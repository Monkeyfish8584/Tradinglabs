"""Research Desk page for the Streamlit app.

Seeded market figures come from ``research-desk/lib/bootstrap.json``. A name
added on the page is fetched from Yahoo Finance and Stock Analysis, and any
field those pages do not publish stays blank. Thesis paragraphs are the ticker
playbooks already written in ``research-desk/lib/research.ts``.

Watchlist search, filter, sort and CSV export, generic stock logos, and
auto-refresh on a stale load follow the React desk (PR #55). Concurrent
refresh and up to five headlines per stock follow PR #56. Company-name
search, insider trades, five-year closes, multi-timeframe macro trends with
news, near-high/low breadth, and the Technical/Sentiment/Fundamental spider
follow PR #57 (research-desk/lib/macro.ts). The spider's Fundamental axis is
adapted for Streamlit: there is no CANSLIM data here, so it uses the share
of stocks with forward P/E below 20 and the share with EPS (TTM) above zero.
Politician/congressional trades are not available: there is no free
structured feed, and disclosures are typically value ranges with no exact
entry price. The BofA Bull & Bear score is proprietary and is not available
in this desk; the breadth + trend read is the desk's own equivalent.
"""

from __future__ import annotations

import csv
import html
import io
import json
import math
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

from research_desk_quotes import (
    QuoteError,
    fetch_candles,
    fetch_new_snapshot,
    fetch_news_rss,
    fetch_text,
    fetch_trend_snapshot,
    normalize_ticker,
    refresh_quote,
    search_symbols,
    table_rows,
    yahoo_chart_url,
)

# Display name, then the Yahoo symbol. GER30 is the DAX index Yahoo publishes as ^GDAXI.
# The original seven markets stay first; the FX pairs follow (PR #57).
MACRO_MARKETS: tuple[tuple[str, str], ...] = (
    ("BTCUSD", "BTC-USD"),
    ("US500", "^GSPC"),
    ("US100", "^NDX"),
    ("US30", "^DJI"),
    ("ETHUSD", "ETH-USD"),
    ("UK100", "^FTSE"),
    ("GER30", "^GDAXI"),
    ("EUR/USD", "EURUSD=X"),
    ("GBP/JPY", "GBPJPY=X"),
    ("USD/JPY", "USDJPY=X"),
)

CLOSE_WINDOWS = (90, 365, 1825)
DEFAULT_CLOSE_WINDOW = 365
# Index constituents published on Wikipedia. GER30 uses the current DAX membership.
BREADTH_SOURCES: dict[str, dict[str, str]] = {
    "US500": {"url": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "venue": "us500"},
    "US100": {"url": "https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies", "venue": "us100"},
    "US30": {"url": "https://en.wikipedia.org/wiki/List_of_Dow_Jones_Industrial_Average_companies", "venue": "us30"},
    "UK100": {"url": "https://en.wikipedia.org/wiki/FTSE_100_Index", "venue": "uk100"},
    "GER30": {"url": "https://en.wikipedia.org/wiki/DAX", "venue": "ger30"},
}
_NO_BREADTH = {"BTCUSD", "ETHUSD"}

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
    theses = payload.get("theses")
    return {
        "refreshed": refreshed if isinstance(refreshed, dict) else {},
        "added": added if isinstance(added, dict) else {},
        "refresh_at": payload.get("refresh_at") if isinstance(payload.get("refresh_at"), str) else None,
        "errors": [str(item) for item in errors] if isinstance(errors, list) else [],
        "theses": {str(key): str(value) for key, value in theses.items()} if isinstance(theses, dict) else {},
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


def _parse_fetched_at(value: object) -> datetime | None:
    """An ISO timestamp from a snapshot, or None when it is missing or unreadable."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _snapshot_fetched_at(snapshot: dict) -> datetime | None:
    """When a snapshot was last fetched: quoteFetchedAt, then attemptedAt."""
    for key in ("quoteFetchedAt", "attemptedAt"):
        fetched = _parse_fetched_at(snapshot.get(key))
        if fetched is not None:
            return fetched
    return None


def _is_fresh(snapshot: dict, minutes: int = 5) -> bool:
    """True when a snapshot was fetched within the last ``minutes`` minutes."""
    fetched = _snapshot_fetched_at(snapshot)
    if fetched is None:
        return False
    return datetime.now(timezone.utc) - fetched < timedelta(minutes=minutes)


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


def sma(values: list[float], period: int) -> float | None:
    """Simple moving average of the last ``period`` values, or None when too few."""
    if period <= 0 or len(values) < period:
        return None
    return sum(values[-period:]) / period


def aggregate_4h(candles: list[dict]) -> list[dict]:
    """Group consecutive hourly candles into 4-hour candles (PR #57, macro.ts)."""
    grouped: list[dict] = []
    for start in range(0, len(candles) - 3, 4):
        group = candles[start : start + 4]
        highs = [c.get("high") for c in group if isinstance(c.get("high"), (int, float)) and not isinstance(c.get("high"), bool)]
        lows = [c.get("low") for c in group if isinstance(c.get("low"), (int, float)) and not isinstance(c.get("low"), bool)]
        volumes = [c.get("volume") for c in group if isinstance(c.get("volume"), (int, float)) and not isinstance(c.get("volume"), bool)]
        grouped.append(
            {
                "date": group[-1].get("date"),
                "open": group[0].get("open"),
                "high": max(highs) if highs else None,
                "low": min(lows) if lows else None,
                "close": group[-1].get("close"),
                "volume": sum(volumes) if volumes else None,
            }
        )
    return grouped


def macro_trend_for(candles: list[dict]) -> dict:
    """Multi-timeframe trend for one set of candles (PR #57, macro.ts ``trendFor``).

    Bullish = close up on the period AND above its 20-period average;
    Bearish = close down AND below it; otherwise Mixed. Fewer than 21
    candles is Unavailable.
    """
    closes = [
        float(c["close"])
        for c in candles
        if isinstance(c.get("close"), (int, float)) and not isinstance(c.get("close"), bool) and math.isfinite(float(c["close"]))
    ]
    if len(closes) < 21:
        return {"label": "Unavailable", "changePct": None, "aboveSma20": None, "note": "Fewer than 21 completed candles."}
    latest, previous = closes[-1], closes[-2]
    average = sma(closes, 20)
    if average is None:
        return {"label": "Unavailable", "changePct": None, "aboveSma20": None, "note": "No 20-period average."}
    above = latest > average
    change_pct = (latest / previous - 1) * 100 if previous > 0 else None
    if latest > previous and above:
        label = "Bullish"
    elif latest < previous and not above:
        label = "Bearish"
    else:
        label = "Mixed"
    note = {
        "Bullish": "Close up on the period and above its 20-period average.",
        "Bearish": "Close down on the period and below its 20-period average.",
        "Mixed": "Close and 20-period average disagree.",
    }[label]
    return {"label": label, "changePct": change_pct, "aboveSma20": above, "note": note}


def _return_over_days(snapshot: dict, days: int) -> float | None:
    """Date-anchored return over ``days``: latest close vs the close on or before that date."""
    pairs = _close_pairs(snapshot)
    if not pairs or any(day is None for day, _ in pairs):
        return None
    latest_day, latest_close = pairs[-1]
    if latest_day is None or latest_close == 0:
        return None
    target_day = latest_day - timedelta(days=days)
    earlier = [close for day, close in pairs if day is not None and day <= target_day]
    if not earlier or earlier[-1] == 0:
        return None
    return (latest_close / earlier[-1] - 1) * 100


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
    """Daily and weekly trend for the macro markets, plus a 4-hour trend and news. A failed feed stays blank."""
    rows: list[dict] = []
    for label, symbol in MACRO_MARKETS:
        try:
            snapshot = fetch_trend_snapshot(symbol, getter, span="6mo")
        except QuoteError:
            rows.append({"label": label, "daily": None, "weekly": None, "four_hour": {"label": "Unavailable", "changePct": None, "aboveSma20": None, "note": "Macro data unavailable."}, "news": [], "available": False})
            continue
        try:
            hourly = fetch_candles(symbol, interval="60m", span="1mo", getter=getter)
            four_hour = macro_trend_for(aggregate_4h(hourly))
        except Exception:
            four_hour = {"label": "Unavailable", "changePct": None, "aboveSma20": None, "note": "4-hour candles unavailable."}
        try:
            news = fetch_news_rss(f"{label} market news", getter=getter) or []
        except Exception:
            news = []
        rows.append(
            {
                "label": label,
                "daily": daily_trend(snapshot),
                "weekly": weekly_trend(snapshot),
                "four_hour": four_hour,
                "news": news,
                "available": True,
            }
        )
    return rows


def _trend_class(value: object) -> str:
    if value in {"Up", "Bullish"}:
        return "macro-up"
    if value in {"Down", "Bearish"}:
        return "macro-down"
    if value in {"Flat", "Mixed"}:
        return "macro-flat"
    return "macro-missing"


def _macro_trend_label(value: object) -> str:
    """A trend label whether it is a plain Up/Down/Flat string or a macro_trend_for dict."""
    if isinstance(value, dict):
        label = value.get("label")
        return str(label) if isinstance(label, str) and label else "Unavailable"
    if value in {"Up", "Down", "Flat", "Bullish", "Bearish", "Mixed"}:
        return str(value)
    return "Unavailable"


def macro_trends_html(rows: list[dict], selected: str | None = None) -> str:
    cards: list[str] = []
    for row in rows:
        label = str(row.get("label") or "")
        daily = trend_text(row.get("daily")) if row.get("available") else "Unavailable"
        weekly = trend_text(row.get("weekly")) if row.get("available") else "Unavailable"
        four_hour = _macro_trend_label(row.get("four_hour")) if row.get("available") else "Unavailable"
        name = html.escape(label)
        if label in BREADTH_SOURCES:
            href = html.escape(f"?breadth={label}", quote=True)
            name = f'<a href="{href}" target="_self">{name}</a>'
        selected_class = " macro-selected" if label == selected else ""
        news = row.get("news") if isinstance(row.get("news"), list) else []
        if news:
            news_html = "<div class=\"macro-news\">" + "".join(
                f"<div><a href=\"{html.escape(str(item.get('url') or ''), quote=True)}\" target=\"_blank\" rel=\"noopener\">{html.escape(str(item.get('title') or ''))}</a></div>"
                for item in news[:5]
                if isinstance(item, dict) and item.get("title") and item.get("url")
            ) + "</div>"
        else:
            news_html = "<div class=\"macro-news\">News unavailable</div>"
        cards.append(
            f"<div class=\"macro-card{selected_class}\">"
            f"<div class=\"macro-name\">{name}</div>"
            f"<div>Daily <span class=\"{_trend_class(row.get('daily') if row.get('available') else None)}\">{html.escape(daily)}</span></div>"
            f"<div>Weekly <span class=\"{_trend_class(row.get('weekly') if row.get('available') else None)}\">{html.escape(weekly)}</span></div>"
            f"<div>4-hour <span class=\"{_trend_class(four_hour if row.get('available') else None)}\">{html.escape(four_hour)}</span></div>"
            f"{news_html}"
            "</div>"
        )
    return "<div class=\"macro-strip\">" + "".join(cards) + "</div>"


def _ticker_cell(text: str, pattern: str) -> str | None:
    cleaned = text.strip().upper()
    if re.fullmatch(pattern, cleaned):
        return cleaned
    return None


def constituent_symbols(html_body: str, label: str) -> list[str]:
    """Yahoo symbols for one index. An unreadable table returns an empty list."""
    rows = table_rows(html_body)
    found: list[str] = []
    if label == "US500":
        start = next((i for i, row in enumerate(rows) if row and row[0]["text"].strip() == "Symbol"), None)
        column, pattern, venue = 0, r"[A-Z]{1,5}(?:\.[A-Z])?", "us"
    elif label == "US100":
        start = next((i for i, row in enumerate(rows) if row and row[0]["text"].strip() == "Ticker"), None)
        column, pattern, venue = 0, r"[A-Z]{1,5}(?:\.[A-Z])?", "us"
    elif label == "US30":
        start = next((i for i, row in enumerate(rows) if len(row) > 2 and row[2]["text"].strip() == "Symbol"), None)
        column, pattern, venue = 2, r"[A-Z]{1,5}(?:\.[A-Z])?", "us"
    elif label == "UK100":
        start = next((i for i, row in enumerate(rows) if len(row) > 1 and row[0]["text"].strip() == "Company" and row[1]["text"].strip().startswith("Ticker")), None)
        column, pattern, venue = 1, r"[A-Z0-9]{2,6}(?:\.[A-Z])?", "uk"
    elif label == "GER30":
        start = next((i for i, row in enumerate(rows) if row and row[0]["text"].strip() == "Ticker"), None)
        column, pattern, venue = 0, r"[A-Z0-9]{1,6}\.[A-Z]{1,3}", "de"
    else:
        return []
    if start is None:
        return []
    for row in rows[start + 1 :]:
        if len(row) <= column:
            break
        symbol = _ticker_cell(row[column]["text"], pattern)
        if symbol is None:
            break
        if venue == "us":
            symbol = symbol.replace(".", "-")
        elif venue == "uk":
            symbol = f"{symbol.replace('.', '-')}.L"
        found.append(symbol)
    unique: list[str] = []
    seen: set[str] = set()
    for symbol in found:
        if symbol not in seen:
            seen.add(symbol)
            unique.append(symbol)
    return unique


def parse_session_extremes(body: str) -> dict | None:
    """Latest session high and low, plus the 52-week high and low, from a Yahoo chart."""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        return None
    meta = result[0].get("meta") or {}

    def number(key: str) -> float | None:
        value = meta.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    extremes = {
        "day_high": number("regularMarketDayHigh"),
        "day_low": number("regularMarketDayLow"),
        "high_52": number("fiftyTwoWeekHigh"),
        "low_52": number("fiftyTwoWeekLow"),
    }
    if any(value is None for value in extremes.values()):
        return None
    return extremes


def _at_high(day_high: float, high_52: float) -> bool:
    """Near a 52-week high: the day high is within 1% of the 52-week high."""
    return high_52 > 0 and day_high >= high_52 * 0.99


def _at_low(day_low: float, low_52: float) -> bool:
    """Near a 52-week low: the day low is within 1% of the 52-week low."""
    return low_52 > 0 and day_low <= low_52 * 1.01


def breadth_summary(label: str, symbols: list[str], extremes: list[dict | None]) -> dict:
    """Percent of constituents at a 52-week high or low. Missing quotes stay out of both shares."""
    highs = lows = measured = unknown = 0
    for item in extremes:
        if not item:
            unknown += 1
            continue
        measured += 1
        if _at_high(item["day_high"], item["high_52"]):
            highs += 1
        if _at_low(item["day_low"], item["low_52"]):
            lows += 1
    attempted = measured + unknown
    ready = bool(symbols) and measured > 0 and measured * 2 >= attempted
    high_pct = None if not ready else highs / measured * 100
    low_pct = None if not ready else lows / measured * 100
    return {
        "label": label,
        "listed": len(symbols),
        "measured": measured,
        "unknown": unknown,
        "highs": highs,
        "lows": lows,
        "high_pct": high_pct,
        "low_pct": low_pct,
        "ready": ready,
    }


def load_breadth(label: str, getter=None) -> dict:
    """Constituent 52-week highs and lows for one index. Crypto has no constituent list."""
    if label in _NO_BREADTH:
        return {"label": label, "applies": False, "ready": False}
    source = BREADTH_SOURCES.get(label)
    if source is None:
        return {"label": label, "applies": False, "ready": False}
    get = getter or fetch_text
    try:
        page = get(source["url"])
    except Exception:
        return {"label": label, "applies": True, "ready": False, "listed": 0}
    symbols = constituent_symbols(page, label)

    def one(symbol: str) -> dict | None:
        try:
            body = get(yahoo_chart_url(symbol, "5d"))
        except Exception:
            return None
        return parse_session_extremes(body)

    if getter is None and len(symbols) > 1:
        with ThreadPoolExecutor(max_workers=8) as pool:
            extremes = list(pool.map(one, symbols))
    else:
        extremes = [one(symbol) for symbol in symbols]
    summary = breadth_summary(label, symbols, extremes)
    summary["applies"] = True
    return summary


def breadth_text(summary: dict) -> str:
    label = summary.get("label") or "This index"
    if summary.get("applies") is False:
        return f"Underlying highs and lows do not apply to {label}."
    if not summary.get("ready"):
        return f"{label} did not publish enough constituent quotes to calculate a near-high or near-low percentage."
    unknown = int(summary.get("unknown") or 0)
    text = (
        f"{summary['high_pct']:.1f}% of {summary['measured']} constituents were near a 52-week high in the latest session "
        f"({summary['highs']} names). "
        f"{summary['low_pct']:.1f}% were near a 52-week low ({summary['lows']} names). "
        f"Coverage: {summary['measured']} of {summary.get('listed', summary['measured'])} listed constituents measured."
    )
    if unknown:
        text += f" {unknown} constituents had no published session range, so they are left out of both percentages."
    return text


def _bullish_share(instruments: list[dict], key: str) -> float | None:
    """Share of instruments that are Bullish on one timeframe.

    Accepts the Streamlit macro rows (daily/weekly as Up/Down/Flat strings,
    four_hour as a macro_trend_for dict) and the React shape (dicts with a
    ``label`` of Bullish/Bearish/Mixed).
    """
    values = [row.get(key) for row in instruments if row.get(key) is not None]
    if not values:
        return None
    bullish = 0
    for value in values:
        if isinstance(value, dict):
            bullish += 1 if value.get("label") == "Bullish" else 0
        elif value in {"Up", "Bullish"}:
            bullish += 1
    return bullish / len(values)


def compute_macro_spider(instruments: list[dict], breadth: list[dict], snapshots: list[dict]) -> dict:
    """Technical/Sentiment/Fundamental spider, 0-10 each (PR #57, macro.ts ``computeMacroSpider``).

    Technical (10): daily Bullish share x4 + weekly x3 + 4-hour x1 + breadth
    net x2; capped at 6 if net breadth is negative while indices rise.
    Sentiment (10): breadth crowdedness x5 + daily Bullish share x3 + weekly
    x2, read backwards -- high = crowded = caution, proxy only.
    Fundamental (10): ADAPTED for Streamlit, because there is no CANSLIM
    data here: share of stocks with forward P/E below 20 x5 + share with
    EPS (TTM) above zero x5, averaged across the stocks on the desk.
    An axis with no usable inputs is None (Unavailable), never 0.
    """
    clamp = lambda n: max(0, min(10, round(n)))
    daily = _bullish_share(instruments, "daily")
    weekly = _bullish_share(instruments, "weekly")
    four_hour = _bullish_share(instruments, "four_hour")
    if four_hour is None:
        four_hour = _bullish_share(instruments, "fourHour")
    usable_breadth = [
        item
        for item in breadth
        if isinstance(item, dict) and not item.get("error") and (item.get("measured") or item.get("total"))
    ]
    nets = [
        (item["highs"] - item["lows"]) / (item.get("measured") or item["total"])
        for item in usable_breadth
        if isinstance(item.get("highs"), (int, float)) and isinstance(item.get("lows"), (int, float))
    ]
    net = sum(nets) / len(nets) if nets else None
    near_highs = [
        item["highs"] / (item.get("measured") or item["total"])
        for item in usable_breadth
        if isinstance(item.get("highs"), (int, float))
    ]
    crowded = sum(near_highs) / len(near_highs) if near_highs else None
    technical: int | None = None
    if daily is not None or weekly is not None or four_hour is not None or net is not None:
        breadth_part = 0 if net is None else max(0.0, min(1.0, (net + 0.2) / 0.4)) * 2
        technical = clamp((daily or 0) * 4 + (weekly or 0) * 3 + (four_hour or 0) * 1 + breadth_part)
        if net is not None and net < 0 and (daily or 0) > 0.5 and technical > 6:
            technical = 6
    sentiment: int | None = None
    if crowded is not None or daily is not None or weekly is not None:
        sentiment = clamp((0 if crowded is None else min(1.0, crowded / 0.3) * 5) + (daily or 0) * 3 + (weekly or 0) * 2)
    fundamental: int | None = None
    if snapshots:
        with_pe = [s for s in snapshots if isinstance(s.get("forwardPE"), (int, float)) and not isinstance(s.get("forwardPE"), bool)]
        with_eps = [s for s in snapshots if isinstance(s.get("eps"), (int, float)) and not isinstance(s.get("eps"), bool)]
        if with_pe or with_eps:
            value_part = (sum(1 for s in with_pe if float(s["forwardPE"]) < 20) / len(with_pe) * 5) if with_pe else 0
            eps_part = (sum(1 for s in with_eps if float(s["eps"]) > 0) / len(with_eps) * 5) if with_eps else 0
            fundamental = clamp(value_part + eps_part)
    axes = [
        {"axis": "Technical", "score": technical, "note": "Daily trend x4, weekly x3, 4-hour x1, breadth x2; capped at 6 if breadth is negative while indices rise."},
        {"axis": "Sentiment", "score": sentiment, "note": "Read backwards -- high = crowded = caution. Breadth crowdedness x5, daily x3, weekly x2. Proxy only: no put/call ratio or live BofA reading in this desk."},
        {"axis": "Fundamental", "score": fundamental, "note": "Adapted for Streamlit (no CANSLIM here): share of desk stocks with forward P/E <20 x5 + share with EPS (TTM) >0 x5."},
    ]
    technical_score, sentiment_score, fundamental_score = technical, sentiment, fundamental
    verdict = "Mixed — check the axes below."
    verdict_note = "No single shape dominates. Read the lowest axis first: that is where the setup is weakest."
    if technical_score is not None and sentiment_score is not None and fundamental_score is not None:
        if sentiment_score >= 8 and fundamental_score >= 6 and technical_score >= 6:
            verdict = "Crowded, not broken"
            verdict_note = "Sentiment is high but fundamentals are decent and the trend is up. Everyone already likes it — expect sharp dips on any disappointment — but the underlying story looks intact. Picky entries, sensible size."
        elif technical_score < 4 and fundamental_score >= 6:
            verdict = "Watchlist, not a short"
            verdict_note = "Technically weak but fundamentally strong. Wait for the trend to turn rather than shorting a good story."
        elif technical_score >= 7 and sentiment_score >= 7 and fundamental_score < 4:
            verdict = "Momentum-bubble shape"
            verdict_note = "Trend and crowd are hot, fundamentals are weak. Momentum can run, but there is little underneath it."
        elif technical_score < 4 and sentiment_score < 4 and fundamental_score < 4:
            verdict = "No reason to be here yet"
            verdict_note = "All three axes are low. Nothing in the setup earns attention right now."
        elif 5 <= technical_score <= 7 and 5 <= sentiment_score <= 7 and 5 <= fundamental_score <= 7:
            verdict = "Healthy, well-rounded setup"
            verdict_note = "A balanced triangle: trend, crowd and fundamentals are all in the middle of the range."
    return {"axes": axes, "verdict": verdict, "verdict_note": verdict_note}


def _spider_svg(axes: list[dict]) -> str:
    """Hand-rolled SVG triangle for the macro spider (same pattern as the React macro panel)."""
    centre_x, centre_y, radius = 150.0, 140.0, 110.0
    vertices = {
        "Technical": (centre_x, centre_y - radius),
        "Sentiment": (centre_x - radius * 0.95, centre_y + radius * 0.75),
        "Fundamental": (centre_x + radius * 0.95, centre_y + radius * 0.75),
    }
    labels = {
        "Technical": (centre_x, centre_y - radius - 12),
        "Sentiment": (centre_x - radius * 0.95 - 8, centre_y + radius * 0.75 + 18),
        "Fundamental": (centre_x + radius * 0.95 + 8, centre_y + radius * 0.75 + 18),
    }
    scores = {item["axis"]: item.get("score") for item in axes if isinstance(item, dict)}

    def point(axis: str, scale: float) -> tuple[float, float]:
        vx, vy = vertices[axis]
        return (centre_x + (vx - centre_x) * scale, centre_y + (vy - centre_y) * scale)

    def polygon(scale: float) -> str:
        return " ".join(f"{x:.1f},{y:.1f}" for x, y in (point(axis, scale) for axis in ("Technical", "Sentiment", "Fundamental")))

    scored_points = []
    for axis in ("Technical", "Sentiment", "Fundamental"):
        score = scores.get(axis)
        scored_points.append(point(axis, (score / 10) if isinstance(score, (int, float)) else 0))
    scored = " ".join(f"{x:.1f},{y:.1f}" for x, y in scored_points)
    parts = [
        '<svg width="300" height="260" viewBox="0 0 300 260" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Macro spider diagram">',
        f'<polygon points="{polygon(1.0)}" fill="none" stroke="#888888" stroke-opacity="0.5" />',
        f'<polygon points="{polygon(0.5)}" fill="none" stroke="#888888" stroke-opacity="0.35" />',
    ]
    for axis in ("Technical", "Sentiment", "Fundamental"):
        vx, vy = vertices[axis]
        parts.append(f'<line x1="{centre_x}" y1="{centre_y}" x2="{vx}" y2="{vy}" stroke="#888888" stroke-opacity="0.35" />')
    parts.append(f'<polygon points="{scored}" fill="rgba(27,127,74,0.25)" stroke="#1b7f4a" stroke-width="2" />')
    for axis in ("Technical", "Sentiment", "Fundamental"):
        x, y = scored_points[("Technical", "Sentiment", "Fundamental").index(axis)]
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#1b7f4a" />')
        lx, ly = labels[axis]
        anchor = "middle" if axis == "Technical" else ("end" if axis == "Sentiment" else "start")
        score = scores.get(axis)
        shown = f"{score}/10" if isinstance(score, (int, float)) else "Unavailable"
        parts.append(f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" font-size="12" font-weight="700" fill="currentColor">{axis} {shown}</text>')
    parts.append("</svg>")
    return "".join(parts)


@st.cache_data(ttl=900, show_spinner=False)
def cached_macro_rows() -> list[dict]:
    return load_macro_rows()


def _requested_breadth() -> str | None:
    value = st.query_params.get("breadth")
    if isinstance(value, list):
        value = value[0] if value else None
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().upper()


@st.cache_data(ttl=1800, show_spinner=False)
def cached_breadth(label: str) -> dict:
    return load_breadth(label)


def render_macro_trends() -> None:
    """Daily and weekly trend for the macro markets, shown above either page."""
    st.markdown("**Macro trends**")
    with st.spinner("Loading macro trends…"):
        try:
            rows = cached_macro_rows()
        except Exception:
            st.caption("Macro trends could not be loaded.")
            return
    selected = _requested_breadth()
    st.markdown(
        """
        <style>
        .macro-strip { display: flex; gap: 0.55rem; flex-wrap: wrap; }
        .macro-card {
          flex: 1 1 7.5rem; border: 1px solid rgba(128,128,128,0.35);
          border-radius: 8px; padding: 0.4rem 0.6rem; line-height: 1.35;
        }
        .macro-selected { outline: 2px solid rgba(27,127,74,0.85); }
        .macro-name { font-weight: 700; }
        .macro-name a { color: inherit; }
        .macro-up { color: #1b7f4a; font-weight: 700; }
        .macro-down { color: #b42318; font-weight: 700; }
        .macro-flat, .macro-missing { font-weight: 700; }
        </style>
        """
        + macro_trends_html(rows, selected),
        unsafe_allow_html=True,
    )
    st.caption(
        "Daily, weekly and 4-hour trend. "
        "Daily is Up when the latest close is higher than each of the previous three daily closes, and Down when it is lower than each of them. Otherwise it is Flat. "
        "Weekly is this week's close against the previous week's close. "
        "4-hour is the Bullish/Bearish/Mixed read from 4-hour candles: Bullish when the close is up on the period and above its 20-period average, Bearish when it is down and below it, otherwise Mixed. "
        "Click an index for the share of its constituents near a 52-week high or low. This does not apply to BTCUSD or ETHUSD. "
        "The BofA Bull & Bear score is proprietary and not available in this desk; the breadth + trend read is the desk's own equivalent."
    )
    if selected:
        _render_breadth(selected)
    _render_macro_spider(rows)


def _render_macro_spider(rows: list[dict]) -> None:
    """Technical/Sentiment/Fundamental spider for the macro view (PR #57)."""
    st.markdown("**Macro spider**")
    try:
        breadth = [cached_breadth(label) for label in BREADTH_SOURCES]
    except Exception:
        breadth = []
    try:
        snapshots = _current_snapshots()
    except Exception:
        snapshots = load_snapshots()
    spider = compute_macro_spider(rows, breadth, snapshots)
    st.markdown(_spider_svg(spider["axes"]), unsafe_allow_html=True)
    st.dataframe(
        pd.DataFrame(
            [
                {"Axis": item["axis"], "Score (0–10)": item["score"] if isinstance(item.get("score"), (int, float)) else "Unavailable", "Note": item["note"]}
                for item in spider["axes"]
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )
    st.markdown(f"**{spider['verdict']}**")
    st.write(spider["verdict_note"])
    st.caption(
        "Example: Technical 7, Sentiment 8, Fundamental 6 — Crowded, not broken (illustrative example, not live data). "
        "Sentiment is read backwards: a high score means crowded, which is caution, not a buy signal."
    )


def _render_breadth(label: str) -> None:
    if label in _NO_BREADTH:
        st.info(f"Underlying highs and lows do not apply to {label}.")
        return
    if label not in BREADTH_SOURCES:
        return
    with st.spinner(f"Checking {label} constituents…"):
        try:
            summary = cached_breadth(label)
        except Exception:
            st.warning(f"{label} constituent strength could not be loaded.")
            return
    st.markdown(f"**{label} underlying strength**")
    st.write(breadth_text(summary))
    if summary.get("ready"):
        st.caption(
            "A constituent counts as near a new high when its latest session high is within 1% of the 52-week high, "
            "and as near a new low when its latest session low is within 1% of the 52-week low."
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


def _snapshot_number(snapshot: dict, key: str) -> float | None:
    value = snapshot.get(key)
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _snapshot_text(snapshot: dict, key: str) -> str | None:
    value = snapshot.get(key)
    return value if isinstance(value, str) and value else None


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
                "currency": _snapshot_text(snapshot, "currency"),
                "quote_at": _snapshot_text(snapshot, "quoteAt") or _snapshot_text(snapshot, "quoteFetchedAt"),
                "short_float": _snapshot_number(snapshot, "shortFloatPct"),
                "shares_short": _snapshot_number(snapshot, "shortShares"),
                "short_date": _snapshot_text(snapshot, "shortDate"),
                "days_to_cover": _snapshot_number(snapshot, "daysToCover"),
                "borrow_fee": _snapshot_number(snapshot, "borrowFee"),
                "available": _snapshot_number(snapshot, "available"),
                "borrow_at": _snapshot_text(snapshot, "borrowAt"),
                "stage": _snapshot_text(snapshot, "stage"),
                "notes": "; ".join(_source_notes(snapshot)),
            }
        )
    rows.sort(key=lambda row: (row["upside"] is None, -(row["upside"] or 0), str(row["ticker"])))
    return rows


WATCHLIST_FILTERS: tuple[str, ...] = (
    "All stocks",
    "Large target gap ≥50%",
    "High short interest ≥20%",
)

WATCHLIST_SORTS: tuple[str, ...] = (
    "Target upside",
    "Ticker A–Z",
    "Short float",
    "Borrow fee",
)


def filter_watchlist_rows(rows: list[dict], query: str = "", filter_option: str = "All stocks", sort_option: str = "Target upside") -> list[dict]:
    """Search (ticker or company name), filter and sort a watchlist view (PR #55).

    The displayed table and the CSV export both use this filtered/sorted view.
    """
    text = (query or "").strip().lower()
    shown = list(rows)
    if text:
        shown = [row for row in shown if text in str(row.get("ticker") or "").lower() or text in str(row.get("name") or "").lower()]
    if filter_option == "Large target gap ≥50%":
        shown = [row for row in shown if row.get("upside") is not None and float(row["upside"]) >= 50]
    elif filter_option == "High short interest ≥20%":
        shown = [row for row in shown if row.get("short_float") is not None and float(row["short_float"]) >= 20]
    if sort_option == "Ticker A–Z":
        shown.sort(key=lambda row: str(row.get("ticker") or ""))
    elif sort_option == "Short float":
        shown.sort(key=lambda row: (row.get("short_float") is None, -(row.get("short_float") or 0), str(row.get("ticker"))))
    elif sort_option == "Borrow fee":
        shown.sort(key=lambda row: (row.get("borrow_fee") is None, -(row.get("borrow_fee") or 0), str(row.get("ticker"))))
    else:
        shown.sort(key=lambda row: (row.get("upside") is None, -(row.get("upside") or 0), str(row.get("ticker"))))
    return shown


WATCHLIST_CSV_COLUMNS: tuple[str, ...] = (
    "Ticker",
    "Company",
    "Currency",
    "Price",
    "Quote as of",
    "Average analyst target",
    "Target upside %",
    "EPS TTM",
    "Forward PE",
    "Short float %",
    "Shares short",
    "SI date",
    "Days to cover",
    "Borrow fee %",
    "Shares available",
    "Borrow as of",
    "Stage",
    "Notes",
    "Thesis",
)


def watchlist_csv(rows: list[dict], theses: dict | None = None) -> str:
    """The filtered/sorted watchlist view as CSV (PR #55). A saved user thesis wins over the playbook title."""
    saved = theses or {}
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(list(WATCHLIST_CSV_COLUMNS))

    def number(value: object) -> object:
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else ""

    for row in rows:
        ticker = str(row.get("ticker") or "")
        writer.writerow(
            [
                ticker,
                row.get("name") or "",
                row.get("currency") or "",
                number(row.get("price")),
                row.get("quote_at") or "",
                number(row.get("target")),
                number(row.get("upside")),
                number(row.get("eps")),
                number(row.get("forward_pe")),
                number(row.get("short_float")),
                number(row.get("shares_short")),
                row.get("short_date") or "",
                number(row.get("days_to_cover")),
                number(row.get("borrow_fee")),
                number(row.get("available")),
                row.get("borrow_at") or "",
                row.get("stage") or "",
                row.get("notes") or "",
                saved.get(ticker) or row.get("thesis") or "",
            ]
        )
    return buffer.getvalue()


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


_LOGO_PALETTE: tuple[str, ...] = (
    "#1b7f4a",
    "#2563eb",
    "#7c3aed",
    "#b45309",
    "#0e7490",
    "#be185d",
    "#4d7c0f",
    "#334155",
)


def _logo_color(ticker: str) -> str:
    """Deterministic monogram colour for a ticker, from a small palette."""
    return _LOGO_PALETTE[sum(ord(char) for char in str(ticker).upper()) % len(_LOGO_PALETTE)]


def _logo_html(ticker: str) -> str:
    """Logo for any ticker from stockanalysis.com, with a monogram fallback.

    The .svg is tried first, then .png; if both fail the image hides and the
    two-letter monogram on a deterministic colour shows instead. No ticker
    is hardcoded.
    """
    symbol = str(ticker or "").strip().lower()
    monogram = html.escape(str(ticker or "").strip().upper()[:2])
    colour = _logo_color(ticker)
    svg = html.escape(f"https://logos.stockanalysis.com/{symbol}.svg", quote=True)
    png = html.escape(f"https://logos.stockanalysis.com/{symbol}.png", quote=True)
    return (
        f'<span class="desk-logo" style="background:{colour}">{monogram}'
        f'<img src="{svg}" alt="" loading="lazy" '
        f"onerror=\"this.onerror=function(){{this.style.display='none'}};this.src='{png}';\" />"
        "</span>"
    )


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
            if header == "Ticker":
                cells.append(f'<td><a href="{href}" target="_blank" rel="noopener">{_logo_html(str(record["Ticker"]))} {text}</a></td>')
            elif header == "Company":
                cells.append(f'<td><a href="{href}" target="_blank" rel="noopener">{text}</a></td>')
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
    _hydrate_quotes()
    _auto_refresh_once()
    ticker = _requested_ticker()
    if ticker:
        _render_stock_page(ticker)
        return
    _render_watchlist()


def _auto_refresh_once() -> None:
    """Refresh once per session when the newest snapshot is older than 6 hours (PR #55).

    Seeded snapshots are dated 2026-10-30, so a first load triggers this.
    There is no Cloudflare check and no schedule: one refresh, then the flag
    ``desk_auto_refreshed`` stops it repeating for the session.
    """
    if st.session_state.get("desk_auto_refreshed"):
        return
    st.session_state.desk_auto_refreshed = True
    snapshots = _current_snapshots()
    fetched = [_snapshot_fetched_at(snapshot) for snapshot in snapshots]
    newest = max((item for item in fetched if item is not None), default=None)
    if newest is None or datetime.now(timezone.utc) - newest > timedelta(hours=6):
        _refresh_prices()


def _render_watchlist() -> None:
    st.title("Research Desk")
    st.caption(
        "USAR, IBRX, ALMU, NVO, UUUU and SMR start from the seeded snapshots in research-desk/lib/bootstrap.json. "
        "Add a ticker to fetch a quote from Yahoo Finance and valuation fields from Stock Analysis. "
        "A figure stays blank when that source does not publish it. "
        "Names you add, and prices you refresh, stay on this running app until it restarts. "
        "They are not written back to the repo. "
        "Thesis text is the ticker playbook in research-desk/lib/research.ts."
    )

    with st.form("add_ticker", clear_on_submit=True):
        entered = st.text_input("Add a ticker", placeholder="AAPL")
        add = st.form_submit_button("Add to watchlist")
    if add:
        _add_ticker(entered)

    st.markdown("**Search by company name**")
    company_query = st.text_input("Search by company name", placeholder="NVIDIA", key="desk_company_search")
    if st.button("Search", key="desk_company_search_button"):
        if not (company_query or "").strip():
            st.error("Enter a company name to search.")
        else:
            with st.spinner(f"Searching for {company_query.strip()}…"):
                try:
                    st.session_state.desk_search_results = search_symbols(company_query.strip())
                except Exception as exc:
                    st.session_state.desk_search_results = []
                    st.error(f"Company search failed: {exc}")
    search_results = st.session_state.get("desk_search_results") or []
    if search_results:
        options = [f"{result.get('symbol')} — {result.get('name')}" for result in search_results if result.get("symbol")]
        if options:
            chosen = st.selectbox("Search results", options=options, key="desk_company_search_results")
            if st.button("Add selected", key="desk_company_search_add"):
                _add_ticker(str(chosen).split(" — ")[0])
    elif st.session_state.get("desk_search_results") is not None:
        st.caption("No companies matched that search.")

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

    rows = _watchlist(snapshots)[0]
    search_col, filter_col, sort_col = st.columns(3)
    with search_col:
        watch_query = st.text_input("Search watchlist", placeholder="Ticker or company name", key="desk_watchlist_search")
    with filter_col:
        watch_filter = st.selectbox("Filter", options=list(WATCHLIST_FILTERS), key="desk_watchlist_filter")
    with sort_col:
        watch_sort = st.selectbox("Sort", options=list(WATCHLIST_SORTS), key="desk_watchlist_sort")
    shown_rows = filter_watchlist_rows(rows, watch_query, watch_filter, watch_sort)
    st.download_button(
        "Export CSV",
        data=watchlist_csv(shown_rows, st.session_state.get("desk_theses") or {}),
        file_name="research-desk-watchlist.csv",
        mime="text/csv",
    )
    if not shown_rows:
        st.caption("No stocks match the current search and filter.")
    st.markdown(
        """
        <style>
        table.desk-watchlist { width: 100%; border-collapse: collapse; font-size: 0.92rem; }
        table.desk-watchlist th, table.desk-watchlist td {
          text-align: left; padding: 0.45rem 0.4rem;
          border-bottom: 1px solid rgba(128,128,128,0.28); vertical-align: top;
        }
        table.desk-watchlist a { font-weight: 650; }
        .desk-logo {
          position: relative; display: inline-flex; align-items: center; justify-content: center;
          width: 1.6rem; height: 1.6rem; border-radius: 0.35rem; color: #fff;
          font-size: 0.65rem; font-weight: 700; vertical-align: middle; margin-right: 0.3rem;
          overflow: hidden; flex: none;
        }
        .desk-logo img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; background: #fff; }
        .macro-news { font-size: 0.85rem; line-height: 1.4; margin-top: 0.3rem; }
        .macro-news a { font-weight: 400; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(watchlist_html(shown_rows), unsafe_allow_html=True)
    st.caption(
        "Click a ticker or company to open that stock on its own page. "
        "Daily trend is Up when the latest close is higher than each of the previous three daily closes, and Down when it is lower than each of them. Otherwise it is Flat. "
        "Weekly trend compares this week's close with the previous week's close: Up when it is higher, Down when it is lower, and Flat when they are equal. "
        "RSI (14) and the 200-day moving average are daily readings, shown on the daily view and the weekly view. "
        "The 200-day average needs 200 stored daily closes. "
        "Upside is the average analyst target divided by the price, minus one. "
        "The squeeze column counts how many of the five repo heuristics are met. Unknown inputs stay unknown and are not treated as zero."
    )
    st.info("Click a stock in the table to open its thesis and short-squeeze checks on a new page.")


def _remember_quotes() -> None:
    try:
        save_quote_cache(
            {
                "refreshed": st.session_state.desk_refreshed,
                "added": st.session_state.desk_added,
                "refresh_at": st.session_state.get("desk_refresh_at"),
                "errors": st.session_state.get("desk_refresh_errors") or [],
                "theses": st.session_state.get("desk_theses") or {},
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
    st.session_state.desk_theses = cached.get("theses") or {}
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
    """Refresh every watchlist price concurrently (PR #56), skipping stocks refreshed in the last 5 minutes."""
    current = _current_snapshots()
    refreshed = dict(st.session_state.desk_refreshed)
    errors: list[str] = []
    updated = 0
    skipped = 0

    def one(snapshot: dict) -> tuple[str, dict | QuoteError | None, bool]:
        ticker = str(snapshot.get("ticker") or "")
        if _is_fresh(snapshot):
            return ticker, None, True
        try:
            return ticker, refresh_quote(snapshot), False
        except QuoteError as exc:
            return ticker, exc, False

    with st.spinner("Refreshing prices from Yahoo Finance…"):
        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(one, current))
    for ticker, result, was_skipped in outcomes:
        if was_skipped:
            skipped += 1
            continue
        if isinstance(result, QuoteError):
            errors.append(str(result))
            continue
        if result is None:
            continue
        refreshed[ticker] = result
        updated += 1
        if ticker in st.session_state.desk_added:
            st.session_state.desk_added[ticker] = result
    st.session_state.desk_refreshed = refreshed
    st.session_state.desk_refresh_errors = errors
    if updated:
        st.session_state.desk_refresh_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        message = f"Updated {updated} price{'s' if updated != 1 else ''}."
        if skipped:
            message += f" Skipped {skipped} refreshed within the last 5 minutes."
        st.success(message)
    elif not errors:
        if skipped:
            st.info(f"All {skipped} price{'s' if skipped != 1 else ''} were refreshed within the last 5 minutes, so nothing was re-fetched.")
        else:
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
        format_func=lambda days: {"90": "3M", "365": "1Y", "1825": "5Y"}.get(str(days), f"{days} days"),
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
    else:
        st.line_chart(chart, height=180)
        st.caption("Close dates are not stored, so the 3M, 1Y and 5Y choices cannot be applied.")
    returns: list[str] = []
    for days, label in ((365, "1-year"), (1825, "5-year")):
        value = _return_over_days(snapshot, days)
        if value is not None:
            returns.append(f"{label} return {_percent(value, 1, signed=True)}")
    if returns:
        st.caption(" · ".join(returns) + ". Date-anchored on the latest stored close.")


def _render_stock_page(ticker: str) -> None:
    """The stock on its own, without the watchlist."""
    st.markdown(
        '<p><a href="/research-desk" target="_self">Back to the watchlist</a></p>',
        unsafe_allow_html=True,
    )
    snapshot = next((row for row in _current_snapshots() if str(row.get("ticker")) == ticker), None)
    if snapshot is None:
        st.warning(f"{ticker} is not on the watchlist.")
        return
    _render_detail(snapshot)


def _render_detail(snapshot: dict) -> None:
    ticker = str(snapshot.get("ticker"))
    st.title(f"{ticker} · {snapshot.get('name') or 'Name not in snapshot'}")

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

    st.markdown("**Headlines**")
    headlines = snapshot.get("headlines") if isinstance(snapshot.get("headlines"), list) else []
    if headlines:
        for item in headlines[:5]:
            if not isinstance(item, dict) or not item.get("title") or not item.get("url"):
                continue
            title = html.escape(str(item["title"]))
            url = html.escape(str(item["url"]), quote=True)
            date_text = f" ({html.escape(str(item['date']))})" if item.get("date") else ""
            st.markdown(f"- [{title}]({url}){date_text}")
    else:
        st.caption("Headlines are unavailable / not yet fetched for this stock.")

    st.markdown("**Insider trades**")
    trades = snapshot.get("insiderTrades") if isinstance(snapshot.get("insiderTrades"), list) else []
    if trades:
        insider_rows = []
        for trade in trades:
            if not isinstance(trade, dict):
                continue
            insider_rows.append(
                {
                    "Date": trade.get("date") or "",
                    "Insider": trade.get("insider") or "",
                    "Type": trade.get("type") or "",
                    "Shares": trade.get("shares") or "",
                    "Entry price": _money(trade.get("price")) or "",
                }
            )
        st.dataframe(pd.DataFrame(insider_rows), use_container_width=True, hide_index=True)
    else:
        sources = snapshot.get("sources") if isinstance(snapshot.get("sources"), dict) else {}
        insider_source = sources.get("insider") if isinstance(sources.get("insider"), dict) else {}
        if insider_source.get("error"):
            st.caption(f"Insider trades: {insider_source['error']}")
        else:
            st.caption("No insider trades returned.")
    st.caption(
        "Politician/congressional trades are not available — there is no free structured feed, "
        "and disclosures are typically value ranges with no exact entry price."
    )

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

    saved_theses = st.session_state.get("desk_theses") or {}
    stored_thesis = saved_theses.get(ticker, "")
    typed_thesis = st.text_area("Thesis", value=stored_thesis, key=f"desk_thesis_{ticker}", height=120)
    if st.button("Save thesis", key=f"desk_thesis_save_{ticker}"):
        updated_theses = dict(st.session_state.get("desk_theses") or {})
        updated_theses[ticker] = typed_thesis
        st.session_state.desk_theses = updated_theses
        _remember_quotes()
        st.success("Thesis saved.")
    saved_now = (st.session_state.get("desk_theses") or {}).get(ticker, "")
    if typed_thesis == saved_now and saved_now:
        st.caption("Saved.")
    elif typed_thesis == saved_now:
        st.caption("No thesis saved yet.")
    else:
        st.caption("Unsaved changes.")
    st.caption(
        "Discuss your thesis with Muse in chat and Muse adds it here. "
        "It is speculation, not sourced data, and not the automatic playbook thesis above."
    )

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
