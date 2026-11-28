"""Phase 0 recon: download the House Clerk index and ~40 sample PTR PDFs.

Writes into recon/ (index files, sample PDFs, report.json). Polite: ~1 request/sec.
"""
import io, json, os, sys, time, zipfile, random
import urllib.request, urllib.error

YEAR = int(os.environ.get("YEAR", "2025"))
BASE = "https://disclosures-clerk.house.gov/public_disc"
UA = "Mozilla/5.0 (compatible; tradinglabs-recon/0.1; personal research)"
OUT = "recon"
report = {"year": YEAR, "requests": [], "notes": []}


def get(url):
    time.sleep(1.0)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
            report["requests"].append({"url": url, "status": r.status, "bytes": len(data),
                                       "type": r.headers.get("Content-Type")})
            return data
    except urllib.error.HTTPError as e:
        report["requests"].append({"url": url, "status": e.code})
        return None
    except Exception as e:
        report["requests"].append({"url": url, "error": str(e)})
        return None


os.makedirs(f"{OUT}/pdfs", exist_ok=True)
z = get(f"{BASE}/financial-pdfs/{YEAR}FD.ZIP")
if not z:
    json.dump(report, open(f"{OUT}/report.json", "w"), indent=2)
    sys.exit("index download failed")
zf = zipfile.ZipFile(io.BytesIO(z))
report["zip_members"] = zf.namelist()
for n in zf.namelist():
    open(f"{OUT}/{n}", "wb").write(zf.read(n))

txt = next((n for n in zf.namelist() if n.lower().endswith(".txt")), None)
rows = []
if txt:
    lines = zf.read(txt).decode("utf-8", "replace").splitlines()
    header = lines[0].split("\t")
    report["header"] = header
    for ln in lines[1:]:
        parts = ln.split("\t")
        if len(parts) == len(header):
            rows.append(dict(zip(header, parts)))
report["total_rows"] = len(rows)
ft_key = next((h for h in report.get("header", []) if "FilingType" in h.replace(" ", "")), None)
id_key = next((h for h in report.get("header", []) if "DocID" in h.replace(" ", "")), None)
from collections import Counter
if ft_key:
    report["filing_type_counts"] = Counter(r[ft_key] for r in rows)
ptr = [r for r in rows if ft_key and r[ft_key] == "P"]
report["ptr_count"] = len(ptr)
if id_key:
    report["ptr_docid_length_counts"] = Counter(len(r[id_key]) for r in ptr)
    random.seed(1)
    by_len = {}
    for r in ptr:
        by_len.setdefault(len(r[id_key]), []).append(r)
    sample = []
    for L, rs in by_len.items():
        sample += random.sample(rs, min(len(rs), 25 if L == 8 else 15))
    sample = sample[:40]
    report["sample"] = []
    for r in sample:
        d = r[id_key]
        data = get(f"{BASE}/ptr-pdfs/{YEAR}/{d}.pdf")
        ok = bool(data)
        if ok:
            open(f"{OUT}/pdfs/{d}.pdf", "wb").write(data)
        report["sample"].append({"doc_id": d, "ok": ok, "row": r})
        fails = sum(1 for s in report["sample"] if not s["ok"])
        if fails >= 5:
            report["notes"].append("stopped after 5 failures")
            break
json.dump(report, open(f"{OUT}/report.json", "w"), indent=2, default=dict)
print(json.dumps({k: report[k] for k in report if k not in ("requests", "sample")}, indent=1, default=dict))
