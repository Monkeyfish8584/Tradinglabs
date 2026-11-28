"""Parse House Periodic Transaction Report (PTR) PDFs into trade rows.

E-filed PDFs only (text layer). Scanned filings are reported as 'not read'.
All text from PDFs is untrusted: escape before display.
"""
import re
import subprocess
from datetime import datetime

OWNERS = {"SP": "Spouse", "DC": "Dependent child", "JT": "Joint"}
DATE = r"\d{2}/\d{2}/\d{4}"
ANCHOR = re.compile(
    r"^\s*(?:(?P<owner>SP|DC|JT)\s{2,})?(?P<asset>.*?)\s+"
    r"(?P<type>S \(partial\)|P|S|E)\s+(?P<traded>" + DATE + r")\s+(?P<notified>" + DATE + r")\s+"
    r"(?P<amount>\$[\d,]+(?:\s*-\s*(?:\$[\d,]+)?)?|Over \$[\d,]+)?\s*$"
)
# the "F S: New" line (font-garbled header "Filing Status") ends a row's asset text
ROW_END = re.compile(r"^\s*F\s+S\s*:")
AMOUNT_PIECE = re.compile(r"^\$[\d,]+$")
TICKER = re.compile(r"\(([A-Z][A-Z0-9.$\-]{0,7})\)")
ASSET_CODE = re.compile(r"\[([A-Z]{2})\]")
TYPES = {"P": "buy", "S": "sell", "S (partial)": "sell (partial)", "E": "exchange"}


def pdf_text(path):
    return subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True,
                          text=True, check=True).stdout


def _money(s):
    return int(s.replace("$", "").replace(",", ""))


def parse_amount(raw):
    """'$1,001 - $15,000' -> (1001, 15000). Open-ended ranges give high=None."""
    if not raw:
        return None, None
    nums = re.findall(r"\$([\d,]+)", raw)
    vals = [int(n.replace(",", "")) for n in nums]
    if raw.startswith("Over") and vals:
        return vals[0], None
    if len(vals) >= 2:
        return vals[0], vals[1]
    return (vals[0], None) if vals else (None, None)


def parse_ptr_text(text):
    """Return {'filing_id','member','status','district','trades':[...],'warnings':[...]}."""
    out = {"filing_id": None, "member": None, "district": None, "trades": [], "warnings": []}
    m = re.search(r"Filing ID #(\d+)", text)
    out["filing_id"] = m.group(1) if m else None
    m = re.search(r"^\s*Name:\s+(.+?)\s*$", text, re.M)
    out["member"] = re.sub(r"^Hon\.\s*", "", m.group(1)) if m else None
    m = re.search(r"State/District:\s*(\S+)", text)
    out["district"] = m.group(1) if m else None

    cur = None

    def close():
        nonlocal cur
        if not cur:
            return
        asset = re.sub(r"\s+", " ", " ".join(cur["parts"])).strip()
        amount_raw = " ".join(cur["amount"]).strip()
        lo, hi = parse_amount(amount_raw)
        tick = TICKER.findall(asset)
        code = ASSET_CODE.findall(asset)
        row = {
            "owner": OWNERS.get(cur["owner"], "Self"),
            "asset": asset,
            "ticker": tick[-1] if tick else None,
            "asset_code": code[-1] if code else None,
            "type": TYPES[cur["type"]],
            "traded": datetime.strptime(cur["traded"], "%m/%d/%Y").date().isoformat(),
            "notified": datetime.strptime(cur["notified"], "%m/%d/%Y").date().isoformat(),
            "amount_low": lo, "amount_high": hi, "amount_raw": amount_raw,
        }
        if lo is None:
            out["warnings"].append(f"no amount for: {asset[:60]}")
        out["trades"].append(row)
        cur = None

    for line in text.splitlines():
        a = ANCHOR.match(line)
        if a:
            close()
            cur = {"owner": a.group("owner"), "parts": [a.group("asset").strip()],
                   "type": a.group("type"), "traded": a.group("traded"),
                   "notified": a.group("notified"),
                   "amount": [a.group("amount")] if a.group("amount") else []}
            continue
        if cur is None:
            continue
        if ROW_END.match(line):
            close()
            continue
        # continuation line: asset text on the left, maybe an amount piece on the right
        pieces = [p for p in re.split(r"\s{2,}", line.strip()) if p]
        for p in pieces:
            if AMOUNT_PIECE.match(p):
                cur["amount"].append(p)
            elif p:
                cur["parts"].append(p)
    close()
    if not out["trades"]:
        out["warnings"].append("no trade rows found")
    return out


def parse_pdf(path):
    text = pdf_text(path)
    if len(text.strip()) < 100:
        return {"filing_id": None, "trades": [], "warnings": ["no text layer (scanned)"],
                "scanned": True}
    return parse_ptr_text(text)


# ---------------------------------------------------------------------------
# Reading the nightly data file (used by the stock page)
# ---------------------------------------------------------------------------
DATA_URL = "https://raw.githubusercontent.com/Monkeyfish8584/tradinglabs/house-trades-data/house_trades.json"
_LINK_PREFIX = "https://disclosures-clerk.house.gov/public_disc/"


def _norm_ticker(t):
    return re.sub(r"[.\-]", "", (t or "").upper())


def trades_for_ticker(data, ticker, today):
    """Stock trades for one ticker, newest first. Each row gets 'future' if its date is after today."""
    want = _norm_ticker(ticker)
    rows = [dict(t) for t in (data or {}).get("trades", [])
            if t.get("asset_code") == "ST" and t.get("ticker") and _norm_ticker(t["ticker"]) == want]
    for r in rows:
        r["future"] = r["traded"] > today.isoformat()
    rows.sort(key=lambda r: (r["traded"], r["filed"]), reverse=True)
    return rows


def safe_link(url):
    return url if isinstance(url, str) and url.startswith(_LINK_PREFIX) else None


def coverage_text(data):
    c = (data or {}).get("coverage") or {}
    seen = c.get("filings_seen")
    parsed, unread = c.get("parsed"), c.get("not_read")
    day = str((data or {}).get("generated_at") or "")[:10] or "unknown date"
    text = f"House only. Data to {day}."
    if seen is not None and parsed is not None:
        text += f" {parsed} of {seen} trade filings read"
        if unread:
            text += f"; {unread} not read (mostly scanned paper filings, which are not supported yet)"
        text += "."
    return text


def amount_text(low, high):
    if low is None:
        return "—"
    if high is None:
        return f"Over ${low:,}"
    return f"${low:,} – ${high:,}"
