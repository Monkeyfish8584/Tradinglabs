"""Nightly House trades job: read new PTR filings and update house_trades.json.

Idempotent and incremental: documents already in the state file are skipped.
Polite: ~1 request/second, backoff on 403/429, aborts after repeated failures.
Environment: YEARS (default "2025,<this year>"), DATA_FILE, MAX_DOCS (default 1500).
"""
import io, json, os, re, sys, tempfile, time, zipfile
import urllib.request, urllib.error
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import house_trades as ht

BASE = "https://disclosures-clerk.house.gov/public_disc"
UA = "Mozilla/5.0 (compatible; tradinglabs-house-trades/0.1; personal research; github.com/Monkeyfish8584/tradinglabs)"
SEC_UA = "tradinglabs personal research github.com/Monkeyfish8584/tradinglabs"
SUFFIXES = {"inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "plc",
            "llc", "lp", "holdings", "holding", "group", "the", "nv", "sa", "ag"}
NOISE = {"common", "stock", "class", "a", "b", "c", "ordinary", "shares", "share", "adr", "ads",
         "com", "new", "cl"}


def normalize_name(s):
    s = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", s.lower())
    s = s.replace("&", " and ")
    words = re.findall(r"[a-z0-9]+", s)
    words = [w for w in words if w not in SUFFIXES and w not in NOISE]
    return " ".join(words)


def build_ticker_map(sec_json, aliases=None):
    """name -> ticker; names that map to more than one ticker are dropped (ambiguous)."""
    seen = {}
    for rec in (sec_json.values() if isinstance(sec_json, dict) else sec_json):
        key = normalize_name(rec["title"])
        seen.setdefault(key, set()).add(rec["ticker"])
    out = {k: next(iter(v)) for k, v in seen.items() if len(v) == 1 and k}
    for k, v in (aliases or {}).items():
        out[normalize_name(k)] = v
    return out


def is_late(traded_iso, filed_iso):
    return (date.fromisoformat(filed_iso) - date.fromisoformat(traded_iso)).days > 45


def http_get(url, ua=UA, state=None):
    for attempt in range(3):
        time.sleep(1.0)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua})
            with urllib.request.urlopen(req, timeout=60) as r:
                if state is not None:
                    state["fail_streak"] = 0
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (403, 429) and attempt < 2:
                time.sleep(30 * (attempt + 1))
                continue
            if e.code == 404:
                return None
        except Exception:
            pass
    if state is not None:
        state["fail_streak"] = state.get("fail_streak", 0) + 1
    return None


def read_index(year, st):
    z = http_get(f"{BASE}/financial-pdfs/{year}FD.ZIP", state=st)
    if not z:
        return None
    zf = zipfile.ZipFile(io.BytesIO(z))
    txt = next(n for n in zf.namelist() if n.lower().endswith(".txt"))
    lines = zf.read(txt).decode("utf-8", "replace").splitlines()
    header = lines[0].split("\t")
    rows = [dict(zip(header, p.split("\t"))) for p in lines[1:] if len(p.split("\t")) == len(header)]
    return [r for r in rows if r.get("FilingType") == "P"]


def new_state():
    return {"generated_at": None,
            "coverage": {"years": [], "filings_seen": 0, "parsed": 0, "parsed_with_warnings": 0,
                         "not_read": 0, "rows": 0},
            "trades": [], "not_read": [], "done_docs": []}


def fmt_date(mdy):
    return datetime.strptime(mdy, "%m/%d/%Y").date().isoformat()


def process_doc(row, year, tmap, st_state):
    doc = row["DocID"]
    url = f"{BASE}/ptr-pdfs/{year}/{doc}.pdf"
    member = " ".join(x for x in (row.get("First"), row.get("Last"), row.get("Suffix")) if x).strip()
    data = http_get(url, state=st_state)
    if data is None:
        return None
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(data); f.flush()
        parsed = ht.parse_pdf(f.name)
    filed = fmt_date(row["FilingDate"])
    if parsed.get("scanned"):
        return {"not_read": {"doc_id": doc, "member": member, "filed": filed, "link": url,
                             "reason": "scanned paper filing (OCR not enabled yet)"}}
    if not parsed["trades"]:
        return {"not_read": {"doc_id": doc, "member": member, "filed": filed, "link": url,
                             "reason": "; ".join(parsed["warnings"]) or "no rows found"}}
    trades = []
    for t in parsed["trades"]:
        ticker, how = t["ticker"], "filing"
        if not ticker and t["asset_code"] == "ST":
            ticker = tmap.get(normalize_name(t["asset"])); how = "sec-name" if ticker else None
        trades.append({"doc_id": doc, "member": parsed["member"] or member,
                       "district": parsed["district"] or row.get("StateDst"), "filed": filed,
                       "traded": t["traded"], "owner": t["owner"], "asset": t["asset"],
                       "asset_code": t["asset_code"], "ticker": ticker, "ticker_source": how,
                       "type": t["type"], "amount_low": t["amount_low"], "amount_high": t["amount_high"],
                       "late": is_late(t["traded"], filed), "link": url})
    return {"trades": trades, "warn": bool(parsed["warnings"])}


def main():
    path = os.environ.get("DATA_FILE", "house_trades.json")
    this_year = datetime.now(timezone.utc).year
    years = [int(y) for y in os.environ.get("YEARS", f"2025,{this_year}").split(",")]
    max_docs = int(os.environ.get("MAX_DOCS", "1500"))
    state = json.load(open(path)) if os.path.exists(path) else new_state()
    st = {"fail_streak": 0}
    sec = http_get("https://www.sec.gov/files/company_tickers.json", ua=SEC_UA, state=st)
    aliases = json.load(open("data/house_aliases.json")) if os.path.exists("data/house_aliases.json") else {}
    tmap = build_ticker_map(json.loads(sec), aliases) if sec else build_ticker_map([], aliases)
    done = set(state["done_docs"]); processed = 0; seen = 0; aborted = False
    for year in sorted(years):
        rows = read_index(year, st)
        if rows is None:
            print(f"index for {year} unavailable"); continue
        seen += len(rows)
        for row in rows:
            if row["DocID"] in done:
                continue
            if processed >= max_docs:
                break
            res = process_doc(row, year, tmap, st)
            if res is None:
                if st["fail_streak"] >= 5:
                    aborted = True; break
                continue
            processed += 1
            done.add(row["DocID"])
            if "trades" in res:
                state["trades"] += res["trades"]
                state["coverage"]["parsed"] += 1
                state["coverage"]["parsed_with_warnings"] += int(res["warn"])
            else:
                state["not_read"].append(res["not_read"])
        if aborted:
            break
    c = state["coverage"]
    c["years"] = sorted(set(c["years"]) | set(years))
    if seen:
        c["filings_seen"] = seen
    c["not_read"] = len(state["not_read"]); c["rows"] = len(state["trades"])
    state["done_docs"] = sorted(done)
    state["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    json.dump(state, open(path, "w"), separators=(",", ":"))
    print(f"processed {processed} new filings; {c['rows']} rows; {c['not_read']} not read; aborted={aborted}")
    sys.exit(1 if aborted else 0)


if __name__ == "__main__":
    main()
