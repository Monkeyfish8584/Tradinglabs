"""Read-only Research Desk page for the Streamlit app.

Market figures come only from ``research-desk/lib/bootstrap.json``. Thesis
paragraphs are the ticker playbooks already written in
``research-desk/lib/research.ts``. Missing snapshot fields stay missing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

BASE_DIR = Path(__file__).resolve().parent
BOOTSTRAP_PATH = BASE_DIR / "research-desk" / "lib" / "bootstrap.json"
RESEARCH_ENGINE_PATH = BASE_DIR / "research-desk" / "lib" / "research.ts"

# Ticker playbooks copied from companyCases in research-desk/lib/research.ts.
# Titles, cases, proof and invalidation are qualitative. They do not add prices.
THESES: dict[str, dict[str, str]] = {
    "USAR": {
        "title": "Rare-earth supply-chain upside, with funding discipline",
        "case": "Your USAR case is a potential rerating in domestic critical-minerals supply as customers seek dependable materials. Separate the nearer-term supply-chain business from longer-dated resource-development value, and test how much of either can reach shareholders.",
        "proof": "For USAR, verify commercial delivery milestones, customer/offtake economics, processing recoveries, the remaining capital budget and any warrants or financing that change the share count.",
        "invalid": "Reassess USAR if delivery or processing milestones slip materially, capital needs increase, or dilution undermines the upside per share.",
    },
    "IBRX": {
        "title": "Immunotherapy uptake versus the cash needed to scale",
        "case": "Your IBRX case is that greater commercial uptake of cancer immunotherapy could outpace expectations after a pullback. The evidence should be sustained product sales, reimbursement and better operating economics, alongside clinically meaningful progress.",
        "proof": "For IBRX, check product-sales progression, approved uses and reimbursement, gross margin, trial evidence and cash burn. Separate approved commercial revenue from pipeline hopes.",
        "invalid": "Reassess IBRX if commercial uptake or reimbursement disappoints, clinical evidence weakens, or financing pressure grows faster than sales can close the cash-flow gap.",
    },
    "ALMU": {
        "title": "Photonics qualification becoming commercial scale",
        "case": "Your ALMU case is an early position in photonics and semiconductor technology before commercial adoption is fully recognised. Its fit with robotics is indirect: the important test is whether customer qualification and design wins turn into repeatable, economically attractive sales.",
        "proof": "For ALMU, distinguish research funding from repeat commercial revenue, verify customer qualification and design wins, and check manufacturing yields, customer concentration and the capital required to scale.",
        "invalid": "Reassess ALMU if qualifications keep slipping, repeat commercial revenue does not emerge, or funding and competition erode the per-share opportunity.",
    },
    "NVO": {
        "title": "A profitable medical franchise after an expectations reset",
        "case": "Your NVO case is that durable demand for diabetes and obesity treatment may be valued too pessimistically after a price reset. The valuation needs support from sustainable prescription demand, pricing, competitive position and earnings rather than a return to old share-price highs.",
        "proof": "For NVO, check treatment demand, realised pricing, supply execution, competitor data, pipeline differentiation and management guidance. Test whether earnings estimates are stabilising.",
        "invalid": "Reassess NVO if pricing, market share or treatment demand deteriorates enough to reduce durable earnings power, or pipeline differentiation no longer supports the valuation case.",
    },
    "UUUU": {
        "title": "Uranium economics plus a separate rare-earth option",
        "case": "Your UUUU case combines exposure to nuclear-fuel demand with a potential critical-minerals opportunity. Value the uranium business and rare-earth opportunity separately, then test whether realised prices, recoveries and processing costs justify the capital committed.",
        "proof": "For UUUU, verify uranium sales and contract terms, inventories, production and processing costs, rare-earth recoveries, remaining capex and balance-sheet capacity.",
        "invalid": "Reassess UUUU if uranium or rare-earth economics weaken, recoveries or commercial deliveries disappoint, or capital requirements materially dilute the shareholder case.",
    },
    "SMR": {
        "title": "Small modular reactor milestones reaching funded orders",
        "case": "Your SMR case is that demand for dependable low-carbon power could support small modular reactor development. Demand for nuclear in general becomes valuable to this company only when licensing, customer commitments, financing and delivery economics form a credible commercial project.",
        "proof": "For SMR, verify the binding nature of customer commitments, customer/project financing, licensing scope, deployment schedules, revenue recognition and the cash needed before delivery.",
        "invalid": "Reassess SMR if prospective projects fail to become financed commitments, delivery economics worsen, or cash requirements and dilution overwhelm the value of the development pipeline.",
    },
}

SQUEEZE_RULES: tuple[tuple[str, str, object], ...] = (
    ("Short float ≥ 20%", "shortFloatPct", lambda n: n >= 20),
    ("Days to cover ≥ 3", "daysToCover", lambda n: n >= 3),
    ("Borrow fee ≥ 10%", "borrowFee", lambda n: n >= 10),
    ("Available shares ≤ 100k", "available", lambda n: n <= 100_000),
    ("Day volume / 20d avg ≥ 1.5×", "relativeVolume", lambda n: n >= 1.5),
)


def load_snapshots() -> list[dict]:
    if not BOOTSTRAP_PATH.exists():
        return []
    payload = json.loads(BOOTSTRAP_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict) and row.get("ticker")]


def upside(snapshot: dict) -> float | None:
    """Same gap as research-desk/lib/model.ts ``upside``."""
    price = snapshot.get("price")
    target = snapshot.get("target")
    if isinstance(price, (int, float)) and isinstance(target, (int, float)) and price > 0:
        return (target / price - 1) * 100
    return None


def squeeze_checks(snapshot: dict) -> list[dict]:
    """Same five heuristics as research-desk/lib/model.ts ``squeezeChecks``."""
    checks: list[dict] = []
    for label, key, test in SQUEEZE_RULES:
        value = snapshot.get(key)
        known = isinstance(value, (int, float)) and not isinstance(value, bool)
        checks.append(
            {
                "label": label,
                "key": key,
                "value": value if known else None,
                "known": known,
                "passed": bool(known and test(value)),
            }
        )
    return checks


def thesis_for(ticker: str) -> dict[str, str] | None:
    thesis = THESES.get(ticker)
    if thesis is None:
        return None
    return dict(thesis)


def _money(value: object, *, signed: bool = False) -> str | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    number = float(value)
    body = f"${abs(number):,.2f}"
    if number < 0:
        return f"-{body}"
    if signed and number > 0:
        return f"+{body}"
    return body


def _percent(value: object, digits: int = 1, *, signed: bool = False) -> str | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    number = float(value)
    text = f"{number:.{digits}f}%"
    if signed and number > 0:
        return f"+{text}"
    return text


def _multiple(value: object) -> str | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return f"{float(value):.1f}×"


def _count(value: object) -> str | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return f"{float(value):,.2f}".rstrip("0").rstrip(".")


def _quote_label(snapshot: dict) -> str | None:
    quote_at = snapshot.get("quoteAt")
    if not isinstance(quote_at, str) or len(quote_at) < 16:
        return None
    return quote_at.replace("T", " ")[:16] + " UTC"


def watchlist_rows(snapshots: list[dict] | None = None) -> list[dict]:
    rows: list[dict] = []
    for snapshot in snapshots if snapshots is not None else load_snapshots():
        gap = upside(snapshot)
        checks = squeeze_checks(snapshot)
        met = sum(1 for check in checks if check["passed"])
        unknown = sum(1 for check in checks if not check["known"])
        thesis = thesis_for(str(snapshot.get("ticker", "")))
        rows.append(
            {
                "ticker": snapshot.get("ticker"),
                "name": snapshot.get("name"),
                "price": snapshot.get("price") if isinstance(snapshot.get("price"), (int, float)) else None,
                "change_pct": snapshot.get("changePct") if isinstance(snapshot.get("changePct"), (int, float)) else None,
                "target": snapshot.get("target") if isinstance(snapshot.get("target"), (int, float)) else None,
                "upside": gap,
                "eps": snapshot.get("eps") if isinstance(snapshot.get("eps"), (int, float)) else None,
                "forward_pe": snapshot.get("forwardPE") if isinstance(snapshot.get("forwardPE"), (int, float)) else None,
                "thesis": None if thesis is None else thesis["title"],
                "squeeze_met": met,
                "squeeze_unknown": unknown,
                "quote_at": _quote_label(snapshot),
            }
        )
    rows.sort(key=lambda row: (row["upside"] is None, -(row["upside"] or 0), str(row["ticker"])))
    return rows


def display_watchlist(rows: list[dict]) -> pd.DataFrame:
    display: list[dict] = []
    for row in rows:
        unknown = row["squeeze_unknown"]
        squeeze = f"{row['squeeze_met']}/5 met"
        if unknown:
            squeeze += f" · {unknown} unknown"
        display.append(
            {
                "Ticker": row["ticker"],
                "Company": row["name"],
                "Price": _money(row["price"]) or "Not in snapshot",
                "Day change": _percent(row["change_pct"], 2, signed=True) or "Not in snapshot",
                "Analyst target": _money(row["target"]) or "Not in snapshot",
                "Upside": _percent(row["upside"], 1, signed=True) or "Not in snapshot",
                "EPS (TTM)": _money(row["eps"]) or "Not in snapshot",
                "Forward P/E": _multiple(row["forward_pe"]) or "Not published",
                "Squeeze": squeeze,
                "Thesis": row["thesis"] or "No playbook in the repo",
            }
        )
    return pd.DataFrame(display)


def valuation_sentence(snapshot: dict) -> str:
    gap = upside(snapshot)
    price = _money(snapshot.get("price"))
    target = _money(snapshot.get("target"))
    if price and target and gap is not None:
        text = (
            f"At {price}, the average analyst target of {target} implies {_percent(gap, 1, signed=True)} upside. "
            "This is the gap to the stored average target, not a verified margin of safety."
        )
    else:
        text = "The snapshot does not include both a price and an average analyst target, so upside is not shown."
    eps = snapshot.get("eps")
    if isinstance(eps, (int, float)) and not isinstance(eps, bool):
        text += f" Trailing EPS is {_money(eps)}."
        forward = _multiple(snapshot.get("forwardPE"))
        if forward:
            text += f" Forward P/E is {forward}."
        else:
            text += " Forward P/E is not in the snapshot."
    return text


def _source_notes(snapshot: dict) -> list[str]:
    notes: list[str] = []
    sources = snapshot.get("sources")
    if not isinstance(sources, dict):
        return notes
    for source in sources.values():
        if isinstance(source, dict) and source.get("error"):
            name = source.get("name") or "A source"
            notes.append(f"{name}: {source['error']}")
    return notes


def render_research_desk() -> None:
    st.title("Research Desk")
    st.caption(
        "Seeded public snapshots from research-desk/lib/bootstrap.json (USAR, IBRX, ALMU, NVO, UUUU, SMR). "
        "Price, analyst target, upside, EPS, forward P/E and short-squeeze inputs are shown only when that file stores them. "
        "Thesis text is the ticker playbook in research-desk/lib/research.ts. "
        "Notes and manual overrides stay in the hosted research-desk database and are not in this file. "
        "Nothing on this page is a live quote."
    )

    snapshots = load_snapshots()
    if not snapshots:
        st.warning("No seeded snapshots were found in research-desk/lib/bootstrap.json.")
        return

    rows = watchlist_rows(snapshots)
    st.dataframe(display_watchlist(rows), use_container_width=True, hide_index=True)
    st.caption(
        "Upside is the stored average analyst target divided by the stored price, minus one. "
        "The squeeze column counts how many of the five repo heuristics are met. Unknown inputs stay unknown and are not treated as zero. "
        "A large target gap means at least 50% upside to that average target."
    )

    by_ticker = {str(snapshot.get("ticker")): snapshot for snapshot in snapshots}
    labels = [f"{row['ticker']} · {row['name']}" for row in rows]
    choice = st.selectbox("Open a stock", labels, index=0)
    ticker = choice.split(" · ", 1)[0]
    snapshot = by_ticker[ticker]
    _render_detail(snapshot)


def _render_detail(snapshot: dict) -> None:
    ticker = str(snapshot.get("ticker"))
    st.subheader(f"{ticker} · {snapshot.get('name') or 'Name not in snapshot'}")
    quote = _quote_label(snapshot)
    if quote:
        st.caption(f"Stored regular-session quote: {quote}.")

    gap = upside(snapshot)
    large_gap = gap is not None and gap >= 50
    checks = squeeze_checks(snapshot)
    met = sum(1 for check in checks if check["passed"])
    unknown = sum(1 for check in checks if not check["known"])

    metrics = st.columns(6)
    price_delta = _percent(snapshot.get("changePct"), 2, signed=True)
    metrics[0].metric("Price", _money(snapshot.get("price")) or "—", delta=price_delta)
    target_help = None
    if isinstance(snapshot.get("analystCount"), int):
        consensus = snapshot.get("consensus")
        target_help = f"{snapshot['analystCount']} analysts"
        if isinstance(consensus, str):
            target_help += f" · {consensus}"
    metrics[1].metric("Analyst target", _money(snapshot.get("target")) or "—", help=target_help)
    metrics[2].metric("Upside", _percent(gap, 1, signed=True) or "—", help="Large target gap" if large_gap else "Below 50% versus the stored average target")
    metrics[3].metric("EPS (TTM)", _money(snapshot.get("eps")) or "—")
    metrics[4].metric(
        "Forward P/E",
        _multiple(snapshot.get("forwardPE")) or "N/A",
        help=None if _multiple(snapshot.get("forwardPE")) else "Not published in this snapshot",
    )
    metrics[5].metric(
        "Short squeeze",
        f"{met}/5",
        help=f"{unknown} unknown" if unknown else "All five inputs are stored on this snapshot",
    )

    closes = snapshot.get("closes")
    close_dates = snapshot.get("closeDates")
    if isinstance(closes, list) and closes:
        chart = pd.DataFrame({"Close": closes})
        if isinstance(close_dates, list) and len(close_dates) == len(closes):
            chart.index = close_dates
        st.markdown("**Stored daily closes**")
        st.line_chart(chart, height=180)
        st.caption("Closes stored with the snapshot. This is the saved series, not a forecast.")

    thesis = thesis_for(ticker)
    st.markdown("**Thesis**")
    if thesis is None:
        st.info("This ticker has numbers in the snapshot and no matching playbook in research-desk/lib/research.ts.")
    else:
        st.markdown(f"**{thesis['title']}**")
        st.write(thesis["case"])
        st.write(valuation_sentence(snapshot))
        st.markdown("**What the playbook says to verify**")
        st.write(thesis["proof"])
        st.markdown("**Invalidation**")
        st.write(thesis["invalid"])

    range_bits: list[str] = []
    for label, key in (("Low", "targetLow"), ("Median", "targetMedian"), ("High", "targetHigh")):
        shown = _money(snapshot.get(key))
        if shown:
            range_bits.append(f"{label} {shown}")
    if range_bits:
        st.caption("Stored target range: " + " · ".join(range_bits) + ". The watchlist target is the average, not this range.")
    if isinstance(snapshot.get("earningsDate"), str):
        st.caption(f"Earnings date stored in the snapshot: {snapshot['earningsDate']}.")

    st.markdown("**Short squeeze**")
    st.caption("Five research heuristics from the repo. They are not a squeeze probability.")
    squeeze_rows = []
    for check in checks:
        if not check["known"]:
            state = "Unknown"
            shown = "Not in snapshot"
        else:
            state = "Met" if check["passed"] else "Not met"
            key = check["key"]
            if key == "shortFloatPct":
                shown = _percent(check["value"], 1) or "Not in snapshot"
            elif key == "borrowFee":
                shown = _percent(check["value"], 2) or "Not in snapshot"
            elif key == "relativeVolume":
                shown = f"{float(check['value']):.2f}×"
            elif key == "available":
                shown = f"{int(check['value']):,}"
            else:
                shown = _count(check["value"]) or "Not in snapshot"
        squeeze_rows.append({"Check": check["label"], "Stored value": shown, "Result": state})
    st.dataframe(pd.DataFrame(squeeze_rows), use_container_width=True, hide_index=True)

    extra: list[str] = []
    if isinstance(snapshot.get("shortDate"), str):
        extra.append(f"Short-interest date in the snapshot: {snapshot['shortDate']}.")
    if snapshot.get("floatDisagreement") is True:
        extra.append("The snapshot flags a disagreement between float estimates.")
    elif snapshot.get("floatDisagreement") is False:
        extra.append("The snapshot does not flag a float-estimate disagreement.")
    notes = _source_notes(snapshot)
    for note in extra + notes:
        st.caption(note)
