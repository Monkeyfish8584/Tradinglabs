"""Macro Desk page for the Streamlit app.

This page REPLACES the old Research Desk (PRs #55-#61). The old desk
grew into a stock-research tool with seeded playbook tickers, a Thesis
box, CANSLIM, a spider diagram, insider trades and short-squeeze checks.
The Macro Desk, per Oliver's spec (workspace/user/files/macro-desk-spec_0_ho0x.md),
is a macro-first dashboard for equity index traders:

- Five indices (DAX, UK100, US100, US30, US500) with W/D/4H trend pills
  and breadth gauges (above 50MA, new highs vs previous day).
- A 7-day red-folder (high-impact) economic calendar, with an event
  detail panel showing forecast / previous / actual.
- One index page per index: hero, 60-session price chart, recent news,
  underlying breadth (top constituents) and red-folder events for it.
- A watchlist: search by ticker or company name, add, and see price,
  analyst target + upside/downside, 50MA, 200MA, weekly, daily and
  forward P/E. Stock detail is a placeholder for now.

Live data comes from the same public providers the old desk used:
Yahoo Finance for prices/closes (``research_desk_quotes``), Forex
Factory's free weekly calendar JSON for red-folder events, Google News
RSS for index news, Stock Analysis for analyst targets / forward P/E.
A figure stays blank when its source does not publish it; nothing is
invented. There is no Thesis box, no CANSLIM, no spider, no insider
trades and no short-squeeze checks in this desk — the spec does not
ask for them.

Calculation defaults (spec section 4, unconfirmed by the user, all in
one config place at the top of this file):
- Trend (W/D/4H): Bullish if the latest close is above the 50-period
  EMA of that timeframe AND the 50 EMA is rising; otherwise Bearish.
- Above 50MA / 200MA: latest daily close vs the 50-day / 200-day SMA.
- Breadth above 50MA: constituents whose latest close is above their
  own 50-day SMA, out of constituents with enough history.
- Breadth new highs: constituents whose current session high exceeds
  the previous session's high.
- Forward P/E: price / consensus next-12-month EPS (as published by
  Stock Analysis); analyst target is the consensus mean target.

The Data Hub / Data tab in app.py is untouched by this change.
"""

from __future__ import annotations

import html
import json
import math
import re
import tempfile
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from research_desk_quotes import (
    QuoteError,
    fetch_candles,
    fetch_new_snapshot,
    fetch_news_rss,
    fetch_red_folder_events,
    fetch_text,
    fetch_trend_snapshot,
    normalize_ticker,
    search_symbols,
    trend_from_closes,
    weekly_closes_from_daily,
)

# ---------------------------------------------------------------------------
# Config — the spec's calculation defaults, in one place (spec section 4).
# ---------------------------------------------------------------------------
TREND_EMA_PERIOD = 50
BREADTH_SMA_PERIOD = 50
CHART_SESSIONS = 60
CALENDAR_DAYS = 7

try:
    LONDON = ZoneInfo("Europe/London")
except Exception:
    LONDON = timezone.utc

# id, label, full name, Yahoo symbol, flag, currency, hero gradient.
MACRO_INDICES: tuple[dict[str, str], ...] = (
    {"id": "dax", "label": "DAX", "name": "Germany 40", "symbol": "^GDAXI", "flag": "🇩🇪", "currency": "EUR", "gradient": "linear-gradient(100deg,#1e3a8a,#3b82f6)"},
    {"id": "uk100", "label": "UK100", "name": "FTSE 100", "symbol": "^FTSE", "flag": "🇬🇧", "currency": "GBP", "gradient": "linear-gradient(100deg,#0f766e,#14b8a6)"},
    {"id": "ndx", "label": "US100", "name": "Nasdaq 100", "symbol": "^NDX", "flag": "🇺🇸", "currency": "USD", "gradient": "linear-gradient(100deg,#7c3aed,#a78bfa)"},
    {"id": "dow", "label": "US30", "name": "Dow Jones 30", "symbol": "^DJI", "flag": "🇺🇸", "currency": "USD", "gradient": "linear-gradient(100deg,#92400e,#f59e0b)"},
    {"id": "spx", "label": "US500", "name": "S&P 500", "symbol": "^GSPC", "flag": "🇺🇸", "currency": "USD", "gradient": "linear-gradient(100deg,#065f46,#10b981)"},
)
INDEX_BY_ID = {item["id"]: item for item in MACRO_INDICES}
INDEX_BY_LABEL = {item["label"]: item for item in MACRO_INDICES}

# Event currency -> indices it affects (spec 3.2, configurable here).
# EUR affects DAX; GBP affects UK100; USD affects US100, US30, US500.
# Major US events also affect DAX (Fed Beige Book, FOMC, US CPI, US jobs).
EVENT_INDEX_MAP: dict[str, tuple[str, ...]] = {
    "EUR": ("dax",),
    "GBP": ("uk100",),
    "USD": ("ndx", "dow", "spx"),
}
MAJOR_US_FOR_DAX = ("FED", "FOMC", "BEIGE BOOK", "CPI", "NONFARM", "NFP", "JOBS", "FED CHAIR", "POWELL")

# Index constituents published on Wikipedia. GER30 uses current DAX membership.
BREADTH_SOURCES: dict[str, dict[str, str]] = {
    "dax": {"url": "https://en.wikipedia.org/wiki/DAX", "label": "DAX"},
    "uk100": {"url": "https://en.wikipedia.org/wiki/FTSE_100_Index", "label": "UK100"},
    "ndx": {"url": "https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies", "label": "US100"},
    "dow": {"url": "https://en.wikipedia.org/wiki/List_of_Dow_Jones_Industrial_Average_companies", "label": "US30"},
    "spx": {"url": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "label": "US500"},
}

QUOTE_CACHE_PATH = Path(tempfile.gettempdir()) / "tradinglabs-macro-desk-watchlist.json"

# Generic, event-type explanations for the event detail panel. These are
# general descriptions of what the release measures, not data about a
# specific release — the numbers always come from the Forex Factory feed.
EVENT_NOTES: tuple[tuple[str, str, str], ...] = (
    ("CPI", "What it measures: consumer price inflation. Higher than forecast usually points to stickier inflation and can push rate-cut expectations later; lower than forecast usually does the opposite.",
     "Typical reaction: currency and rate-sensitive stocks often move sharply in the first minutes; indices can swing either way depending on whether the print helps or hurts the rate outlook."),
    ("PMI", "What it measures: business activity in manufacturing or services. Above 50 means expansion, below 50 means contraction.",
     "Typical reaction: a surprise either way can move cyclicals and the currency; a weak print can lift rate-cut hopes, a strong one can do the opposite."),
    ("JOLTS", "What it measures: job openings in the US — a read on how tight the labour market is.",
     "Typical reaction: a hot labour market can push back rate-cut expectations; a cool one can bring them forward."),
    ("BEIGE BOOK", "What it is: the Fed's anecdotal survey of economic conditions across its districts, published ahead of FOMC meetings.",
     "Typical reaction: usually a slow-burn read rather than a spike, but hawkish or dovish language can move bonds and equities."),
    ("FOMC", "What it is: the US Federal Reserve's rate decision and statement.",
     "Typical reaction: one of the biggest market movers — rates, the dollar and equities can all swing sharply on the decision and the press conference."),
    ("NONFARM", "What it measures: US jobs added outside farming, plus unemployment and wage growth.",
     "Typical reaction: a big beat or miss can move everything — the dollar, yields and equities — within minutes."),
    ("LAGARDE", "What it is: the ECB President speaking — markets listen for hints on the next rate move.",
     "Typical reaction: any hint on timing of cuts or hikes can move the euro and European equities."),
    ("POWELL", "What it is: the Fed Chair speaking — markets listen for hints on the next rate move.",
     "Typical reaction: any hint on timing of cuts or hikes can move the dollar, yields and equities."),
    ("GDP", "What it measures: overall economic growth for the quarter.",
     "Typical reaction: a surprise can shift rate expectations and move equities and the currency."),
    ("RETAIL SALES", "What it measures: consumer spending — a read on how strong the consumer is.",
     "Typical reaction: a strong print can lift rate expectations and the currency; a weak one can do the opposite."),
)
GENERIC_EVENT_NOTE = (
    "What it measures: a high-impact economic release. The forecast and previous readings above are the numbers to watch against the actual when it lands.",
    "Typical reaction: high-impact releases can move the affected currency and its indices sharply in the first minutes after release.",
)


def sma(values: list[float], period: int) -> float | None:
    """Simple moving average of the last ``period`` values, or None when too few."""
    if period <= 0 or len(values) < period:
        return None
    return sum(values[-period:]) / period


def event_notes(title: str) -> tuple[str, str]:
    """Generic explanation for an event title, from EVENT_NOTES or the generic fallback."""
    upper = (title or "").upper()
    for keyword, expected, reaction in EVENT_NOTES:
        if keyword in upper:
            return expected, reaction
    return GENERIC_EVENT_NOTE


def affected_indices(event: dict) -> list[str]:
    """Index ids affected by one red-folder event (spec 3.2)."""
    country = str(event.get("country") or "").upper()
    ids = list(EVENT_INDEX_MAP.get(country, ()))
    if country == "USD":
        title = str(event.get("title") or "").upper()
        if any(word in title for word in MAJOR_US_FOR_DAX) and "dax" not in ids:
            ids.append("dax")
    return ids


def _money(value: object, symbol: str = "$") -> str | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return f"{symbol}{float(value):,.2f}"


def _percent(value: object, digits: int = 1, *, signed: bool = False) -> str | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
        return None
    number = float(value)
    body = f"{abs(number):,.{digits}f}%"
    if number < 0:
        return f"-{body}"
    return f"+{body}" if signed and number > 0 else body


def _pill(label: str, trend: str | None) -> str:
    """A W/D/4H pill: the word Bullish or Bearish, never colour alone."""
    if trend == "Bullish":
        return f'<span class="md-pill md-bull">{html.escape(label)}<br>Bullish</span>'
    if trend == "Bearish":
        return f'<span class="md-pill md-bear">{html.escape(label)}<br>Bearish</span>'
    return f'<span class="md-pill md-missing">{html.escape(label)}<br>Unavailable</span>'


MACRO_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&family=DM+Mono:wght@400;500&display=swap');
.md-title { font-family: 'DM Sans', sans-serif; }
.md-mono { font-family: 'DM Mono', monospace; font-variant-numeric: tabular-nums; }
.md-strip { display: flex; gap: 0.6rem; flex-wrap: wrap; }
.md-card { flex: 1 1 11rem; border: 1px solid rgba(128,128,128,0.35); border-radius: 10px; padding: 0.6rem 0.7rem; line-height: 1.35; background: var(--md-card-bg, transparent); }
.md-card.md-active { outline: 2px solid #2563eb; }
.md-card-name { font-weight: 700; font-size: 1.05rem; }
.md-card-change { font-family: 'DM Mono', monospace; font-weight: 500; float: right; }
.md-up { color: #15803d; } .md-down { color: #b42318; }
.md-pills { display: flex; gap: 0.35rem; margin: 0.45rem 0; }
.md-pill { flex: 1; text-align: center; font-size: 0.8rem; line-height: 1.3; padding: 0.35rem 0.2rem; border-radius: 6px; }
.md-bull { background: rgba(21,128,61,0.12); color: #15803d; }
.md-bear { background: rgba(180,35,24,0.12); color: #b42318; }
.md-missing { background: rgba(128,128,128,0.15); color: #666; }
.md-gauge-label { font-size: 0.78rem; color: #666; }
.md-gauge-num { font-family: 'DM Mono', monospace; font-weight: 500; }
.md-gauge-track { height: 6px; border-radius: 3px; background: rgba(128,128,128,0.25); margin: 0.2rem 0 0.45rem; overflow: hidden; }
.md-gauge-fill { height: 100%; border-radius: 3px; }
.md-hero { border-radius: 12px; padding: 1.1rem 1.2rem; color: #fff; margin-bottom: 0.6rem; position: relative; overflow: hidden; }
.md-hero h2 { margin: 0; color: #fff; }
.md-hero .md-hero-price { font-family: 'DM Mono', monospace; font-size: 1.1rem; }
.md-hero .md-hero-flag { position: absolute; right: 1rem; top: 0.9rem; font-size: 1.4rem; font-weight: 700; opacity: 0.9; }
.md-hero .md-skyline { position: absolute; right: 0; bottom: 0; opacity: 0.25; font-size: 2.2rem; letter-spacing: 0.1rem; line-height: 1; }
.md-event-chip { display: block; width: 100%; text-align: left; background: rgba(180,35,24,0.10); border-left: 3px solid #b42318; border-radius: 6px; padding: 0.4rem 0.5rem; margin-top: 0.4rem; font-size: 0.85rem; line-height: 1.35; }
.md-event-chip .md-event-meta { font-size: 0.78rem; color: #666; }
.md-news-item { margin: 0.45rem 0; font-size: 0.92rem; }
.md-news-meta { font-size: 0.78rem; color: #666; }
.md-breadth-num { font-family: 'DM Mono', monospace; font-size: 1.5rem; font-weight: 500; }
.md-dot { display: inline-block; width: 0.7rem; height: 0.7rem; border-radius: 50%; }
.md-dot-on { background: #15803d; } .md-dot-off { background: rgba(128,128,128,0.35); }
table.md-watchlist { width: 100%; border-collapse: collapse; font-size: 0.92rem; }
table.md-watchlist th, table.md-watchlist td { text-align: left; padding: 0.45rem 0.4rem; border-bottom: 1px solid rgba(128,128,128,0.28); vertical-align: top; }
</style>
"""


# ---------------------------------------------------------------------------
# Data loading — cached, honest unavailable states, no invented figures.
# ---------------------------------------------------------------------------

def _trend_from_candles(candles: list[dict]) -> str | None:
    """EMA50 trend for one candle set (spec section 4)."""
    closes = [float(c["close"]) for c in candles if isinstance(c.get("close"), (int, float)) and not isinstance(c.get("close"), bool)]
    return trend_from_closes(closes, TREND_EMA_PERIOD)


def load_index_data(index_id: str, getter=None) -> dict:
    """Price, change, W/D/4H trends and last-60-session closes for one index.

    Returns {"available": False, ...} when Yahoo does not return a price —
    the page shows that honestly instead of guessing.
    """
    item = INDEX_BY_ID[index_id]
    symbol = item["symbol"]
    try:
        quote = fetch_trend_snapshot(symbol, getter, span="6mo")
        daily = fetch_candles(symbol, interval="1d", span="1y", getter=getter)
    except QuoteError:
        return {"id": index_id, "available": False}
    try:
        weekly = fetch_candles(symbol, interval="1wk", span="5y", getter=getter)
    except QuoteError:
        weekly = []
    try:
        hourly = fetch_candles(symbol, interval="60m", span="1mo", getter=getter)
        four_hour = _trend_from_candles(_aggregate_4h(hourly))
    except QuoteError:
        four_hour = None
    closes60 = [c["close"] for c in daily[-CHART_SESSIONS:]]
    dates60 = [c["date"] for c in daily[-CHART_SESSIONS:]]
    return {
        "id": index_id,
        "available": True,
        "price": quote.get("price"),
        "change_pct": quote.get("changePct"),
        "currency": quote.get("currency"),
        "weekly_trend": _trend_from_candles(weekly),
        "daily_trend": _trend_from_candles(daily),
        "four_hour_trend": four_hour,
        "closes60": closes60,
        "dates60": dates60,
        "daily_candles": daily,
    }


def _aggregate_4h(candles: list[dict]) -> list[dict]:
    """Group consecutive hourly candles into 4-hour candles."""
    grouped: list[dict] = []
    for start in range(0, len(candles) - 3, 4):
        group = candles[start : start + 4]
        grouped.append({"date": group[-1].get("date"), "close": group[-1].get("close"), "high": max(c["high"] for c in group), "low": min(c["low"] for c in group)})
    return grouped


@st.cache_data(ttl=300, show_spinner=False)
def cached_index_data(index_id: str) -> dict:
    """Index data, recalculated at most every 5 minutes (spec section 4)."""
    return load_index_data(index_id)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_red_folder() -> dict:
    """All high-impact events for the next 7 days, fetched at most hourly."""
    return fetch_red_folder_events()


# --- Constituents and breadth (spec section 4) ---------------------------

def constituent_symbols(html_body: str, index_id: str) -> list[str]:
    """Yahoo symbols for one index from its Wikipedia list page.

    An unreadable table returns an empty list. Lists are loaded from the
    data source, not hard-coded (spec section 2).
    """
    from research_desk_quotes import table_rows

    rows = table_rows(html_body)
    found: list[str] = []
    if index_id == "spx":
        start = next((i for i, row in enumerate(rows) if row and row[0]["text"].strip() == "Symbol"), None)
        column, pattern, venue = 0, r"[A-Z]{1,5}(?:\.[A-Z])?", "us"
    elif index_id == "ndx":
        start = next((i for i, row in enumerate(rows) if row and row[0]["text"].strip() == "Ticker"), None)
        column, pattern, venue = 0, r"[A-Z]{1,5}(?:\.[A-Z])?", "us"
    elif index_id == "dow":
        start = next((i for i, row in enumerate(rows) if len(row) > 2 and row[2]["text"].strip() == "Symbol"), None)
        column, pattern, venue = 2, r"[A-Z]{1,5}(?:\.[A-Z])?", "us"
    elif index_id == "uk100":
        start = next((i for i, row in enumerate(rows) if len(row) > 1 and row[0]["text"].strip() == "Company" and row[1]["text"].strip().startswith("Ticker")), None)
        column, pattern, venue = 1, r"[A-Z0-9]{2,6}(?:\.[A-Z])?", "uk"
    elif index_id == "dax":
        start = next((i for i, row in enumerate(rows) if row and row[0]["text"].strip() == "Ticker"), None)
        column, pattern, venue = 0, r"[A-Z0-9]{1,6}\.[A-Z]{1,3}", "de"
    else:
        return []
    if start is None:
        return []
    for row in rows[start + 1 :]:
        if len(row) <= column:
            break
        cleaned = row[column]["text"].strip().upper()
        if not re.fullmatch(pattern, cleaned):
            break
        symbol = cleaned
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


def constituent_names(html_body: str, index_id: str) -> list[str]:
    """Company names alongside constituent_symbols, in the same row order."""
    from research_desk_quotes import table_rows

    rows = table_rows(html_body)
    names: list[str] = []
    if index_id == "spx":
        start = next((i for i, row in enumerate(rows) if row and row[0]["text"].strip() == "Symbol"), None)
        name_col = 1
    elif index_id == "ndx":
        start = next((i for i, row in enumerate(rows) if row and row[0]["text"].strip() == "Ticker"), None)
        name_col = 1
    elif index_id == "dow":
        start = next((i for i, row in enumerate(rows) if len(row) > 2 and row[2]["text"].strip() == "Symbol"), None)
        name_col = 0
    elif index_id == "uk100":
        start = next((i for i, row in enumerate(rows) if len(row) > 1 and row[0]["text"].strip() == "Company" and row[1]["text"].strip().startswith("Ticker")), None)
        name_col = 0
    elif index_id == "dax":
        start = next((i for i, row in enumerate(rows) if row and row[0]["text"].strip() == "Ticker"), None)
        name_col = 1
    else:
        return []
    if start is None:
        return []
    symbols = constituent_symbols(html_body, index_id)
    for row in rows[start + 1 : start + 1 + len(symbols)]:
        if len(row) <= name_col:
            names.append("")
        else:
            names.append(row[name_col]["text"].strip())
    return names


@st.cache_data(ttl=3600, show_spinner=False)
def cached_constituents(index_id: str) -> dict:
    """Constituent symbols and names for one index, from Wikipedia."""
    source = BREADTH_SOURCES.get(index_id)
    if source is None:
        return {"symbols": [], "names": []}
    try:
        page = fetch_text(source["url"])
    except Exception:
        return {"symbols": [], "names": []}
    return {"symbols": constituent_symbols(page, index_id), "names": constituent_names(page, index_id)}


def breadth_summary(index_id: str, per_symbol: list[dict | None]) -> dict:
    """Above-50MA and new-high counts, per the spec's definitions.

    ``per_symbol`` is one entry per constituent: {"above50": bool|None,
    "new_high": bool|None} or None when that constituent published no
    usable closes. Missing constituents stay out of both counts.
    """
    above = highs = measured = unknown = 0
    for item in per_symbol:
        if not item or item.get("above50") is None and item.get("new_high") is None:
            unknown += 1
            continue
        measured += 1
        if item.get("above50"):
            above += 1
        if item.get("new_high"):
            highs += 1
    listed = len(per_symbol)
    ready = listed > 0 and measured > 0 and measured * 2 >= listed
    return {"index_id": index_id, "listed": listed, "measured": measured, "unknown": unknown, "above50": above, "new_highs": highs, "ready": ready}


def load_macro_breadth(index_id: str, getter=None) -> dict:
    """Breadth for one index: above 50MA and new highs vs previous day.

    Each constituent needs at least 51 daily closes for its 50-day SMA
    and the last two sessions' highs for the new-high read. A constituent
    that does not publish them is left out, never counted as either.
    """
    symbols = cached_constituents(index_id).get("symbols") or []
    if not symbols:
        return {"index_id": index_id, "listed": 0, "measured": 0, "unknown": 0, "above50": 0, "new_highs": 0, "ready": False, "top": []}
    get = getter or fetch_text

    def one(symbol: str) -> dict | None:
        try:
            candles = fetch_candles(symbol, interval="1d", span="6mo", getter=get)
        except Exception:
            return None
        closes = [float(c["close"]) for c in candles if isinstance(c.get("close"), (int, float))]
        if len(closes) < BREADTH_SMA_PERIOD + 1 or len(candles) < 2:
            return None
        average = sma(closes, BREADTH_SMA_PERIOD)
        if average is None:
            return None
        last, previous = candles[-1], candles[-2]
        return {
            "symbol": symbol,
            "above50": closes[-1] > average,
            "new_high": bool(isinstance(last.get("high"), (int, float)) and isinstance(previous.get("high"), (int, float)) and float(last["high"]) > float(previous["high"])),
        }

    if getter is None and len(symbols) > 1:
        with ThreadPoolExecutor(max_workers=8) as pool:
            per_symbol = list(pool.map(one, symbols))
    else:
        per_symbol = [one(symbol) for symbol in symbols]
    summary = breadth_summary(index_id, per_symbol)
    names = cached_constituents(index_id).get("names") or []
    top: list[dict] = []
    for position, item in enumerate(per_symbol[:8]):
        if item is None:
            continue
        top.append({"name": names[position] if position < len(names) else item["symbol"], "symbol": item["symbol"], "above50": item["above50"], "new_high": item["new_high"]})
    summary["top"] = top
    return summary


@st.cache_data(ttl=1800, show_spinner=False)
def cached_breadth(index_id: str) -> dict:
    """Breadth, recalculated at most every 30 minutes."""
    return load_macro_breadth(index_id)


def parent_index(ticker: str) -> str | None:
    """Which of the five indices lists this ticker, if any.

    Tickers are matched with their exchange suffix stripped (e.g. SAP.DE
    and AZN.L match the DAX / FTSE lists). A ticker in no list returns None.
    """
    base = (ticker or "").upper().replace(".DE", "").replace(".L", "").replace("-", ".")
    for item in MACRO_INDICES:
        symbols = cached_constituents(item["id"]).get("symbols") or []
        for symbol in symbols:
            if symbol.upper().replace(".DE", "").replace(".L", "").replace("-", ".") == base:
                return item["label"]
    return None


# ---------------------------------------------------------------------------
# Red-folder calendar (spec 3.2)
# ---------------------------------------------------------------------------

def calendar_days(calendar: dict | None, today: date | None = None) -> list[dict]:
    """Seven day columns starting today, each with its high-impact events."""
    start = today or datetime.now(LONDON).date()
    events = []
    if isinstance(calendar, dict) and isinstance(calendar.get("events"), list):
        events = [e for e in calendar["events"] if isinstance(e, dict) and isinstance(e.get("date"), datetime)]
    days: list[dict] = []
    for offset in range(CALENDAR_DAYS):
        day = start + timedelta(days=offset)
        day_events = [e for e in events if e["date"].astimezone(LONDON).date() == day]
        days.append({"date": day, "weekend": day.weekday() >= 5, "events": sorted(day_events, key=lambda e: e["date"])})
    return days


def _event_key(event: dict) -> str:
    when = event.get("date")
    stamp = when.isoformat() if isinstance(when, datetime) else str(when or "")
    return f"{stamp}|{event.get('country') or ''}|{event.get('title') or ''}"


def render_event_detail() -> None:
    """Event detail panel for the selected red-folder event.

    Streamlit has no native modal, so the detail renders as a panel at
    the top of the calendar with a Close button (and the same panel is
    used from index pages). It shows forecast / previous / actual, a
    generic explanation, the typical reaction, and affected indices.
    """
    selected = st.session_state.get("macro_event")
    if not selected:
        return
    calendar = st.session_state.get("macro_calendar") or {}
    events = calendar.get("events") if isinstance(calendar, dict) else []
    event = next((e for e in (events or []) if isinstance(e, dict) and _event_key(e) == selected), None)
    if event is None:
        st.session_state.macro_event = None
        return
    when = event.get("date")
    when_text = when.astimezone(LONDON).strftime("%a %d %b, %H:%M") if isinstance(when, datetime) else str(when or "")
    expected, reaction = event_notes(str(event.get("title") or ""))
    st.markdown("### 🔴 " + html.escape(str(event.get("title") or "")))
    st.write(f"{when_text} · {event.get('country') or ''} · High impact")
    cols = st.columns(3)
    cols[0].metric("Forecast", str(event.get("forecast") or "–"))
    cols[1].metric("Previous", str(event.get("previous") or "–"))
    cols[2].metric("Actual", str(event.get("actual") or "–"))
    st.caption("Actual shows – until the release, then it updates from the calendar feed.")
    st.markdown("**What's expected**")
    st.write(expected)
    st.markdown("**Typical reaction**")
    st.write(reaction)
    st.markdown("**Affected indices**")
    ids = affected_indices(event)
    if not ids:
        st.caption("No index in this desk is directly affected by this event.")
    for index_id in ids:
        item = INDEX_BY_ID[index_id]
        if st.button(f"{item['flag']} {item['label']} — {item['name']}", key=f"macro_event_index_{index_id}"):
            st.session_state.macro_event = None
            st.query_params["index"] = index_id
            st.rerun()
    if st.button("Close", key="macro_event_close"):
        st.session_state.macro_event = None
        st.rerun()


def render_calendar(calendar: dict | None, index_id: str | None = None) -> None:
    """Seven day columns of red-folder events, filtered by index if given."""
    st.markdown("## Red folder — next 7 days")
    if isinstance(calendar, dict) and not calendar.get("available"):
        st.caption("Economic calendar unavailable — the Forex Factory feed could not be read.")
        return
    days = calendar_days(calendar)
    if index_id is not None:
        days = [{**day, "events": [e for e in day["events"] if index_id in affected_indices(e)]} for day in days]
    cols = st.columns(7)
    for col, day in zip(cols, days):
        with col:
            st.markdown(f"**{day['date'].strftime('%a %d')}**")
            if day["weekend"]:
                st.caption("Weekend")
            elif not day["events"]:
                st.caption("Nothing red")
            for event in day["events"]:
                when = event["date"].astimezone(LONDON).strftime("%H:%M")
                label = f"{event.get('title') or ''} · {when} · {event.get('country') or ''}"
                if st.button(label, key=f"macro_event_{_event_key(event)}", width="stretch"):
                    st.session_state.macro_event = _event_key(event)
                    st.session_state.macro_calendar = calendar
                    st.rerun()
    if isinstance(calendar, dict) and calendar.get("partial"):
        st.caption("Next week's calendar feed was not available, so this list may end before the full 7 days.")


def render_red_folder_list(calendar: dict | None, index_id: str) -> None:
    """Red-folder list for one index, on its index page (spec 3.3)."""
    item = INDEX_BY_ID[index_id]
    st.markdown(f"## Red folder for {item['label']}")
    if isinstance(calendar, dict) and not calendar.get("available"):
        st.caption("Economic calendar unavailable.")
        return
    events = [e for e in calendar_days(calendar) for e in e["events"]] if calendar else []
    mine = [e for e in events if index_id in affected_indices(e)]
    if not mine:
        st.caption(f"No high-impact (red-folder) events for {item['label']} in the next 7 days.")
        return
    for event in mine:
        when = event["date"].astimezone(LONDON).strftime("%a %d %b, %H:%M") if isinstance(event.get("date"), datetime) else ""
        if st.button(f"{event.get('title') or ''} — {when} · {event.get('country') or ''}", key=f"macro_list_event_{_event_key(event)}", width="stretch"):
            st.session_state.macro_event = _event_key(event)
            st.session_state.macro_calendar = calendar
            st.rerun()


# ---------------------------------------------------------------------------
# Top index strip (spec 3.1) and index pages (spec 3.3)
# ---------------------------------------------------------------------------

def _strip_card(item: dict, data: dict, active: bool) -> str:
    label = item["label"]
    if not data.get("available"):
        change = "—"
        change_class = ""
        pills = _pill("W", None) + _pill("D", None) + _pill("4H", None)
        gauges = '<div class="md-gauge-label">Breadth unavailable</div>'
    else:
        change = _percent(data.get("change_pct"), 2, signed=True) or "—"
        change_class = "md-up" if (data.get("change_pct") or 0) >= 0 else "md-down"
        pills = _pill("W", data.get("weekly_trend")) + _pill("D", data.get("daily_trend")) + _pill("4H", data.get("four_hour_trend"))
        breadth = data.get("breadth") or {}
        if breadth.get("ready"):
            listed = int(breadth.get("listed") or 0)
            above = int(breadth.get("above50") or 0)
            highs = int(breadth.get("new_highs") or 0)
            above_pct = (above / listed * 100) if listed else 0
            high_pct = (highs / listed * 100) if listed else 0
            above_colour = "#15803d" if above_pct >= 50 else "#b42318"
            gauges = (
                f'<div><span class="md-gauge-label" title="Constituents whose latest close is above their 50-day moving average">50MA</span> '
                f'<span class="md-gauge-num" style="float:right">{above}/{listed}</span></div>'
                f'<div class="md-gauge-track"><div class="md-gauge-fill" style="width:{above_pct:.0f}%;background:{above_colour}"></div></div>'
                f'<div><span class="md-gauge-label" title="Constituents whose current session high exceeds the previous session high">Highs</span> '
                f'<span class="md-gauge-num" style="float:right">{highs}/{listed}</span></div>'
                f'<div class="md-gauge-track"><div class="md-gauge-fill" style="width:{high_pct:.0f}%;background:#2563eb"></div></div>'
            )
        else:
            gauges = '<div class="md-gauge-label">Breadth unavailable — not enough constituent quotes published.</div>'
    active_class = " md-active" if active else ""
    href = f"?index={item['id']}"
    return (
        f'<div class="md-card{active_class}">'
        f'<div><a href="{href}" target="_self" style="text-decoration:none;color:inherit">'
        f'<span class="md-card-name">{item["flag"]} {html.escape(label)}</span>'
        f'<span class="md-card-change {change_class}">{html.escape(change)}</span></a></div>'
        f'<div class="md-pills">{pills}</div>{gauges}</div>'
    )


def render_strip(active_id: str | None = None) -> dict:
    """Five index cards in a row, with W/D/4H pills and breadth gauges.

    Returns {index_id: data} so the index page can reuse the same load.
    """
    st.markdown('<h1 class="md-title"><a href="?index=" target="_self" style="text-decoration:none;color:inherit">Macro Desk</a></h1>', unsafe_allow_html=True)
    st.caption("Live data from Yahoo Finance, Forex Factory and Google News. A figure stays blank when its source does not publish it.")
    data: dict[str, dict] = {}
    with st.spinner("Loading indices…"):
        for item in MACRO_INDICES:
            try:
                data[item["id"]] = cached_index_data(item["id"])
            except Exception:
                data[item["id"]] = {"id": item["id"], "available": False}
    # Breadth is slow (one quote per constituent), so load it only for the
    # strip's gauges and cache it for 30 minutes.
    for item in MACRO_INDICES:
        try:
            data[item["id"]]["breadth"] = cached_breadth(item["id"])
        except Exception:
            data[item["id"]]["breadth"] = {"ready": False}
    st.markdown(MACRO_CSS + '<div class="md-strip">' + "".join(_strip_card(item, data[item["id"]], active_id == item["id"]) for item in MACRO_INDICES) + "</div>", unsafe_allow_html=True)
    st.caption("50MA: constituents above their 50-day moving average. Highs: constituents whose current session high exceeds the previous session's high. Click a card to open that index.")
    return data


def render_index_page(index_id: str, data: dict, calendar: dict | None) -> None:
    """One index on one page: hero, 60-session chart, news, breadth, red folder."""
    item = INDEX_BY_ID[index_id]
    info = data.get(index_id) or {}
    if st.button("← Back to Macro Desk", key="macro_index_back"):
        st.query_params.clear()
        st.rerun()
    if not info.get("available"):
        st.warning(f"{item['label']} trend and price could not be loaded from Yahoo Finance.")
    price = info.get("price")
    change = _percent(info.get("change_pct"), 2, signed=True) or ""
    price_text = f"{price:,.1f}" if isinstance(price, (int, float)) else "—"
    st.markdown(
        f'<div class="md-hero" style="background:{item["gradient"]}">'
        f'<span class="md-hero-flag">{item["flag"]} {item["id"].upper()}</span>'
        f'<h2>{html.escape(item["name"])}</h2>'
        f'<div class="md-hero-price">{price_text} {change}</div>'
        f'<div class="md-skyline" aria-hidden="true">▂▃▄▅▆▇█▇▆▅▄▃▂</div></div>',
        unsafe_allow_html=True,
    )
    closes = info.get("closes60") or []
    dates = info.get("dates60") or []
    st.markdown("**Price — 60 sessions**")
    if closes:
        chart = pd.DataFrame({"Close": closes}, index=dates if len(dates) == len(closes) else None)
        st.line_chart(chart, height=220)
    else:
        st.caption("Price chart unavailable — no daily closes were published.")
    st.markdown(
        '<div class="md-pills">' + _pill("Weekly", info.get("weekly_trend")) + _pill("Daily", info.get("daily_trend")) + _pill("4H", info.get("four_hour_trend")) + "</div>",
        unsafe_allow_html=True,
    )
    st.caption("Trend: Bullish if the latest close is above the 50-period EMA and the 50 EMA is rising, otherwise Bearish (spec section 4).")
    st.markdown("## Recent news")
    try:
        news = fetch_news_rss(f"{item['label']} {item['name']} market news") or []
    except Exception:
        news = []
    if not news:
        st.caption("News unavailable.")
    for entry in news[:10]:
        if not isinstance(entry, dict) or not entry.get("title") or not entry.get("url"):
            continue
        title = html.escape(str(entry["title"]))
        url = html.escape(str(entry["url"]), quote=True)
        meta = " · ".join(part for part in (str(entry.get("date") or ""), str(entry.get("source") or "")) if part)
        st.markdown(f'<div class="md-news-item"><a href="{url}" target="_blank" rel="noopener">{title}</a><div class="md-news-meta">{html.escape(meta)}</div></div>', unsafe_allow_html=True)
    st.markdown("## Underlying breadth")
    breadth = info.get("breadth") or {}
    if not breadth.get("ready"):
        st.caption("Breadth unavailable — not enough constituent quotes were published to calculate it.")
    else:
        listed = int(breadth.get("listed") or 0)
        above = int(breadth.get("above50") or 0)
        highs = int(breadth.get("new_highs") or 0)
        above_pct = (above / listed * 100) if listed else 0
        high_pct = (highs / listed * 100) if listed else 0
        st.markdown(f"Above 50-day MA <span class='md-breadth-num' style='float:right'>{above} / {listed}</span>", unsafe_allow_html=True)
        st.markdown(f'<div class="md-gauge-track" style="height:10px"><div class="md-gauge-fill" style="width:{above_pct:.0f}%;background:#2563eb"></div></div>', unsafe_allow_html=True)
        st.markdown(f"New highs vs previous day <span class='md-breadth-num' style='float:right'>{highs} / {listed}</span>", unsafe_allow_html=True)
        st.markdown(f'<div class="md-gauge-track" style="height:10px"><div class="md-gauge-fill" style="width:{high_pct:.0f}%;background:#15803d"></div></div>', unsafe_allow_html=True)
        st.caption(f"Coverage: {breadth.get('measured')} of {listed} listed constituents measured. A constituent with no usable closes is left out of both counts.")
        top = breadth.get("top") or []
        if top:
            st.markdown("**Top weights**")
            st.caption("First constituents as listed by the source — index weights are not published by this source, so this is source order, not a weight ranking.")
            rows = []
            for entry in top:
                rows.append({"Constituent": entry.get("name") or entry.get("symbol"), ">50MA": "●" if entry.get("above50") else "○", "New high": "●" if entry.get("new_high") else "○"})
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    render_red_folder_list(calendar, index_id)


# ---------------------------------------------------------------------------
# Watchlist (spec 3.4)
# ---------------------------------------------------------------------------

def load_watchlist_cache(path: Path | None = None) -> dict:
    """Watchlist snapshots saved on this running app, or {} when none."""
    target = path or QUOTE_CACHE_PATH
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_watchlist_cache(payload: dict, path: Path | None = None) -> None:
    target = path or QUOTE_CACHE_PATH
    target.write_text(json.dumps(payload), encoding="utf-8")


def _hydrate_watchlist() -> None:
    if st.session_state.get("macro_hydrated"):
        return
    cached = load_watchlist_cache()
    st.session_state.macro_added = cached.get("added") or {}
    st.session_state.macro_hydrated = True


def _remember_watchlist() -> None:
    try:
        save_watchlist_cache({"added": st.session_state.get("macro_added") or {}})
    except OSError:
        st.warning("The new watchlist is showing, but it could not be saved for the next page load.")


def _watchlist_row(snapshot: dict) -> dict:
    """One watchlist row, with every spec column populated from the snapshot.

    50MA / 200MA come from the stored daily closes; weekly and daily
    trends are the spec's EMA50 trend on weekly-aggregated and daily
    closes. A missing input stays blank, never zero.
    """
    closes = [float(c) for c in (snapshot.get("closes") or []) if isinstance(c, (int, float)) and not isinstance(c, bool)]
    price = snapshot.get("price") if isinstance(snapshot.get("price"), (int, float)) else None
    target = snapshot.get("target") if isinstance(snapshot.get("target"), (int, float)) else None
    upside = (target / price - 1) * 100 if price and target and price > 0 else None
    forward_pe = snapshot.get("forwardPE") if isinstance(snapshot.get("forwardPE"), (int, float)) else None
    if forward_pe is None and price is not None and isinstance(snapshot.get("eps"), (int, float)) and snapshot.get("eps"):
        forward_pe = price / float(snapshot["eps"])
    average50 = sma(closes, 50)
    average200 = sma(closes, 200)
    weekly_closes = weekly_closes_from_daily(snapshot.get("closeDates") or [], closes)
    return {
        "ticker": snapshot.get("ticker"),
        "name": snapshot.get("name"),
        "parent": parent_index(str(snapshot.get("ticker") or "")),
        "price": price,
        "currency": snapshot.get("currency"),
        "target": target,
        "upside": upside,
        "above50": None if average50 is None or price is None else price > average50,
        "above200": None if average200 is None or price is None else price > average200,
        "weekly": trend_from_closes(weekly_closes, TREND_EMA_PERIOD),
        "daily": trend_from_closes(closes, TREND_EMA_PERIOD),
        "forward_pe": forward_pe,
    }


def _currency_symbol(currency: str | None) -> str:
    return {"USD": "$", "EUR": "€", "GBP": "£"}.get(currency or "", "$")


def _run_add_search(query: str) -> None:
    """One box: type a ticker (AAPL) or a company name (NVIDIA) to add it.

    A known ticker typed on its own is added straight away when the
    Yahoo symbol search returns it as an exact match. A company name
    has no exact symbol, so its matches are shown below the box to pick
    from. If the search returns nothing at all, a ticker-looking query
    falls back to the direct add path.
    """
    text = (query or "").strip()
    if not text:
        st.session_state.macro_search_results = None
        st.error("Enter a ticker or a company name to search.")
        return
    with st.spinner(f"Searching for {text}…"):
        try:
            results = search_symbols(text)
        except Exception as exc:
            results = []
            st.error(f"Search failed: {exc}")
    exact = [r for r in results if str(r.get("symbol") or "").upper() == text.upper()]
    if exact:
        st.session_state.macro_search_results = None
        _add_ticker(str(exact[0].get("symbol")))
        return
    if not results:
        try:
            normalize_ticker(text)
        except QuoteError:
            st.session_state.macro_search_results = []
            return
        st.session_state.macro_search_results = None
        _add_ticker(text)
        return
    st.session_state.macro_search_results = results


def _add_ticker(raw: str) -> None:
    try:
        ticker = normalize_ticker(raw)
    except QuoteError as exc:
        st.error(str(exc))
        return
    existing = set(st.session_state.get("macro_added") or {})
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
    st.session_state.macro_added[ticker] = snapshot
    _remember_watchlist()
    st.success(f"Added {ticker}. Blank fields were not published by the source.")


def _remove_ticker(ticker: str) -> None:
    added = dict(st.session_state.get("macro_added") or {})
    added.pop(ticker, None)
    st.session_state.macro_added = added
    _remember_watchlist()


def _render_watchlist() -> None:
    st.markdown("## Watchlist")
    query = st.text_input("Add a stock — search by ticker or company name", placeholder="NVDA, SAP, Shell…", key="macro_add_search")
    if st.button("Search", key="macro_add_search_button"):
        _run_add_search(query)
    results = st.session_state.get("macro_search_results") or []
    if results:
        options = [f"{r.get('symbol')} — {r.get('name')}" for r in results if r.get("symbol")]
        if options:
            chosen = st.selectbox("Search results", options=options, key="macro_add_search_results")
            if st.button("Add selected", key="macro_add_search_add"):
                _add_ticker(str(chosen).split(" — ")[0])
    elif st.session_state.get("macro_search_results") is not None:
        st.caption("No companies matched that search.")
    added = st.session_state.get("macro_added") or {}
    if not added:
        st.caption("Your watchlist is empty – search above to add a stock.")
        return
    rows = [_watchlist_row(snapshot) for snapshot in added.values()]
    rows.sort(key=lambda row: str(row.get("ticker") or ""))
    header = "<tr><th>Stock</th><th>Price</th><th>Analyst target</th><th>50MA</th><th>200MA</th><th>Weekly</th><th>Daily</th><th>Fwd P/E</th><th></th></tr>"
    body_rows: list[str] = []
    for row in rows:
        ticker = str(row.get("ticker") or "")
        symbol = _currency_symbol(row.get("currency"))
        price = _money(row.get("price"), symbol) or "—"
        if row.get("target") is not None:
            target = _money(row.get("target"), symbol) or "—"
            upside_text = _percent(row.get("upside"), 1, signed=True) or ""
            upside_class = "md-up" if (row.get("upside") or 0) >= 0 else "md-down"
            target_cell = f"{target}<br><span class='{upside_class}'>{html.escape(upside_text)}</span>"
        else:
            target_cell = "—"
        def above_below(value: bool | None) -> str:
            if value is None:
                return "—"
            return '<span class="md-up">Above</span>' if value else '<span class="md-down">Below</span>'
        def bull_bear(value: str | None) -> str:
            if value == "Bullish":
                return '<span class="md-up">Bullish</span>'
            if value == "Bearish":
                return '<span class="md-down">Bearish</span>'
            return "—"
        forward_pe = f"{row['forward_pe']:.1f}x" if isinstance(row.get("forward_pe"), (int, float)) else "n/m"
        parent = f" · {row['parent']}" if row.get("parent") else ""
        body_rows.append(
            f"<tr><td><a href='?stock={urllib.parse.quote(ticker)}' target='_self'><strong>{html.escape(ticker)}</strong></a><br>"
            f"{html.escape(str(row.get('name') or ''))}{html.escape(parent)}</td>"
            f"<td class='md-mono'>{price}</td><td class='md-mono'>{target_cell}</td>"
            f"<td>{above_below(row.get('above50'))}</td><td>{above_below(row.get('above200'))}</td>"
            f"<td>{bull_bear(row.get('weekly'))}</td><td>{bull_bear(row.get('daily'))}</td>"
            f"<td class='md-mono'>{forward_pe}</td><td></td></tr>"
        )
    st.markdown(MACRO_CSS + f'<div style="overflow-x:auto"><table class="md-watchlist">{header}{"".join(body_rows)}</table></div>', unsafe_allow_html=True)
    for row in rows:
        ticker = str(row.get("ticker") or "")
        if st.button("✕", key=f"macro_remove_{ticker}", help=f"Remove {ticker} from the watchlist"):
            _remove_ticker(ticker)
            st.rerun()
    st.caption("Click a stock to open its page. Or select an index above for its chart, news, red folder events and constituents.")


def _render_stock_placeholder(ticker: str) -> None:
    """Stock detail placeholder (spec 3.4) — design to be supplied later."""
    if st.button("← Back to the watchlist", key="macro_stock_back"):
        st.query_params.clear()
        st.rerun()
    added = st.session_state.get("macro_added") or {}
    snapshot = added.get(ticker.upper())
    st.markdown(f"## {html.escape(ticker.upper())}")
    if snapshot is not None:
        price = snapshot.get("price")
        st.write(f"Price: {_money(price, _currency_symbol(snapshot.get('currency'))) or '—'}")
        if snapshot.get("name"):
            st.write(str(snapshot["name"]))
    st.info("To be designed – coming soon")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _requested_index() -> str | None:
    value = st.query_params.get("index")
    if isinstance(value, list):
        value = value[0] if value else None
    if not isinstance(value, str) or not value.strip():
        return None
    wanted = value.strip().lower()
    return wanted if wanted in INDEX_BY_ID else None


def _requested_stock() -> str | None:
    value = st.query_params.get("stock")
    if isinstance(value, list):
        value = value[0] if value else None
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return normalize_ticker(value)
    except QuoteError:
        return None


def render_macro_desk() -> None:
    """Macro Desk home, index and stock pages. The top strip and the
    red-folder calendar are visible on every page (spec section 3)."""
    _hydrate_watchlist()
    if "macro_theme" not in st.session_state:
        st.session_state.macro_theme = "Light"
    theme = st.radio("Theme", options=["Light", "Dark"], index=0 if st.session_state.macro_theme == "Light" else 1, horizontal=True, key="macro_theme_radio")
    st.session_state.macro_theme = theme
    # The manual toggle only restyles this page's own cards and pills;
    # Streamlit's own chrome follows the system theme.
    if theme == "Dark":
        st.markdown("<style>.md-card{background:#1f2937;color:#f9fafb} .md-card a{color:#f9fafb} .md-pill.md-missing{color:#d1d5db}</style>", unsafe_allow_html=True)
    index_id = _requested_index()
    stock = _requested_stock()
    try:
        calendar = cached_red_folder()
    except Exception:
        calendar = {"events": [], "available": False, "partial": False}
    data = render_strip(active_id=index_id)
    render_event_detail()
    render_calendar(calendar, index_id=index_id)
    if stock is not None:
        _render_stock_placeholder(stock)
        return
    if index_id is not None:
        render_index_page(index_id, data, calendar)
        return
    _render_watchlist()
    st.caption(
        "Trend: Bullish if the latest close is above the 50-period EMA and the 50 EMA is rising, otherwise Bearish. "
        "Breadth and trends are recalculated at most every 5 minutes for indices and every 30 minutes for breadth. "
        "Red-folder events are high-impact only, from the Forex Factory calendar, in UK time. "
        "Watchlist names you add stay on this running app until it restarts; they are not written back to the repo."
    )


# Backwards-compatible name: app.py used to import render_research_desk.
render_research_desk = render_macro_desk
