"""Senate recon (phase S0): can we read Senate eFD periodic transaction reports, and what do they look like?

Does the site's own public-search steps (session cookie, accept the public-use agreement), lists
senators' periodic transaction reports since START, then saves ~25 detail pages and a request log.
Polite: 1.5 s between requests. Personal, non-commercial research use only.
Nothing here was tested against the live site when written; the log shows what really happened.
"""
import html, http.cookiejar, json, os, re, sys, time, urllib.parse, urllib.request, urllib.error

BASE = "https://efdsearch.senate.gov"
UA = "Mozilla/5.0 (compatible; tradinglabs-senate-recon/0.1; personal research; github.com/Monkeyfish8584/tradinglabs)"
START = os.environ.get("START", "01/01/2025")
OUT = "senate_recon"
log = []
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def call(url, data=None, headers=None):
    time.sleep(1.5)
    h = {"User-Agent": UA, **(headers or {})}
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=h)
    try:
        with opener.open(req, timeout=60) as r:
            raw = r.read()
            log.append({"url": url, "method": "POST" if data is not None else "GET", "status": r.status, "bytes": len(raw), "final": r.geturl()})
            return raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        log.append({"url": url, "status": e.code, "body": e.read()[:300].decode("utf-8", "replace")})
    except Exception as e:
        log.append({"url": url, "error": str(e)})
    return None


def cookie(name):
    return next((c.value for c in jar if c.name == name), "")


def finish(extra=None):
    os.makedirs(OUT, exist_ok=True)
    json.dump({"log": log, **(extra or {})}, open(f"{OUT}/report.json", "w"), indent=1)
    print(json.dumps(extra or {}, indent=1)[:1500]); print("requests:", len(log), [l.get("status") or l.get("error") for l in log][:12])


os.makedirs(f"{OUT}/pages", exist_ok=True)
home = call(f"{BASE}/search/home/")
tok = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', home or "")
if not tok:
    finish({"stage": "home", "note": "no csrf token found on home page", "sample": (home or "")[:500]})
    sys.exit("could not start a session")
call(f"{BASE}/search/home/", {"prohibition_agreement": "1", "csrfmiddlewaretoken": tok.group(1)}, {"Referer": f"{BASE}/search/home/"})
call(f"{BASE}/search/")
ct = cookie("csrftoken")
reports, start = [], 0
while True:
    res = call(f"{BASE}/search/report/data/",
               {"start": start, "length": 100, "report_types": "[11]", "filer_types": "[1]", "submitted_start_date": f"{START} 00:00:00",
                "candidate_state": "", "senator_state": "", "office_id": "", "first_name": "", "last_name": "",
                "csrfmiddlewaretoken": ct},
               {"Referer": f"{BASE}/search/", "X-CSRFToken": ct, "X-Requested-With": "XMLHttpRequest"})
    try:
        j = json.loads(res)
    except Exception:
        finish({"stage": "search", "note": "search did not return JSON", "sample": (res or "")[:500]})
        sys.exit("search failed")
    reports += j.get("data", [])
    total = j.get("recordsTotal", 0)
    start += 100
    if start >= total or not j.get("data"):
        break
    if start >= 500:
        break
rows = []
for r in reports:
    m = re.search(r'href="([^"]+)"', r[3]) if len(r) > 3 else None
    rows.append({"first": r[0], "last": r[1], "type": r[2], "link": html.unescape(m.group(1)) if m else None,
                 "title": re.sub(r"<[^>]+>", "", r[3]).strip(), "date": r[4] if len(r) > 4 else None})
paper = [x for x in rows if x["link"] and "/view/paper/" in x["link"]]
elec = [x for x in rows if x["link"] and "/view/ptr/" in x["link"]]
saved = []
for x in elec[:20] + paper[:5]:
    page = call(BASE + x["link"], headers={"Referer": f"{BASE}/search/"})
    if page:
        name = re.sub(r"[^A-Za-z0-9]", "_", x["link"].strip("/"))[-40:]
        open(f"{OUT}/pages/{name}.html", "w", encoding="utf-8").write(page)
        saved.append({"file": name, "row": x})
finish({"records_total": total, "listed": len(rows), "electronic": len(elec), "paper": len(paper), "saved": saved,
        "first_rows": rows[:5]})
