"""Survey the scanned (paper) House filings that the nightly job could not read.

Reads the not_read list from house_trades.json, downloads each scanned PDF, OCRs page 1 (best of
4 rotations), classifies it, and saves a report plus small page-1 thumbnails of anything that looks
like a filled-in form. Usage: house_scan_survey.py DATA_JSON OUT_DIR   (or --local PDF_DIR OUT_DIR)
"""
import glob, json, os, re, subprocess, sys, tempfile, time, urllib.request
from PIL import Image

UA = "Mozilla/5.0 (compatible; tradinglabs-house-trades/0.1; personal research; github.com/Monkeyfish8584/tradinglabs)"


def ocr_best(png):
    im = Image.open(png).convert("L")
    best = ("", -1, 0)
    for rot in (0, 90, 180, 270):
        p = png + f".r{rot}.png"
        im.rotate(rot, expand=True).save(p)
        t = subprocess.run(["tesseract", p, "-", "--psm", "6"], capture_output=True, text=True).stdout
        os.remove(p)
        score = len(re.findall(r"[A-Za-z]{4,}", t))
        if score > best[1]:
            best = (t, score, rot)
    return best


def classify(text):
    low = re.sub(r"\s+", " ", text.lower())
    if re.search(r"nothing to report|no transactions to report|no reportable|none to report", low):
        return "nil"
    if re.search(r"dear (mr|madam|clerk)|sincerely|respectfully", low):
        return "letter"
    if "periodic transaction report" in low or "full asset name" in low:
        return "form"
    return "other"


def survey(pdf, outdir, name):
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["pdftoppm", "-r", "150", "-f", "1", "-l", "1", "-png", pdf, f"{td}/p"], check=True)
        png = sorted(glob.glob(f"{td}/p*.png"))[0]
        text, score, rot = ocr_best(png)
        kind = classify(text)
        pages = int(re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", pdf], capture_output=True, text=True).stdout).group(1))
        thumb = None
        if kind in ("form", "other"):
            im = Image.open(png).convert("L").rotate(rot, expand=True)
            im.thumbnail((1100, 1100))
            thumb = f"thumbs/{name}.jpg"
            os.makedirs(f"{outdir}/thumbs", exist_ok=True)
            im.save(f"{outdir}/{thumb}", quality=55)
        return {"kind": kind, "pages": pages, "rotation": rot, "words": score, "thumb": thumb,
                "text": re.sub(r"\s+", " ", text)[:500]}


def main():
    a = sys.argv[1:]
    out = a[-1]
    os.makedirs(out, exist_ok=True)
    items = []
    if a[0] == "--local":
        for f in sorted(glob.glob(f"{a[1]}/*.pdf")):
            items.append({"doc_id": os.path.basename(f)[:-4], "member": "?", "path": f})
    else:
        data = json.load(open(a[0]))
        for r in data["not_read"]:
            if "scanned" in r["reason"]:
                items.append({"doc_id": r["doc_id"], "member": r["member"], "filed": r["filed"], "link": r["link"]})
    report = []
    for it in items:
        path = it.get("path")
        if not path:
            time.sleep(1.0)
            path = f"{out}/_{it['doc_id']}.pdf"
            try:
                req = urllib.request.Request(it["link"], headers={"User-Agent": UA})
                open(path, "wb").write(urllib.request.urlopen(req, timeout=60).read())
            except Exception as e:
                report.append({**it, "kind": "download_failed", "error": str(e)}); continue
        try:
            res = survey(path, out, it["doc_id"])
        except Exception as e:
            res = {"kind": "error", "error": str(e)}
        if not it.get("path"):
            os.remove(path)
        report.append({**{k: v for k, v in it.items() if k != "path"}, **res})
        print(it["doc_id"], res["kind"], flush=True)
    json.dump(report, open(f"{out}/survey.json", "w"), indent=1)
    from collections import Counter
    print(Counter(r["kind"] for r in report))


if __name__ == "__main__":
    main()
