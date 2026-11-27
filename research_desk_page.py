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
  analyst target + upside/downside, 50MA, 200MA, weekly, daily,
  forward P/E, and a sentiment score when one has been saved.
- A stock page: price and trend, imported sentiment, news, US insider
  filings from SEC Form 4, and a government-trades note.
- An index seasonality card from published daily closes, plus a
  sentiment card. X posts come only from a confirmed Grok import.

Live data comes from the same public providers the old desk used:
Yahoo Finance for prices/closes (``research_desk_quotes``), Forex
Factory's free weekly calendar JSON for red-folder events, Google News
RSS for index news, Stock Analysis for analyst targets / forward P/E.
A figure stays blank when its source does not publish it; nothing is
invented. There is no Thesis box, no CANSLIM, no spider and no
short-squeeze checks. US insider rows are SEC Form 4 filings. A
sentiment number is shown only after a confirmed import. Government
trades stay blank until a filings feed is connected.

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

from macro_desk_insights import (
    fetch_bluesky_posts,
    fetch_reddit_posts,
    score_texts,
    score_text,
    tone_of,
    auto_sentiment_view,
    fetch_insider_many,
    fetch_us_insider_trades,
    load_sec_cik_map,
    parse_grok_import,
    seasonality_from_candles,
    sec_symbol,
    sentiment_view,
)
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
.md-gauges { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; margin-top: 0.35rem; }
.md-gauge-label { display: block; font-size: 0.68rem; color: #666; line-height: 1.2; }
.md-gauge-num { display: block; font-family: 'DM Mono', monospace; font-weight: 500; font-size: 0.72rem; line-height: 1.2; white-space: nowrap; }
.md-gauge-track { height: 5px; border-radius: 3px; background: rgba(128,128,128,0.25); margin: 0.15rem 0 0; overflow: hidden; }
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
# Explicit Light / Dark themes.
#
# Bug fixed here (reported 2026-11-26): Light mode stayed dark. The old code
# had no explicit light theme at all — the base CSS above left cards
# transparent (``background: var(--md-card-bg, transparent)``) and only
# injected a dark card style when Dark was chosen, so on a device whose
# system theme is dark, Streamlit's own chrome stayed dark and Light
# mode looked dark too. The same bug was found in the standalone preview
# (no explicit light palette, toggle recomputed from matchMedia).
#
# Fix, mirroring the preview fix: BOTH themes now inject a full, explicit
# palette — page background, text, card background, muted text, pills —
# placed AFTER the base CSS above, so the chosen theme always wins over
# Streamlit's system theme. Light is genuinely light (pale background,
# white cards, dark text); Dark is genuinely dark. The toggle in
# render_macro_desk() swaps the explicit theme, it does not rely on the
# system preference. Streamlit runs the theme choice server-side, so there
# is no prefers-color-scheme detection here and no "before first paint"
# script as in the static preview — the explicit CSS is injected on every
# render of this page, which is the Streamlit equivalent. It is scoped to
# this page only (it is only injected by render_macro_desk() /
# _macro_css()); the Data Hub / Trading Edge page is untouched.
# ---------------------------------------------------------------------------
MACRO_THEME_CSS: dict[str, str] = {
    "Light": """
<style>
.stApp, [data-testid="stAppViewContainer"] { background: #f8fafc !important; color: #111827 !important; color-scheme: light; }
.stApp h1, .stApp h2, .stApp h3, [data-testid="stMarkdownContainer"] { color: #111827 !important; }
.md-card { background: #ffffff !important; color: #111827 !important; border-color: rgba(17,24,39,0.15) !important; }
.md-card a { color: #111827 !important; }
.md-gauge-label, .md-event-chip .md-event-meta, .md-news-meta { color: #4b5563 !important; }
.md-missing { background: rgba(107,114,128,0.15) !important; color: #4b5563 !important; }
.md-bull { background: rgba(21,128,61,0.12) !important; color: #15803d !important; }
.md-bear { background: rgba(180,35,24,0.10) !important; color: #b42318 !important; }
.md-up { color: #15803d !important; } .md-down { color: #b42318 !important; }
table.md-watchlist th, table.md-watchlist td { color: #111827 !important; }
.md-event-chip { color: #111827 !important; }
.md-hero, .md-hero h2, .md-hero .md-hero-price { color: #ffffff !important; }
</style>
""",
    "Dark": """
<style>
.stApp, [data-testid="stAppViewContainer"] { background: #0f172a !important; color: #f1f5f9 !important; color-scheme: dark; }
.stApp h1, .stApp h2, .stApp h3, [data-testid="stMarkdownContainer"] { color: #f1f5f9 !important; }
.md-card { background: #1e293b !important; color: #f1f5f9 !important; border-color: rgba(241,245,249,0.18) !important; }
.md-card a { color: #f1f5f9 !important; }
.md-gauge-label, .md-event-chip .md-event-meta, .md-news-meta { color: #cbd5e1 !important; }
.md-missing { background: rgba(148,163,184,0.18) !important; color: #cbd5e1 !important; }
.md-bull { background: rgba(74,222,128,0.16) !important; color: #4ade80 !important; }
.md-bear { background: rgba(248,113,113,0.16) !important; color: #f87171 !important; }
.md-up { color: #4ade80 !important; } .md-down { color: #f87171 !important; }
table.md-watchlist th, table.md-watchlist td { color: #f1f5f9 !important; }
.md-event-chip { color: #f1f5f9 !important; }
.md-hero, .md-hero h2, .md-hero .md-hero-price { color: #ffffff !important; }
</style>
""",
}


def _current_theme() -> str:
    """The theme chosen with the toggle; Light unless Dark was chosen."""
    try:
        theme = st.session_state.get("macro_theme", "Light")
    except Exception:
        return "Light"
    return "Dark" if theme == "Dark" else "Light"


def _normalize_theme(raw: object) -> str | None:
    """Pure helper: "dark"/"Dark" -> "Dark", "light" -> "Light", else None."""
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if not isinstance(raw, str):
        return None
    lowered = raw.strip().lower()
    if lowered == "dark":
        return "Dark"
    if lowered == "light":
        return "Light"
    return None


def _theme_query_value(theme: str | None) -> str:
    """Query-param spelling of a theme: "dark" for Dark, "light" otherwise."""
    return "dark" if theme == "Dark" else "light"


def _theme_from_query_params() -> str | None:
    """Theme carried in the URL (?theme=dark|light), if it is a valid one."""
    try:
        return _normalize_theme(st.query_params.get("theme"))
    except Exception:
        return None


def _set_theme_query_param(theme: str | None) -> None:
    """Write the chosen theme into the URL, so a full reload carries it."""
    try:
        value = _theme_query_value(theme)
        if _normalize_theme(st.query_params.get("theme")) != ("Dark" if value == "dark" else "Light"):
            st.query_params["theme"] = value
    except Exception:
        pass


def _sync_theme() -> str:
    """Adopt the theme from the URL if one is there, else keep the session
    choice, and write the result back into the URL.

    Bug fixed here (reported 2026-11-26): the theme used to live only in
    session state, so it reset to Light on every page change. Clicking a
    stock or an index card follows a plain <a href="?stock=..."> /
    "?index=..." anchor — a full browser reload that starts a new
    Streamlit session, and session state does not survive that. This is
    the Streamlit equivalent of the preview fix, where the theme travels
    in the page address: the choice is now also carried in a
    theme=dark|light query param, which survives a full reload, and every
    navigation link in this desk carries it (see _link_with_theme). The
    radio toggle still wins on its own rerun: _sync_theme() may adopt the
    old URL value first, but st.radio() then returns the widget's new
    value, which is written back into the URL below.
    """
    from_url = _theme_from_query_params()
    if from_url is not None:
        st.session_state.macro_theme = from_url
    theme = _current_theme()
    _set_theme_query_param(theme)
    return theme


def _link_with_theme(query: str) -> str:
    """A same-app link (?index=... / ?stock=...) that keeps the theme in
    the URL, so following it does not reset the desk to Light."""
    return f"?{query}&theme={_theme_query_value(_current_theme())}"


def _clear_macro_route() -> None:
    """Go back to the Macro Desk home, keeping the theme in the URL.

    Unlike st.query_params.clear(), which would wipe theme=... as well
    and reset the desk to Light on the next full reload, this removes
    only the route (index / stock) and keeps the theme param.
    """
    try:
        for key in ("index", "stock"):
            if key in st.query_params:
                del st.query_params[key]
    except Exception:
        pass
    _set_theme_query_param(_current_theme())


def _macro_css(theme: str | None = None) -> str:
    """Base CSS plus the explicit palette for the chosen theme, theme last
    so it always wins over the base rules and over Streamlit's system theme."""
    chosen = "Dark" if theme == "Dark" else "Light"
    return MACRO_CSS + MACRO_THEME_CSS[chosen]


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
        daily5 = fetch_candles(symbol, interval="1d", span="5y", getter=getter)
    except QuoteError:
        daily5 = daily
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
        "closes5y": [c["close"] for c in daily5],
        "dates5y": [c["date"] for c in daily5],
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


def session_extreme(last: dict | None, previous: dict | None) -> tuple[bool, bool]:
    """Whether this session made a new high or a new low versus the previous one.

    A new high is this session's high above the previous session's high.
    A new low is this session's low below the previous session's low.
    A missing price counts as neither. One session can be both.
    """

    def price(candle: dict | None, key: str) -> float | None:
        if not isinstance(candle, dict):
            return None
        value = candle.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    last_high, prev_high = price(last, "high"), price(previous, "high")
    last_low, prev_low = price(last, "low"), price(previous, "low")
    new_high = last_high is not None and prev_high is not None and last_high > prev_high
    new_low = last_low is not None and prev_low is not None and last_low < prev_low
    return new_high, new_low


def breadth_summary(index_id: str, per_symbol: list[dict | None]) -> dict:
    """Above-50MA, new-high and new-low counts.

    ``per_symbol`` is one entry per constituent: {"above50": bool|None,
    "new_high": bool|None, "new_low": bool|None} or None when that
    constituent published no usable closes. Missing constituents stay
    out of the counts.
    """
    above = highs = lows = measured = unknown = 0
    for item in per_symbol:
        if not item or item.get("above50") is None and item.get("new_high") is None and item.get("new_low") is None:
            unknown += 1
            continue
        measured += 1
        if item.get("above50"):
            above += 1
        if item.get("new_high"):
            highs += 1
        if item.get("new_low"):
            lows += 1
    listed = len(per_symbol)
    ready = listed > 0 and measured > 0 and measured * 2 >= listed
    return {
        "index_id": index_id,
        "listed": listed,
        "measured": measured,
        "unknown": unknown,
        "above50": above,
        "new_highs": highs,
        "new_lows": lows,
        "ready": ready,
    }


def load_macro_breadth(index_id: str, getter=None) -> dict:
    """Breadth for one index: above 50MA, new highs and new lows vs the previous day.

    Each constituent needs at least 51 daily closes for its 50-day SMA
    and the last two sessions' highs and lows. A constituent that does
    not publish them is left out of the counts.
    """
    symbols = cached_constituents(index_id).get("symbols") or []
    if not symbols:
        return {"index_id": index_id, "listed": 0, "measured": 0, "unknown": 0, "above50": 0, "new_highs": 0, "new_lows": 0, "ready": False, "top": []}
    get = getter or fetch_text

    def one(symbol: str) -> dict | None:
        try:
            candles = fetch_candles(symbol, interval="1d", span="6mo", getter=get)
        except Exception:
            return None
        closes = [float(c["close"]) for c in candles if isinstance(c.get("close"), (int, float)) and not isinstance(c.get("close"), bool)]
        if len(closes) < BREADTH_SMA_PERIOD + 1 or len(candles) < 2:
            return None
        average = sma(closes, BREADTH_SMA_PERIOD)
        if average is None:
            return None
        new_high, new_low = session_extreme(candles[-1], candles[-2])
        return {
            "symbol": symbol,
            "above50": closes[-1] > average,
            "new_high": new_high,
            "new_low": new_low,
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
        top.append({"name": names[position] if position < len(names) else item["symbol"], "symbol": item["symbol"], "above50": item["above50"], "new_high": item["new_high"], "new_low": item["new_low"]})
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

def _breadth_gauge(label: str, count: str, pct: float, colour: str, title: str) -> str:
    """One thin breadth gauge: label, count and a bar. A positive count keeps a visible sliver."""
    width = 0.0 if pct <= 0 else max(pct, 3.0)
    return (
        f'<div class="md-gauge" title="{html.escape(title)}">'
        f'<span class="md-gauge-label">{html.escape(label)}</span>'
        f'<span class="md-gauge-num">{html.escape(count)}</span>'
        f'<div class="md-gauge-track"><div class="md-gauge-fill" style="width:{width:.0f}%;background:{colour}"></div></div>'
        f"</div>"
    )


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
            lows = int(breadth.get("new_lows") or 0)
            above_pct = (above / listed * 100) if listed else 0
            high_pct = (highs / listed * 100) if listed else 0
            low_pct = (lows / listed * 100) if listed else 0
            above_colour = "#15803d" if above_pct >= 50 else "#b42318"
            gauges = (
                '<div class="md-gauges">'
                + _breadth_gauge("50MA", f"{above}/{listed}", above_pct, above_colour, "Constituents above their 50-day moving average")
                + _breadth_gauge("Highs", f"{highs}/{listed}", high_pct, "#2563eb", "Constituents making a new high vs the previous day")
                + _breadth_gauge("Lows", f"{lows}/{listed}", low_pct, "#b42318", "Constituents making a new low vs the previous day")
                + "</div>"
            )
        else:
            gauges = '<div class="md-gauge-label">Breadth unavailable — not enough constituent quotes published.</div>'
    active_class = " md-active" if active else ""
    href = _link_with_theme(f"index={item['id']}")
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
    st.markdown(f'<h1 class="md-title"><a href="?theme={_theme_query_value(_current_theme())}" target="_self" style="text-decoration:none;color:inherit">Macro Desk</a></h1>', unsafe_allow_html=True)
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
    st.markdown(_macro_css(_current_theme()) + '<div class="md-strip">' + "".join(_strip_card(item, data[item["id"]], active_id == item["id"]) for item in MACRO_INDICES) + "</div>", unsafe_allow_html=True)
    st.caption("50MA: constituents above their 50-day moving average. Highs: constituents whose current session high exceeds the previous session's high. Click a card to open that index.")
    return data


def _london_today() -> date:
    return datetime.now(LONDON).date()


@st.cache_data(ttl=3600, show_spinner=False)
def cached_seasonality(symbol: str, as_of: str) -> dict:
    """Three-year seasonality for one index, from Yahoo daily closes."""
    candles = fetch_candles(symbol, interval="1d", span="5y")
    return seasonality_from_candles(candles, date.fromisoformat(as_of))


@st.cache_data(ttl=86400, show_spinner=False)
def cached_cik_map() -> dict:
    """SEC ticker list, shared by every insider lookup on this app."""
    return load_sec_cik_map()


@st.cache_data(ttl=21600, show_spinner=False)
def cached_insider(ticker: str, as_of: str) -> dict:
    """Form 4 filings for one US ticker, cached for six hours."""
    return fetch_us_insider_trades(ticker, today=date.fromisoformat(as_of), cik_map=cached_cik_map())


@st.cache_data(ttl=21600, show_spinner=False)
def cached_insider_batch(tickers: tuple[str, ...], as_of: str) -> dict:
    """Form 4 flags for the whole watchlist, one shared SEC ticker list."""
    return fetch_insider_many(tickers, today=date.fromisoformat(as_of), cik_map=cached_cik_map())


@st.cache_data(ttl=1800, show_spinner=False)
def cached_bluesky(query: str) -> dict:
    """Public Bluesky posts for a search. No tone is added."""
    return fetch_bluesky_posts(query)


SHOW_X_SENTIMENT = False  # X is hidden until a way to feed it is chosen


def _secret(name: str) -> str | None:
    """A key from Streamlit secrets or the environment, or None."""
    try:
        value = st.secrets.get(name)
        if value:
            return str(value)
    except Exception:
        pass
    import os

    return os.environ.get(name) or None


@st.cache_data(ttl=1800, show_spinner=False)
def cached_news_titles(query: str) -> list[dict]:
    """Headlines for a search (Google News RSS), refreshed every 30 minutes."""
    return fetch_news_rss(query) or []


@st.cache_data(ttl=1800, show_spinner=False)
def cached_reddit(query: str, client_id: str | None, client_secret: str | None) -> dict:
    return fetch_reddit_posts(query, client_id, client_secret)


def _reddit_feed(search: str) -> dict:
    try:
        return cached_reddit(search, _secret("REDDIT_CLIENT_ID"), _secret("REDDIT_CLIENT_SECRET"))
    except Exception:
        return {"configured": True, "available": False, "posts": []}


def _bluesky_feed(search: str) -> dict:
    try:
        return cached_bluesky(search)
    except Exception:
        return {"available": False, "posts": []}


def _auto_history(subject: str) -> dict:
    return (st.session_state.get("macro_auto_sentiment") or {}).get(subject) or {}


def _sentiment_for(subject: str) -> dict:
    """Saved scores only (no network): used by the watchlist column."""
    return auto_sentiment_view(_auto_history(subject), _london_today())


def _live_sentiment(subject: str, news_query: str, social_query: str) -> dict:
    """Score today's headlines and Bluesky/Reddit posts, save the day, return the view.

    A source that is unavailable contributes nothing. The day is saved
    only when at least one source has items, and is kept for the 30-day line.
    """
    try:
        headlines = [str(n.get("title") or "") for n in cached_news_titles(news_query)]
    except Exception:
        headlines = []
    posts = [str(p.get("text") or "") for p in (_bluesky_feed(social_query).get("posts") or [])]
    posts += [str(p.get("text") or "") for p in (_reddit_feed(social_query).get("posts") or [])]
    news, social = score_texts(headlines), score_texts(posts)
    live = {"news": news["score"], "news_n": news["count"], "social": social["score"], "social_n": social["count"]}
    today = _london_today()
    if news["count"] or social["count"]:
        store = dict(st.session_state.get("macro_auto_sentiment") or {})
        days = dict(store.get(subject) or {})
        days[today.isoformat()] = live
        for old in sorted(days)[:-45]:
            days.pop(old, None)
        store[subject] = days
        if store != st.session_state.get("macro_auto_sentiment"):
            st.session_state.macro_auto_sentiment = store
            _remember_watchlist()
    view = auto_sentiment_view(_auto_history(subject), today, live)
    view["news_n"], view["social_n"] = news["count"], social["count"]
    return view


def _signed_points(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:+.0f}"


def _render_sentiment_card(subject: str, label: str, news_query: str | None = None, social_query: str | None = None) -> None:
    """Today's score from news headlines and Bluesky/Reddit posts, and the saved 30-day line."""
    view = _live_sentiment(subject, news_query or f"{label} stock market", social_query or label)
    st.markdown(f"**Sentiment — {html.escape(label)}**")
    if view["score"] is None:
        st.caption("No sentiment score yet today. A source needs at least 3 headlines or posts, and none of the feeds returned enough.")
    else:
        st.metric("Today", _signed_points(view["score"]))
        if view["label"]:
            st.write(f"{view['label']} · {_signed_points(view['change'])} versus 7 days ago.")
        elif view["change"] is None:
            st.caption("Not enough saved days for a 7-day change yet. That needs a score on each of the last 3 days and the 3 days a week earlier.")
        else:
            st.caption(f"{_signed_points(view['change'])} versus 7 days ago. Inside the quiet band, so it is not labelled improving or worsening.")
        if view["low_volume"]:
            only = "news" if view["social"] is None else "social posts"
            st.caption(f"Low volume. Only {only} had enough items, so this is that source on its own.")
        else:
            st.caption(f"News {_signed_points(view['news'])} · Social {_signed_points(view['social'])}. Combined is 60% news and 40% social.")
    if view["series"]:
        frame = pd.DataFrame(view["series"])
        frame["date"] = frame["date"].astype(str)
        st.line_chart(frame.set_index("date")[["combined"]], height=180)
        st.caption("Saved days only, from −100 to +100. A day this page was not opened is left out.")
    else:
        st.caption("No 30-day line yet. Each day this page is opened adds that day's point.")
    st.caption("A simple keyword score on headlines and posts, not a person or an AI model. It is rough and easy to fool. Sentiment is an input, not a recommendation to trade.")


def _post_line(author: str, text: str, link: str = "") -> None:
    tone = tone_of(score_text(text))
    st.markdown(f"**{html.escape(author)}** · {tone}")
    st.write(text)
    if link.startswith("https://"):
        st.markdown(f"[Open post]({link})")


def _render_social(subject: str, search: str) -> None:
    """Bluesky and Reddit posts, each with a keyword tone. X only when enabled."""
    st.markdown(f"**Social posts mentioning {html.escape(search)}**")
    options = ["All", "Bluesky", "Reddit"] + (["X"] if SHOW_X_SENTIMENT else [])
    choice = st.radio("Source", options, horizontal=True, key=f"macro_social_{subject}")
    if SHOW_X_SENTIMENT and choice in {"All", "X"}:
        latest = ((st.session_state.get("macro_sentiment") or {}).get(subject) or {})
        latest = latest[max(latest)] if latest else {}
        for post in (latest.get("posts") if isinstance(latest.get("posts"), list) else []):
            _post_line(str(post.get("author") or ""), str(post.get("text") or ""), str(post.get("link") or ""))
    if choice in {"All", "Bluesky"}:
        feed = _bluesky_feed(search)
        if not feed.get("available"):
            st.caption("Bluesky feed unavailable.")
        elif not feed.get("posts"):
            st.caption("No recent Bluesky posts for this search.")
        for post in feed.get("posts") or []:
            _post_line(str(post.get("author") or ""), str(post.get("text") or ""))
    if choice in {"All", "Reddit"}:
        feed = _reddit_feed(search)
        if not feed.get("configured"):
            st.caption("Reddit is off until REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET are added to the app's secrets (a free Reddit app, for non-commercial use).")
        elif not feed.get("available"):
            st.caption("Reddit feed unavailable.")
        elif not feed.get("posts"):
            st.caption("No recent Reddit posts for this search.")
        for post in feed.get("posts") or []:
            _post_line(f"{post.get('author')} · r/{post.get('subreddit')}", str(post.get("text") or ""), str(post.get("link") or ""))


def _news_html(entries: list[dict]) -> str:
    """Headlines with a thumbnail when the feed published one."""
    blocks: list[str] = []
    for entry in entries[:10]:
        if not isinstance(entry, dict) or not entry.get("title") or not entry.get("url"):
            continue
        title = html.escape(str(entry["title"]))
        url = html.escape(str(entry["url"]), quote=True)
        meta = " · ".join(part for part in (str(entry.get("date") or ""), str(entry.get("source") or "")) if part)
        image = entry.get("image") or entry.get("favicon")
        thumb = ""
        if isinstance(image, str) and image.startswith("https://"):
            safe = html.escape(image, quote=True)
            thumb = f'<img src="{safe}" alt="" width="48" height="48" style="object-fit:cover;border-radius:6px;flex:none">'
        blocks.append(
            f'<div class="md-news-item" style="display:flex;gap:0.6rem;align-items:flex-start">{thumb}'
            f'<div><a href="{url}" target="_blank" rel="noopener">{title}</a>'
            f'<div class="md-news-meta">{html.escape(meta)}</div></div></div>'
        )
    return "".join(blocks)


def _pct_text(value: float | None) -> str:
    if value is None:
        return "not published"
    return f"{value:+.1f}%"


def _render_seasonality(item: dict) -> None:
    """Year-to-date path for this year and the previous two, from daily closes."""
    st.markdown("### Seasonality — year to date vs previous years")
    as_of = _london_today().isoformat()
    try:
        report = cached_seasonality(item["symbol"], as_of)
    except Exception:
        st.caption("Seasonality unavailable. Yahoo did not publish enough daily closes.")
        return
    years = report["years"]
    summary = report["summary"]
    st.write(
        f"{item['name']} is {_pct_text(summary.get(str(years[0])))} so far in {years[0]}. "
        f"Same point in {years[1]}: {_pct_text(summary.get(str(years[1])))}. "
        f"In {years[2]}: {_pct_text(summary.get(str(years[2])))}."
    )
    chart = pd.DataFrame(report["chart"], index=report["labels"])
    st.line_chart(chart, height=260)
    st.caption("Each line is the percent change from that year's first published close. The current year stops at the latest close.")
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    rows = []
    for year in years:
        row: dict[str, object] = {"Year": str(year)}
        for month, value in zip(months, report["monthly"][str(year)]):
            row[month] = None if value is None else round(float(value), 1)
        rows.append(row)
    average_row: dict[str, object] = {"Year": report["average_label"]}
    for month, value in zip(months, report["average"]):
        average_row[month] = None if value is None else round(float(value), 1)
    rows.append(average_row)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    partial = months[int(report["partial_month"]) - 1]
    st.caption(f"{partial} {years[0]} is partial. Later months are blank. A blank cell means that close was not published.")


PRICE_RANGES = (("1M", 1), ("6M", 6), ("1Y", 12), ("3Y", 36))
CHART_HEIGHT = 340


def _yes_no(value: bool | None) -> str:
    """Plain Yes or No for the breadth table (never a dot)."""
    return "Yes" if value else "No"


def build_price_figure(dates: list, closes: list, theme: str = "Light", height: int = CHART_HEIGHT):
    """Five-year price line: fixed height, fixed-size end dot, range buttons.

    The line and dot sizes are in pixels, so they stay the same when the
    chart is zoomed. Scroll zooms the date axis, dragging pans it, and the
    1M / 6M / 1Y / 3Y / 5Y buttons jump to a range. Opens on one year.
    Returns None when there is nothing to draw.
    """
    import plotly.graph_objects as go

    pairs = []
    for when, close in zip(dates, closes):
        stamp = pd.to_datetime(when, errors="coerce")
        if pd.isna(stamp) or isinstance(close, bool) or not isinstance(close, (int, float)):
            continue
        pairs.append((stamp, float(close)))
    if len(pairs) < 2:
        return None
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    dark = theme == "Dark"
    text = "#f1f5f9" if dark else "#111827"
    grid = "rgba(241,245,249,0.12)" if dark else "rgba(17,24,39,0.10)"
    card = "#1e293b" if dark else "#ffffff"
    bull, bear = ("#4ade80", "#f87171") if dark else ("#15803d", "#b42318")
    year_ago = ys[max(0, len(ys) - 253)]
    color = bull if ys[-1] >= year_ago else bear
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", line=dict(color=color, width=2), hovertemplate="%{x|%a %d %b %Y}<br>%{y:,.1f}<extra></extra>", showlegend=False))
    fig.add_trace(go.Scatter(x=[xs[-1]], y=[ys[-1]], mode="markers", marker=dict(size=9, color=color, line=dict(color=card, width=2)), hoverinfo="skip", showlegend=False))
    buttons = [dict(count=months, label=label, step="month", stepmode="backward") for label, months in PRICE_RANGES]
    buttons.append(dict(label="5Y", step="all"))
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=8, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=text, family="DM Sans, sans-serif"),
        dragmode="pan",
        hovermode="x",
    )
    fig.update_xaxes(
        range=[xs[-1] - pd.DateOffset(years=1), xs[-1]],
        showgrid=False,
        rangeselector=dict(buttons=buttons, bgcolor=card, activecolor=grid, font=dict(color=text)),
    )
    fig.update_yaxes(side="right", showgrid=True, gridcolor=grid, zeroline=False, tickformat=",.0f", autorange=True, fixedrange=True)
    return fig


def _render_price_chart(info: dict, theme: str) -> None:
    """Five-year zoomable chart, with the old 60-session line as the fallback."""
    dates = info.get("dates5y") or []
    closes = info.get("closes5y") or []
    fig = None
    if closes and len(dates) == len(closes):
        try:
            fig = build_price_figure(dates, closes, theme)
        except ImportError:
            fig = None
    if fig is not None:
        st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": True, "displaylogo": False, "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d"]}, key="macro_price_chart")
        st.caption("Scroll to zoom, drag to pan, or use the 1M to 5Y buttons. The line and dot stay the same size.")
        return
    short = info.get("closes60") or []
    short_dates = info.get("dates60") or []
    if short:
        chart = pd.DataFrame({"Close": short}, index=short_dates if len(short_dates) == len(short) else None)
        st.line_chart(chart, height=CHART_HEIGHT)
    else:
        st.caption("Price chart unavailable — no daily closes were published.")


def render_index_page(index_id: str, data: dict, calendar: dict | None) -> None:
    """One index on one page: hero, 5-year chart, sentiment and posts, seasonality, then news beside breadth. The red folder calendar stays at the top only."""
    item = INDEX_BY_ID[index_id]
    info = data.get(index_id) or {}
    if st.button("← Back to Macro Desk", key="macro_index_back"):
        _clear_macro_route()
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
    st.markdown("**Price — 5 years**")
    _render_price_chart(info, _current_theme())
    st.markdown(
        '<div class="md-pills">' + _pill("Weekly", info.get("weekly_trend")) + _pill("Daily", info.get("daily_trend")) + _pill("4H", info.get("four_hour_trend")) + "</div>",
        unsafe_allow_html=True,
    )
    st.caption("Trend: Bullish if the latest close is above the 50-period EMA and the 50 EMA is rising, otherwise Bearish (spec section 4).")
    left, right = st.columns(2)
    with left:
        _render_sentiment_card(index_id, item["label"], f"{item['label']} {item['name']} market news", item["label"])
    with right:
        _render_social(index_id, item["label"])
    _render_seasonality(item)
    news_col, breadth_col = st.columns(2)
    with news_col:
        st.markdown("## Recent news")
        try:
            news = fetch_news_rss(f"{item['label']} {item['name']} market news") or []
        except Exception:
            news = []
        if not news:
            st.caption("News unavailable.")
        else:
            st.markdown(_news_html(news), unsafe_allow_html=True)
            st.caption("Headlines come from the public news feed. A sentiment tag is not shown, because no news-score source is connected.")
    with breadth_col:
        st.markdown("## Underlying breadth")
        breadth = info.get("breadth") or {}
        if not breadth.get("ready"):
            st.caption("Breadth unavailable — not enough constituent quotes were published to calculate it.")
        else:
            listed = int(breadth.get("listed") or 0)
            above = int(breadth.get("above50") or 0)
            highs = int(breadth.get("new_highs") or 0)
            lows = int(breadth.get("new_lows") or 0)
            above_pct = (above / listed * 100) if listed else 0
            high_pct = (highs / listed * 100) if listed else 0
            low_pct = (lows / listed * 100) if listed else 0
            st.markdown(f"Above 50-day MA <span class='md-breadth-num' style='float:right'>{above} / {listed}</span>", unsafe_allow_html=True)
            st.markdown(f'<div class="md-gauge-track" style="height:10px"><div class="md-gauge-fill" style="width:{above_pct:.0f}%;background:#2563eb"></div></div>', unsafe_allow_html=True)
            st.markdown(f"New highs vs previous day <span class='md-breadth-num' style='float:right'>{highs} / {listed}</span>", unsafe_allow_html=True)
            st.markdown(f'<div class="md-gauge-track" style="height:10px"><div class="md-gauge-fill" style="width:{high_pct:.0f}%;background:#15803d"></div></div>', unsafe_allow_html=True)
            st.markdown(f"New lows vs previous day <span class='md-breadth-num' style='float:right'>{lows} / {listed}</span>", unsafe_allow_html=True)
            st.markdown(f'<div class="md-gauge-track" style="height:10px"><div class="md-gauge-fill" style="width:{low_pct:.0f}%;background:#b42318"></div></div>', unsafe_allow_html=True)
            st.caption(f"Coverage: {breadth.get('measured')} of {listed} listed constituents measured. A constituent with no usable closes is left out of the counts.")
            top = breadth.get("top") or []
            if top:
                st.markdown("**Top weights**")
                st.caption("First constituents as listed by the source — index weights are not published by this source, so this is source order, not a weight ranking.")
                rows = []
                for entry in top:
                    rows.append({
                        "Constituent": entry.get("name") or entry.get("symbol"),
                        ">50MA?": _yes_no(entry.get("above50")),
                        "New high?": _yes_no(entry.get("new_high")),
                        "New low?": _yes_no(entry.get("new_low")),
                    })
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


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
    st.session_state.macro_sentiment = cached.get("sentiment") if isinstance(cached.get("sentiment"), dict) else {}
    st.session_state.macro_auto_sentiment = cached.get("auto_sentiment") if isinstance(cached.get("auto_sentiment"), dict) else {}
    st.session_state.macro_hydrated = True


def _remember_watchlist() -> None:
    try:
        save_watchlist_cache({
            "added": st.session_state.get("macro_added") or {},
            "sentiment": st.session_state.get("macro_sentiment") or {},
            "auto_sentiment": st.session_state.get("macro_auto_sentiment") or {},
        })
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


try:
    from streamlit_searchbox import st_searchbox
except Exception:  # the plain search box below is the fallback
    st_searchbox = None


def _suggest_symbols(query: str) -> list[tuple[str, str]]:
    """Suggestions for the one search box: (label shown, ticker returned)."""
    text = (query or "").strip()
    if len(text) < 2:
        return []
    try:
        results = search_symbols(text)
    except Exception:
        return []
    options = []
    for r in results:
        symbol = str(r.get("symbol") or "").strip()
        if symbol:
            name = str(r.get("name") or "").strip()
            options.append((f"{symbol} — {name}" if name else symbol, symbol))
    return options[:8]


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
    if st_searchbox is not None:
        picked = st_searchbox(
            _suggest_symbols,
            placeholder="Add a stock — start typing a name or ticker, e.g. Nvid",
            key="macro_add_box",
            clear_on_submit=True,
        )
        if picked and picked != st.session_state.get("macro_last_picked"):
            st.session_state.macro_last_picked = picked
            _add_ticker(str(picked))
        elif not picked:
            st.session_state.macro_last_picked = None
    else:
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
        if SHOW_X_SENTIMENT:
            _render_x_import()
        return
    rows = [_watchlist_row(snapshot) for snapshot in added.values()]
    rows.sort(key=lambda row: str(row.get("ticker") or ""))
    us_tickers = tuple(sorted({str(row.get("ticker") or "") for row in rows if sec_symbol(str(row.get("ticker") or ""))}))
    try:
        insider_by_ticker = cached_insider_batch(us_tickers, _london_today().isoformat()) if us_tickers else {}
    except Exception:
        insider_by_ticker = {}
    header = "<tr><th>Stock</th><th>Price</th><th>Analyst target</th><th>50MA</th><th>200MA</th><th>Weekly</th><th>Daily</th><th>Fwd P/E</th><th>Sentiment</th><th></th></tr>"
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
        forward_value = row.get("forward_pe")
        forward_pe = f"{forward_value:.1f}x" if isinstance(forward_value, (int, float)) and forward_value > 0 else "n/m"
        parent = f" · {row['parent']}" if row.get("parent") else ""
        sentiment_view_row = _sentiment_for(ticker)  # saved days only; fills in when the stock or index page is opened
        if sentiment_view_row["score"] is None:
            sentiment_cell = "—"
        else:
            sentiment_cell = _signed_points(sentiment_view_row["score"])
            if sentiment_view_row["change"] is not None:
                arrow = "▲" if sentiment_view_row["change"] >= 0 else "▼"
                sentiment_cell += f" {arrow} {abs(sentiment_view_row['change']):.0f}"
        buying = ""
        filing = insider_by_ticker.get(ticker) or {}
        if (filing.get("summary") or {}).get("insider_buying"):
            buying = "<br><span class='md-up'>Insider buying</span>"
        stock_href = _link_with_theme("stock=" + urllib.parse.quote(ticker))
        body_rows.append(
            f"<tr><td><a href='{stock_href}' target='_self'><strong>{html.escape(ticker)}</strong></a><br>"
            f"{html.escape(str(row.get('name') or ''))}{html.escape(parent)}{buying}</td>"
            f"<td class='md-mono'>{price}</td><td class='md-mono'>{target_cell}</td>"
            f"<td>{above_below(row.get('above50'))}</td><td>{above_below(row.get('above200'))}</td>"
            f"<td>{bull_bear(row.get('weekly'))}</td><td>{bull_bear(row.get('daily'))}</td>"
            f"<td class='md-mono'>{forward_pe}</td><td class='md-mono'>{html.escape(sentiment_cell)}</td><td></td></tr>"
        )
    st.markdown(_macro_css(_current_theme()) + f'<div style="overflow-x:auto"><table class="md-watchlist">{header}{"".join(body_rows)}</table></div>', unsafe_allow_html=True)
    for row in rows:
        ticker = str(row.get("ticker") or "")
        if st.button("✕", key=f"macro_remove_{ticker}", help=f"Remove {ticker} from the watchlist"):
            _remove_ticker(ticker)
            st.rerun()
    st.caption("Click a stock to open its page. Or select an index above for its chart, news, red folder events and constituents.")
    if SHOW_X_SENTIMENT:
        _render_x_import()


def _import_aliases() -> dict[str, str]:
    """Watchlist tickers and company names the pasted import is allowed to name."""
    aliases: dict[str, str] = {}
    for ticker, snapshot in (st.session_state.get("macro_added") or {}).items():
        symbol = str(ticker)
        aliases[symbol.lower()] = symbol
        name = str((snapshot or {}).get("name") or "").strip().lower()
        if name:
            aliases[name] = symbol
    return aliases


def _grok_prompt() -> str:
    names = ["DAX", "UK100", "US100", "US30", "US500", *list((st.session_state.get("macro_added") or {}).keys())]
    return (
        "For each of these: " + ", ".join(names) + ".\n"
        "Look at X posts from the last 24 hours that mention it. Reply in exactly this format, one block per item, with nothing else:\n"
        "SUBJECT: the name exactly as I gave it\n"
        "TONE: bullish, neutral or bearish\n"
        "SCORE: whole number from -100 (very bearish) to 100 (very bullish)\n"
        "SUMMARY: one sentence on what is driving the mood\n"
        "POST: @handle | bullish, neutral or bearish | exact post text | link\n"
        "(3 to 5 POST lines, real posts only)\n"
        "---"
    )


def _render_x_import() -> None:
    """Paste a Grok answer, review the parse, then save it for today."""
    st.markdown("### Import X sentiment from Grok")
    st.caption("Give Grok the prompt, paste its answer, and check the table before saving. The desk files each block under the subject Grok named. It does not call an AI service.")
    st.code(_grok_prompt(), language=None)
    pasted = st.text_area("Grok’s answer", placeholder="Paste Grok’s answer here", key="macro_grok_paste")
    if st.button("Read answer", key="macro_grok_read"):
        st.session_state.macro_import_preview = parse_grok_import(pasted, _import_aliases())
    preview = st.session_state.get("macro_import_preview")
    if not isinstance(preview, dict):
        return
    items = preview.get("items") or []
    unknown = preview.get("unknown") or []
    if not items:
        st.caption("Nothing in the expected format was found. Check that Grok kept the SUBJECT, TONE and SCORE lines." + (f" Not recognised, so skipped: {', '.join(unknown)}." if unknown else ""))
        return
    st.caption(f"{len(items)} found." + (f" Not recognised, so skipped: {', '.join(unknown)}." if unknown else ""))
    st.dataframe(
        pd.DataFrame([
            {"Filed under": item["subject"], "Tone": item["tone"], "Score": item["score"], "Posts": len(item["posts"]), "Summary": item["summary"]}
            for item in items
        ]),
        hide_index=True,
        width="stretch",
    )
    if st.button("Save to the desk", key="macro_grok_save"):
        store = dict(st.session_state.get("macro_sentiment") or {})
        day = _london_today().isoformat()
        for item in items:
            days = dict(store.get(item["subject"]) or {})
            days[day] = {"score": item["score"], "tone": item["tone"], "summary": item["summary"], "posts": item["posts"]}
            store[item["subject"]] = days
        st.session_state.macro_sentiment = store
        st.session_state.macro_import_preview = None
        _remember_watchlist()
        st.success("Saved. Open that index or stock to see it in the sentiment card and the X tab.")


def _tone_pill(value: str | None) -> str:
    if value == "Bullish":
        return '<span class="md-up">Bullish</span>'
    if value == "Bearish":
        return '<span class="md-down">Bearish</span>'
    return "—"


def _above_pill(value: bool | None, label: str) -> str:
    if value is None:
        return label
    word = "Above" if value else "Below"
    colour = "md-up" if value else "md-down"
    return f'<span class="{colour}">{word}</span> {label}'


def _render_insider_block(ticker: str) -> None:
    st.markdown("### Insider transactions")
    st.caption("Last 30 days. US listings use SEC Form 4. An open-market buy is code P. Awards and option exercises stay marked other. The trade date and the filing date are both shown.")
    if sec_symbol(ticker) is None:
        st.caption("Director dealings for this listing are not connected. US stocks are the ones read from SEC Form 4.")
        return
    try:
        filing = cached_insider(ticker, _london_today().isoformat())
    except Exception:
        st.caption("SEC Form 4 filings could not be read for this ticker.")
        return
    if not filing.get("available"):
        st.caption("SEC Form 4 filings could not be read for this ticker.")
        return
    summary = filing.get("summary") or {}
    trades = summary.get("trades") or []
    if not trades:
        st.caption("No Form 4 transactions in the last 30 days were published.")
        return
    net = summary.get("net_value")
    if isinstance(net, (int, float)):
        if net > 0:
            label = "Net buying"
        elif net < 0:
            label = "Net selling"
        else:
            label = "Flat"
        st.write(f"{label}: {_money(abs(net)) or '—'}")
    else:
        st.caption("A net value is not shown, because one or more filings did not publish a price.")
    body = []
    for trade in trades:
        kind = {"buy": "Buy", "sell": "Sell"}.get(str(trade.get("type")), "Other")
        body.append(
            "<tr>"
            f"<td>{html.escape(str(trade.get('traded_at') or '—'))}</td>"
            f"<td>{html.escape(str(trade.get('filed_at') or '—'))}</td>"
            f"<td>{html.escape(str(trade.get('person') or '—'))}</td>"
            f"<td>{html.escape(str(trade.get('role') or '—'))}</td>"
            f"<td>{html.escape(kind)}</td>"
            f"<td class='md-mono'>{html.escape(_money(trade.get('value')) or '—')}</td>"
            "</tr>"
        )
    header = "<tr><th>Traded</th><th>Filed</th><th>Insider</th><th>Role</th><th>Type</th><th>Value</th></tr>"
    st.markdown(
        _macro_css(_current_theme()) + f'<div style="overflow-x:auto"><table class="md-watchlist">{header}{"".join(body)}</table></div>',
        unsafe_allow_html=True,
    )


def _render_government_block(ticker: str) -> None:
    st.markdown("### Government officials’ trades")
    if sec_symbol(ticker) is not None:
        st.caption("US officials’ trades are disclosed in value ranges, often days to weeks after the trade. No filings feed is connected, so this table stays empty rather than showing sample names.")
        return
    st.caption("US officials’ trades are only disclosed for US-listed stocks. Other countries publish interests differently, and this desk does not show those as trades.")


def _render_stock_page(ticker: str) -> None:
    """One watchlist stock: price, sentiment, news, insider filings."""
    if st.button("← Back to the watchlist", key="macro_stock_back"):
        _clear_macro_route()
        st.rerun()
    added = st.session_state.get("macro_added") or {}
    snapshot = added.get(ticker)
    if snapshot is None:
        st.warning(f"{ticker} is not on the watchlist.")
        return
    row = _watchlist_row(snapshot)
    parent = INDEX_BY_LABEL.get(str(row.get("parent") or ""))
    if parent is not None:
        st.markdown(f"[Open {parent['label']}]({_link_with_theme('index=' + parent['id'])})")
    symbol = _currency_symbol(row.get("currency"))
    price = _money(row.get("price"), symbol) or "—"
    target = _money(row.get("target"), symbol) or "—"
    upside = _percent(row.get("upside"), 1, signed=True) or "—"
    forward_value = row.get("forward_pe")
    forward = f"{forward_value:.1f}x" if isinstance(forward_value, (int, float)) and forward_value > 0 else "n/m"
    gradient = parent["gradient"] if parent else "linear-gradient(100deg,#334155,#64748b)"
    name = html.escape(str(row.get("name") or ticker))
    st.markdown(
        f'<div class="md-hero" style="background:{gradient}">'
        f"<h2>{name} ({html.escape(ticker)})</h2>"
        f'<div class="md-hero-price">{html.escape(price)} · analyst target {html.escape(target)} ({html.escape(upside)}) · fwd P/E {html.escape(forward)}</div>'
        f'<div class="md-pills">{_above_pill(row.get("above50"), "50MA")} {_above_pill(row.get("above200"), "200MA")} {_tone_pill(row.get("weekly"))} Weekly {_tone_pill(row.get("daily"))} Daily</div>'
        f"</div>",
        unsafe_allow_html=True,
    )
    left, right = st.columns(2)
    with left:
        _render_sentiment_card(ticker, ticker, f"{ticker} {row.get('name') or ''} stock", "$" + ticker)
    with right:
        _render_social(ticker, "$" + ticker)
    st.markdown("### Recent news")
    try:
        news = fetch_news_rss(f"{ticker} {row.get('name') or ''} stock") or []
    except Exception:
        news = []
    if news:
        st.markdown(_news_html(news), unsafe_allow_html=True)
        st.caption("Headlines come from the public news feed. A sentiment tag is not shown, because no news-score source is connected.")
    else:
        st.caption("News unavailable.")
    _render_insider_block(ticker)
    _render_government_block(ticker)


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
    # Theme persistence: _sync_theme() adopts theme=dark|light from the
    # URL when present (see _sync_theme for why session state alone is
    # not enough — navigation links are full reloads). The radio toggle
    # below then returns the widget's value, which wins and is written
    # back into the URL so the next page change carries it.
    _sync_theme()
    theme = st.radio("Theme", options=["Light", "Dark"], index=0 if _current_theme() == "Light" else 1, horizontal=True, key="macro_theme_radio")
    st.session_state.macro_theme = theme
    _set_theme_query_param(theme)
    # Both themes inject a full explicit palette (see MACRO_THEME_CSS):
    # Light used to inject nothing, so on a dark-system device Streamlit's
    # dark chrome showed through and Light mode looked dark. The chosen
    # theme now always wins over the system theme, for this page only.
    # Streamlit's sidebar / chrome still follows the system theme.
    st.markdown(MACRO_THEME_CSS[theme], unsafe_allow_html=True)
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
        _render_stock_page(stock)
        return
    if index_id is not None:
        render_index_page(index_id, data, calendar)
        return
    _render_watchlist()
    st.caption(
        "Trend: Bullish if the latest close is above the 50-period EMA and the 50 EMA is rising, otherwise Bearish. "
        "Breadth and trends are recalculated at most every 5 minutes for indices and every 30 minutes for breadth. "
        "Red-folder events are high-impact only, from the Forex Factory calendar, in UK time. "
        "Watchlist names you add, and X sentiment you save, stay on this running app until it restarts. They are not written back to the repo. "
        "Sentiment is an input, not a recommendation to trade."
    )


# Backwards-compatible name: app.py used to import render_research_desk.
render_research_desk = render_macro_desk
