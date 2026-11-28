"""Nightly company-insider job: collect open-market insider BUYS (Form 4, code P) from SEC EDGAR.

Reads each completed day's EDGAR daily form index, downloads each new Form 4 / 4/A submission, keeps
open-market purchases and writes insider_buys.json. Resumable: a day is only marked done when fully
read. Polite: about 8 requests/second at most (SEC limit is 10), real contact in the User-Agent.
Environment: DATA_FILE, INITIAL_DAYS (default 30), MAX_DOCS (default 8000), KEEP_DAYS (default 180).
"""
import json, os, re, sys, time
import urllib.request, urllib.error
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from macro_desk_insights import parse_form4

UA = "Tradinglabs MacroDesk personal research (github.com/Monkeyfish8584/tradinglabs)"
INDEX_LINE = re.compile(r"^(4/A|4)\s+(.*?)\s+(\d{3,10})\s+(\d{8})\s+(edgar/data/\S+\.txt)\s*$")
XML_DOC = re.compile(r"<ownershipDocument>.*?</ownershipDocument>", re.S)


def parse_index(text):
    """Unique Form 4 / 4/A submissions from a daily form index, by accession."""
    out, seen = [], set()
    for line in text.splitlines():
        m = INDEX_LINE.match(line)
        if not m:
            continue
        form, _name, _cik, filed, path = m.groups()
        acc = os.path.basename(path)[:-4]
        if acc in seen:
            continue
        seen.add(acc)
        out.append({"form": form, "filed": f"{filed[:4]}-{filed[4:6]}-{filed[6:]}", "path": path, "accession": acc})
    return out


def issuer_of(xml_text):
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None, None
    name = ticker = None
    for node in root.iter():
        tag = node.tag.split("}")[-1]
        if tag == "issuerName" and not name:
            name = (node.text or "").strip()
        elif tag == "issuerTradingSymbol" and not ticker:
            ticker = (node.text or "").strip().upper()
    return name, ticker


def buys_from_submission(text, entry):
    m = XML_DOC.search(text)
    if not m:
        return []
    xml_text = m.group(0)
    name, ticker = issuer_of(xml_text)
    rows = parse_form4(xml_text, filed_at=entry["filed"], amended=entry["form"] == "4/A", accession=entry["accession"])
    out = []
    for t in rows:
        if t["type"] != "buy":
            continue
        out.append({"ticker": ticker, "company": name, "person": t["person"], "role": t["role"],
                    "traded": t["traded_at"], "filed": entry["filed"], "shares": t["shares"],
                    "price": t["price"], "value": t["value"], "amended": t["amended"],
                    "accession": entry["accession"],
                    "link": f"https://www.sec.gov/Archives/{entry['path']}"})
    return out


def dedupe(buys):
    """Same person, company, date, shares and price: keep the amended one, else the latest filed."""
    best = {}
    for b in buys:
        key = (b["ticker"], b["person"], b["traded"], b["shares"], b["price"])
        cur = best.get(key)
        if cur is None or (b["amended"], b["filed"]) > (cur["amended"], cur["filed"]):
            best[key] = b
    return list(best.values())


def business_days(start, end):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def get(url, state):
    for attempt in range(3):
        time.sleep(0.125)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                state["fail_streak"] = 0
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (403, 429):
                time.sleep(30 * (attempt + 1))
        except Exception:
            pass
    state["fail_streak"] = state.get("fail_streak", 0) + 1
    return None


def run(data, today, fetch, max_docs=8000, initial_days=30, keep_days=180):
    """Process missing completed days into data. ``fetch(url)`` returns text, None (404) or raises."""
    done = set(data.get("days_done", []))
    start = today - timedelta(days=initial_days)
    used = 0
    aborted = False
    for day in business_days(start, today - timedelta(days=1)):
        iso = day.isoformat()
        if iso in done:
            continue
        q = (day.month - 1) // 3 + 1
        idx = fetch(f"https://www.sec.gov/Archives/edgar/daily-index/{day.year}/QTR{q}/form.{day:%Y%m%d}.idx")
        if idx is None:
            done.add(iso)  # no index for that day (holiday)
            continue
        entries = parse_index(idx)
        if used + len(entries) > max_docs and used > 0:
            break
        new = []
        for e in entries:
            text = fetch(f"https://www.sec.gov/Archives/{e['path']}")
            used += 1
            if text is None:
                if fetch.state.get("fail_streak", 0) >= 5:
                    aborted = True
                    break
                continue
            new += buys_from_submission(text, e)
        if aborted:
            break
        data["buys"] = dedupe(data.get("buys", []) + new)
        done.add(iso)
    cutoff = (today - timedelta(days=keep_days)).isoformat()
    data["buys"] = sorted((b for b in data.get("buys", []) if b["filed"] >= cutoff),
                          key=lambda b: (b["filed"], b["traded"]), reverse=True)
    data["days_done"] = sorted(d for d in done if d >= cutoff)
    data["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data["coverage"] = {"days_from": min(data["days_done"]) if data["days_done"] else None,
                        "days_to": max(data["days_done"]) if data["days_done"] else None,
                        "buys": len(data["buys"]), "docs_read_this_run": used}
    return aborted


def main():
    path = os.environ.get("DATA_FILE", "insider_buys.json")
    data = json.load(open(path)) if os.path.exists(path) else {"buys": [], "days_done": []}
    st = {"fail_streak": 0}

    def fetch(url):
        return get(url, st)
    fetch.state = st
    aborted = run(data, datetime.now(timezone.utc).date(), fetch,
                  int(os.environ.get("MAX_DOCS", "8000")), int(os.environ.get("INITIAL_DAYS", "30")),
                  int(os.environ.get("KEEP_DAYS", "180")))
    json.dump(data, open(path, "w"), separators=(",", ":"))
    print(data["coverage"], "aborted" if aborted else "ok")
    sys.exit(1 if aborted else 0)


if __name__ == "__main__":
    main()
