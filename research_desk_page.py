"""Research Desk page for the Streamlit app.

Seeded market figures come from ``research-desk/lib/bootstrap.json``. A name
added on the page is fetched from Yahoo Finance and Stock Analysis, and any
field those pages do not publish stays blank. Thesis paragraphs are the ticker
playbooks already written in ``research-desk/lib/research.ts``.
"""

from __future__ import annotations

import html
import json
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

from research_desk_quotes import QuoteError, fetch_new_snapshot, fetch_trend_snapshot, normalize_ticker, refresh_quote

# Display name, then the Yahoo symbol. GER30 is the DAX index Yahoo publishes as ^GDAXI.
MACRO_MARKETS: tuple[tuple[str, str], ...] = (
    ("BTCUSD", "BTC-USD"),
    ("US500", "^GSPC"),
    ("US100", "^NDX"),
    ("US30", "^DJI"),
    ("ETHUSD", "ETH-USD"),
    ("UK100", "^FTSE"),
    ("GER30", "^GDAXI"),
)

CLOSE_WINDOWS = (30, 60, 90)
DEFAULT_CLOSE_WINDOW = 60

BASE_DIR = Path(__file__).resolve().parent
BOOTSTRAP_PATH = BASE_DIR / "research-desk" / "lib" / "bootstrap.json"
RESEARCH_ENGINE_PATH = BASE_DIR / "research-desk" / "lib" / "research.ts"
QUOTE_CACHE_PATH = Path(tempfile.gettempdir()) / "tradinglabs-desk-quotes.json"

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


def load_quote_cache(path: Path | None = None) -> dict:
    """Read refreshed quotes saved for this running app. A missing or broken file is empty."""
    cache_path = QUOTE_CACHE_PATH if path is None else path
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    refreshed = payload.get("refreshed")
    added = payload.get("added")
    errors = payload.get("errors")
    return {
        "refreshed": refreshed if isinstance(refreshed, dict) else {},
        "added": added if isinstance(added, dict) else {},
        "refresh_at": payload.get("refresh_at") if isinstance(payload.get("refresh_at"), str) else None,
        "errors": [str(item) for item in errors] if isinstance(errors, list) else [],
    }


def save_quote_cache(payload: dict, path: Path | None = None) -> None:
    cache_path = QUOTE_CACHE_PATH if path is None else path
    cache_path.write_text(json.dumps(payload), encoding="utf-8")


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
    if isinstance(price, (int, float)) and isinstance(target, (int, float)) and not isinstance(price, bool) and price > 0:
        return (target / price - 1) * 100
    return None


def _close_pairs(snapshot: dict) -> list[tuple[date | None, float]]:
    closes = snapshot.get("closes")
    if not isinstance(closes, list):
        return []
    dates = snapshot.get("closeDates")
    pairs: list[tuple[date | None, float]] = []
    for index, close in enumerate(closes):
        if isinstance(close, bool) or not isinstance(close, (int, float)):
            continue
        day = None
        if isinstance(dates, list) and index < len(dates) and isinstance(dates[index], str):
            try:
                day = date.fromisoformat(dates[index][:10])
            except ValueError:
                day = None
        pairs.append((day, float(close)))
    if pairs and all(day is not None for day, _ in pairs):
        pairs.sort(key=lambda item: item[0] or date.min)
    return pairs


def _closes(snapshot: dict) -> list[float]:
    return [close for _, close in _close_pairs(snapshot)]


def daily_trend(snapshot: dict) -> str | None:
    """Up or Down only when the latest close is beyond each of the previous three closes."""
    values = _closes(snapshot)
    if len(values) < 4:
        return None
    latest = values[-1]
    previous = values[-4:-1]
    if all(latest > item for item in previous):
        return "Up"
    if all(latest < item for item in previous):
        return "Down"
    return "Flat"


def weekly_trend(snapshot: dict) -> str | None:
    """This week's close compared with the previous week's close."""
    pairs = _close_pairs(snapshot)
    if not pairs or any(day is None for day, _ in pairs):
        return None
    latest_day = pairs[-1][0]
    if latest_day is None:
        return None
    this_key = latest_day.isocalendar()[:2]
    previous_key = (latest_day - timedelta(days=7)).isocalendar()[:2]
    this_closes = [close for day, close in pairs if day is not None and day.isocalendar()[:2] == this_key]
    previous_closes = [close for day, close in pairs if day is not None and day.isocalendar()[:2] == previous_key]
    if not this_closes or not previous_closes:
        return None
    this_close = this_closes[-1]
    previous_close = previous_closes[-1]
    if this_close > previous_close:
        return "Up"
    if this_close < previous_close:
        return "Down"
    return "Flat"


def rsi_14(snapshot: dict) -> float | None:
    """Wilder RSI(14) of the stored daily closes. Missing history stays missing."""
    values = _closes(snapshot)
    if len(values) < 15:
        return None
    changes = [values[index] - values[index - 1] for index in range(1, len(values))]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    average_gain = sum(gains[:14]) / 14
    average_loss = sum(losses[:14]) / 14
    for gain, loss in zip(gains[14:], losses[14:]):
        average_gain = (average_gain * 13 + gain) / 14
        average_loss = (average_loss * 13 + loss) / 14
    if average_gain == 0 and average_loss == 0:
        return None
    if average_loss == 0:
        return 100.0
    strength = average_gain / average_loss
    return 100 - (100 / (1 + strength))


def average_position(snapshot: dict) -> str | None:
    """Whether the price is above or below the daily 200-day moving average."""
    values = _closes(snapshot)
    if len(values) < 200:
        return None
    average = sum(values[-200:]) / 200
    price = snapshot.get("price")
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        price = values[-1]
    if float(price) > average:
        return "Above"
    if float(price) < average:
        return "Below"
    return "At the average"


def close_window(snapshot: dict, days: int) -> tuple[list[float], list[str] | None]:
    """Closes inside the last ``days`` calendar days, ending on the latest stored close."""
    pairs = _close_pairs(snapshot)
    if not pairs:
        return [], None
    if any(day is None for day, _ in pairs):
        return [close for _, close in pairs], None
    latest = pairs[-1][0]
    if latest is None:
        return [close for _, close in pairs], None
    start = latest - timedelta(days=days - 1)
    chosen = [(day, close) for day, close in pairs if day is not None and day >= start]
    return [close for _, close in chosen], [day.isoformat() for day, _ in chosen]


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


def trend_text(value: object) -> str:
    if value in {"Up", "Down", "Flat"}:
        return str(value)
    return "Not enough closes"


def load_macro_rows(getter=None) -> list[dict]:
    """Daily and weekly trend for the macro markets. A failed feed stays blank."""
    rows: list[dict] = []
    for label, symbol in MACRO_MARKETS:
        try:
            snapshot = fetch_trend_snapshot(symbol, getter, span="6mo")
        except QuoteError:
            rows.append({"label": label, "daily": None, "weekly": None, "available": False})
            continue
        rows.append(
            {
                "label": label,
                "daily": daily_trend(snapshot),
                "weekly": weekly_trend(snapshot),
                "available": True,
            }
        )
    return rows


def _trend_class(value: object) -> str:
    if value == "Up":
        return "macro-up"
    if value == "Down":
        return "macro-down"
    if value == "Flat":
        return "macro-flat"
    return "macro-missing"


def macro_trends_html(rows: list[dict]) -> str:
    cards: list[str] = []
    for row in rows:
        daily = trend_text(row.get("daily")) if row.get("available") else "Unavailable"
        weekly = trend_text(row.get("weekly")) if row.get("available") else "Unavailable"
        cards.append(
            "<div class=\"macro-card\">"
            f"<div class=\"macro-name\">{html.escape(str(row.get('label') or ''))}</div>"
            f"<div>Daily <span class=\"{_trend_class(row.get('daily') if row.get('available') else None)}\">{html.escape(daily)}</span></div>"
            f"<div>Weekly <span class=\"{_trend_class(row.get('weekly') if row.get('available') else None)}\">{html.escape(weekly)}</span></div>"
            "</div>"
        )
    return "<div class=\"macro-strip\">" + "".join(cards) + "</div>"


@st.cache_data(ttl=900, show_spinner=False)
def cached_macro_rows() -> list[dict]:
    return load_macro_rows()


def render_macro_trends() -> None:
    """Daily and weekly trend for the macro markets, shown above either page."""
    st.markdown("**Macro trends**")
    with st.spinner("Loading macro trends…"):
        try:
            rows = cached_macro_rows()
        except Exception:
            st.caption("Macro trends could not be loaded.")
            return
    st.markdown(
        """
        <style>
        .macro-strip { display: flex; gap: 0.55rem; flex-wrap: wrap; }
        .macro-card {
          flex: 1 1 7.5rem; border: 1px solid rgba(128,128,128,0.35);
          border-radius: 8px; padding: 0.4rem 0.6rem; line-height: 1.35;
        }
        .macro-name { font-weight: 700; }
        .macro-up { color: #1b7f4a; font-weight: 700; }
        .macro-down { color: #b42318; font-weight: 700; }
        .macro-flat, .macro-missing { font-weight: 700; }
        </style>
        """
        + macro_trends_html(rows),
        unsafe_allow_html=True,
    )
    st.caption(
        "Daily and weekly trend only. "
        "Daily is Up when the latest close is higher than each of the previous three daily closes, and Down when it is lower than each of them. Otherwise it is Flat. "
        "Weekly is this week's close against the previous week's close."
    )


def rsi_text(snapshot: dict) -> str:
    value = rsi_14(snapshot)
    if value is None:
        return "Not enough closes"
    return f"{value:.1f}"


def average_text(snapshot: dict) -> str:
    position = average_position(snapshot)
    if position is None:
        return "Not enough closes"
    return position


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
                "daily_trend": daily_trend(snapshot),
                "weekly_trend": weekly_trend(snapshot),
                "rsi": rsi_text(snapshot),
                "average": average_text(snapshot),
                "target": snapshot.get("target") if isinstance(snapshot.get("target"), (int, float)) else None,
                "upside": gap,
                "eps": snapshot.get("eps") if isinstance(snapshot.get("eps"), (int, float)) else None,
                "forward_pe": snapshot.get("forwardPE") if isinstance(snapshot.get("forwardPE"), (int, float)) else None,
                "thesis": None if thesis is None else thesis["title"],
                "squeeze_met": met,
                "squeeze_unknown": unknown,
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
                "Daily trend": trend_text(row["daily_trend"]),
                "Daily RSI (14)": row["rsi"],
                "Daily 200-day average": row["average"],
                "Weekly trend": trend_text(row["weekly_trend"]),
                "Weekly RSI (14)": row["rsi"],
                "Weekly 200-day average": row["average"],
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


def _watchlist(snapshots: list[dict]) -> tuple[list[dict], dict[str, dict]]:
    rows = watchlist_rows(snapshots)
    by_ticker = {str(snapshot.get("ticker")): snapshot for snapshot in snapshots}
    return rows, by_ticker


def _requested_ticker() -> str | None:
    value = st.query_params.get("ticker")
    if isinstance(value, list):
        value = value[0] if value else None
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().upper()


def _plain_cell(value: object) -> str:
    return html.escape(str(value).replace("\n", " "))


def watchlist_html(rows: list[dict]) -> str:
    """HTML table whose ticker and company are links to that stock."""
    frame = display_watchlist(rows)
    headers = "".join(f"<th>{html.escape(name)}</th>" for name in frame.columns)
    body: list[str] = []
    for record in frame.to_dict("records"):
        ticker = html.escape(str(record["Ticker"]), quote=True)
        href = f"?ticker={ticker}"
        cells = []
        for header, value in record.items():
            text = _plain_cell(value)
            if header in {"Ticker", "Company"}:
                cells.append(f'<td><a href="{href}" target="_self">{text}</a></td>')
            else:
                cells.append(f"<td>{text}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (
        "<table class=\"desk-watchlist\"><thead><tr>"
        + headers
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
    )


def render_research_desk() -> None:
    st.title("Research Desk")
    st.caption(
        "USAR, IBRX, ALMU, NVO, UUUU and SMR start from the seeded snapshots in research-desk/lib/bootstrap.json. "
        "Add a ticker to fetch a quote from Yahoo Finance and valuation fields from Stock Analysis. "
        "A figure stays blank when that source does not publish it. "
        "Names you add, and prices you refresh, stay on this running app until it restarts. "
        "They are not written back to the repo. "
        "Thesis text is the ticker playbook in research-desk/lib/research.ts."
    )

    _hydrate_quotes()

    with st.form("add_ticker", clear_on_submit=True):
        entered = st.text_input("Add a ticker", placeholder="AAPL")
        add = st.form_submit_button("Add to watchlist")
    if add:
        _add_ticker(entered)

    snapshots = _current_snapshots()
    if not snapshots:
        st.warning("No seeded snapshots were found in research-desk/lib/bootstrap.json.")
        return

    _, refresh_col = st.columns([4, 1])
    with refresh_col:
        refresh = st.button("Refresh prices", width="stretch")
    if refresh:
        _refresh_prices()
        snapshots = _current_snapshots()
    for message in st.session_state.get("desk_refresh_errors") or []:
        st.error(message)

    rows, by_ticker = _watchlist(snapshots)
    st.markdown(
        """
        <style>
        table.desk-watchlist { width: 100%; border-collapse: collapse; font-size: 0.92rem; }
        table.desk-watchlist th, table.desk-watchlist td {
          text-align: left; padding: 0.45rem 0.4rem;
          border-bottom: 1px solid rgba(128,128,128,0.28); vertical-align: top;
        }
        table.desk-watchlist a { font-weight: 650; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(watchlist_html(rows), unsafe_allow_html=True)
    st.caption(
        "Click a ticker or company in the table to open it. "
        "Daily trend is Up when the latest close is higher than each of the previous three daily closes, and Down when it is lower than each of them. Otherwise it is Flat. "
        "Weekly trend compares this week's close with the previous week's close: Up when it is higher, Down when it is lower, and Flat when they are equal. "
        "RSI (14) and the 200-day moving average are daily readings, shown on the daily view and the weekly view. "
        "The 200-day average needs 200 stored daily closes. "
        "Upside is the average analyst target divided by the price, minus one. "
        "The squeeze column counts how many of the five repo heuristics are met. Unknown inputs stay unknown and are not treated as zero."
    )

    ticker = _requested_ticker()
    snapshot = by_ticker.get(str(ticker)) if ticker else None
    if ticker and snapshot is None:
        st.warning(f"{ticker} is not on the watchlist.")
        return
    if snapshot is None:
        st.info("Click a stock in the table to open its thesis and short-squeeze checks.")
        return
    _render_detail(snapshot)


def _remember_quotes() -> None:
    try:
        save_quote_cache(
            {
                "refreshed": st.session_state.desk_refreshed,
                "added": st.session_state.desk_added,
                "refresh_at": st.session_state.get("desk_refresh_at"),
                "errors": st.session_state.get("desk_refresh_errors") or [],
            }
        )
    except OSError:
        st.warning("The new prices are showing, but they could not be saved for the next page load.")


def _hydrate_quotes() -> None:
    if st.session_state.get("desk_hydrated"):
        return
    cached = load_quote_cache()
    st.session_state.desk_refreshed = cached.get("refreshed") or {}
    st.session_state.desk_added = cached.get("added") or {}
    st.session_state.desk_refresh_at = cached.get("refresh_at")
    st.session_state.desk_refresh_errors = cached.get("errors") or []
    st.session_state.desk_hydrated = True


def _current_snapshots() -> list[dict]:
    overrides = st.session_state.get("desk_refreshed") or {}
    combined = [*load_snapshots(), *st.session_state.desk_added.values()]
    current: list[dict] = []
    for snapshot in combined:
        ticker = str(snapshot.get("ticker") or "")
        current.append(overrides.get(ticker, snapshot))
    return current


def _refresh_prices() -> None:
    current = _current_snapshots()
    refreshed = dict(st.session_state.desk_refreshed)
    errors: list[str] = []
    updated = 0
    with st.spinner("Refreshing prices from Yahoo Finance…"):
        for snapshot in current:
            ticker = str(snapshot.get("ticker") or "")
            try:
                refreshed[ticker] = refresh_quote(snapshot)
            except QuoteError as exc:
                errors.append(str(exc))
                continue
            updated += 1
            if ticker in st.session_state.desk_added:
                st.session_state.desk_added[ticker] = refreshed[ticker]
    st.session_state.desk_refreshed = refreshed
    st.session_state.desk_refresh_errors = errors
    if updated:
        st.session_state.desk_refresh_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        st.success(f"Updated {updated} price{'s' if updated != 1 else ''}.")
    elif not errors:
        st.warning("There are no stocks to refresh.")
    _remember_quotes()


def _add_ticker(raw: str) -> None:
    try:
        ticker = normalize_ticker(raw)
    except QuoteError as exc:
        st.error(str(exc))
        return
    existing = {str(row.get("ticker")) for row in load_snapshots()} | set(st.session_state.desk_added)
    if ticker in existing:
        st.error(f"{ticker} is already on the watchlist.")
        return
    if len(existing) >= 100:
        st.error("The watchlist already has 100 names.")
        return
    with st.spinner(f"Fetching {ticker}…"):
        try:
            snapshot = fetch_new_snapshot(ticker)
        except QuoteError as exc:
            st.error(str(exc))
            return
    st.session_state.desk_added[ticker] = snapshot
    _remember_quotes()
    st.query_params["ticker"] = ticker
    st.success(f"Added {ticker}. Blank fields were not published by the source.")


def _view_lines(snapshot: dict, trend: str | None) -> None:
    st.write(f"Trend: {trend_text(trend)}.")
    st.write(f"RSI (14): {rsi_text(snapshot)}.")
    st.write(f"200-day moving average: {average_text(snapshot)}.")


def _render_closes(snapshot: dict) -> None:
    window = st.radio(
        "Daily closes",
        options=list(CLOSE_WINDOWS),
        index=CLOSE_WINDOWS.index(DEFAULT_CLOSE_WINDOW),
        format_func=lambda days: f"{days} days",
        horizontal=True,
        key="desk_close_window",
    )
    closes, close_dates = close_window(snapshot, int(window))
    if not closes:
        st.caption("No daily closes are stored for this stock.")
        return
    chart = pd.DataFrame({"Close": closes})
    if close_dates is not None:
        chart.index = close_dates
        st.line_chart(chart, height=180)
        st.caption(f"Closes from the last {int(window)} days. This is not a forecast.")
        return
    st.line_chart(chart, height=180)
    st.caption("Close dates are not stored, so the 30, 60 and 90 day choices cannot be applied.")


def _render_detail(snapshot: dict) -> None:
    ticker = str(snapshot.get("ticker"))
    st.subheader(f"{ticker} · {snapshot.get('name') or 'Name not in snapshot'}")

    gap = upside(snapshot)
    large_gap = gap is not None and gap >= 50
    checks = squeeze_checks(snapshot)
    met = sum(1 for check in checks if check["passed"])
    unknown = sum(1 for check in checks if not check["known"])

    metrics = st.columns(6)
    metrics[0].metric("Price", _money(snapshot.get("price")) or "—")
    target_help = None
    analyst_count = snapshot.get("analystCount")
    if isinstance(analyst_count, (int, float)) and not isinstance(analyst_count, bool):
        shown_count = int(analyst_count) if float(analyst_count).is_integer() else analyst_count
        consensus = snapshot.get("consensus")
        target_help = f"{shown_count} analysts"
        if isinstance(consensus, str) and consensus:
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

    st.markdown("**Daily**")
    _view_lines(snapshot, daily_trend(snapshot))
    _render_closes(snapshot)

    st.markdown("**Weekly**")
    _view_lines(snapshot, weekly_trend(snapshot))

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
