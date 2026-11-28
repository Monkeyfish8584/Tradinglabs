"""Aggregations for the insider-buys page: Congress (House) trades and company insider buys.

Pure functions over the nightly JSON files, so they can be tested without Streamlit.
"""
from datetime import date, timedelta

COMPANY_DATA_URL = "https://raw.githubusercontent.com/Monkeyfish8584/tradinglabs/insider-data/insider_buys.json"
SEC_PREFIX = "https://www.sec.gov/"
CLUSTER_MIN = 3


def _cut(today, days):
    return (today - timedelta(days=days)).isoformat()


def congress_view(data, today, days=90, kind="buy"):
    """Stock trades filed in the last ``days`` days. kind: 'buy', 'sell' or 'all'.

    Returns {'summary': [...by ticker...], 'rows': [...newest first...]}. Window is by filing date,
    because the filing is when the trade became public.
    """
    cut = _cut(today, days)
    rows = []
    for t in (data or {}).get("trades", []):
        if t.get("asset_code") != "ST" or not t.get("ticker") or t.get("filed", "") < cut:
            continue
        ttype = str(t.get("type", ""))
        if kind == "buy" and ttype != "buy":
            continue
        if kind == "sell" and not ttype.startswith("sell"):
            continue
        r = dict(t)
        r["future"] = r["traded"] > today.isoformat()
        rows.append(r)
    rows.sort(key=lambda r: (r["filed"], r["traded"]), reverse=True)
    by = {}
    for r in rows:
        s = by.setdefault(r["ticker"], {"ticker": r["ticker"], "company": r["asset"], "members": set(),
                                         "trades": 0, "latest": ""})
        s["members"].add(r["member"])
        s["trades"] += 1
        s["latest"] = max(s["latest"], r["filed"])
    summary = []
    for s in by.values():
        s["members"] = len(s["members"])
        s["cluster"] = s["members"] >= CLUSTER_MIN
        summary.append(s)
    summary.sort(key=lambda s: (-s["members"], -s["trades"], s["ticker"]))
    return {"summary": summary, "rows": rows}


def company_view(data, today, days=30, min_value=0):
    """Open-market insider buys filed in the last ``days`` days, with total value at least ``min_value``.

    Rows without a published price have no value: they stay only when min_value is 0.
    """
    cut = _cut(today, days)
    rows = []
    for b in (data or {}).get("buys", []):
        if b.get("filed", "") < cut:
            continue
        v = b.get("value")
        if min_value and (v is None or v < min_value):
            continue
        rows.append(dict(b))
    rows.sort(key=lambda r: (r["filed"], r["traded"]), reverse=True)
    by = {}
    for r in rows:
        key = r.get("ticker") or r.get("company") or "?"
        s = by.setdefault(key, {"ticker": r.get("ticker"), "company": r.get("company"), "people": set(),
                                 "buys": 0, "value": 0.0, "unpriced": 0, "latest": ""})
        s["people"].add(r["person"])
        s["buys"] += 1
        if r.get("value") is None:
            s["unpriced"] += 1
        else:
            s["value"] += r["value"]
        s["latest"] = max(s["latest"], r["filed"])
    summary = []
    for s in by.values():
        s["people"] = len(s["people"])
        s["cluster"] = s["people"] >= CLUSTER_MIN
        summary.append(s)
    summary.sort(key=lambda s: (-s["value"], s["ticker"] or ""))
    return {"summary": summary, "rows": rows}


def sec_link(url):
    return url if isinstance(url, str) and url.startswith(SEC_PREFIX) else None


def company_coverage(data):
    c = (data or {}).get("coverage") or {}
    if not c.get("days_from"):
        return "No days have been read yet."
    return (f"Open-market purchases (SEC code P) from Form 4 filings, {c['days_from']} to {c['days_to']}. "
            "Awards, option exercises and sales are left out. Filings arrive up to two business days after the trade.")
