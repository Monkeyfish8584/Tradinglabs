"""Fetch a new watchlist name from the same public pages the research desk uses.

Yahoo Finance supplies the quote and daily closes. Stock Analysis supplies the
valuation and short-interest statistics when that page publishes them. A missing
field stays missing. Nothing here is estimated.
"""

from __future__ import annotations

import copy
import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

UA = "Mozilla/5.0 (compatible; ResearchDesk/1.0)"
TICKER_RE = re.compile(r"^[A-Z0-9^][A-Z0-9.^=-]{0,14}$")
_SUFFIX = {"T": 1e12, "B": 1e9, "M": 1e6, "K": 1e3}
_MARKETS = {"DE": "etr", "MC": "bme", "PA": "epa"}


class QuoteError(ValueError):
    """A ticker could not be added. The message is safe to show on the page."""


def normalize_ticker(raw: str) -> str:
    ticker = (raw or "").strip().upper()
    if not TICKER_RE.fullmatch(ticker):
        raise QuoteError("Enter a Yahoo symbol such as AAPL, using letters, numbers, and . ^ = -.")
    return ticker


def number_value(raw: str | None) -> float | None:
    """Same reading rules as research-desk/lib/parsing.ts ``numberValue``."""
    if raw is None:
        return None
    text = raw.strip()
    if not text or re.fullmatch(r"n/a|--|—|-", text, flags=re.IGNORECASE):
        return None
    cleaned = re.sub(r"[$,%+\s]", "", text)
    match = re.fullmatch(r"(-?[\d.]+)([TBMK])?", cleaned, flags=re.IGNORECASE)
    if not match:
        return None
    suffix = _SUFFIX.get((match.group(2) or "").upper(), 1)
    try:
        value = float(match.group(1)) * suffix
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    return value


def _text_only(raw: str) -> str:
    text = re.sub(r"<!--[\s\S]*?-->", "", raw)
    text = re.sub(r"<[^>]*>", " ", text)
    for src, dst in (
        ("&amp;", "&"),
        ("&nbsp;", " "),
        ("&#160;", " "),
        ("&#39;", "'"),
        ("&apos;", "'"),
        ("&quot;", '"'),
    ):
        text = text.replace(src, dst)
    return re.sub(r"\s+", " ", text).strip()


def table_rows(html: str) -> list[list[dict[str, str]]]:
    """Same row split as research-desk/lib/parsing.ts ``tableRows``."""
    cleaned = re.sub(r"<!--[\s\S]*?-->", "", html)
    rows: list[list[dict[str, str]]] = []
    for row in re.finditer(r"<tr\b[^>]*>([\s\S]*?)</tr>", cleaned, flags=re.IGNORECASE):
        cells = []
        for cell in re.finditer(r"<t[dh]\b([^>]*)>([\s\S]*?)</t[dh]>", row.group(1), flags=re.IGNORECASE):
            cells.append({"text": _text_only(cell.group(2)), "raw": cell.group(1) + ">" + cell.group(2)})
        if cells:
            rows.append(cells)
    return rows


def _cell_number(cell: dict[str, str] | None) -> float | None:
    if not cell:
        return None
    titled = re.search(r'title="([^"]+)"', cell.get("raw") or "")
    if titled:
        value = number_value(titled.group(1))
        if value is not None:
            return value
    return number_value(cell.get("text"))


def parse_statistics_html(html: str) -> dict:
    rows = table_rows(html)
    values = {row[0]["text"].strip(): row[1] for row in rows if len(row) == 2}
    if "Market Cap" not in values or "Shares Outstanding" not in values:
        raise RuntimeError("Statistics not available for this ticker")

    def val(*labels: str) -> float | None:
        for label in labels:
            if label in values:
                return _cell_number(values[label])
        return None

    consensus = values.get("Analyst Consensus")
    earnings = values.get("Earnings Date")
    return {
        "marketCap": val("Market Cap"),
        "target": val("Price Target"),
        "eps": val("Earnings Per Share (EPS)", "Earnings Per Share", "Loss Per Share"),
        "forwardPE": val("Forward PE"),
        "analystCount": val("Analyst Count"),
        "consensus": None if consensus is None else consensus["text"],
        "epsGrowth": val("EPS Growth Forecast (3Y)"),
        "float": val("Float"),
        "sharesOutstanding": val("Shares Outstanding"),
        "shortShares": val("Short Interest"),
        "shortPrevious": val("Short Previous Month"),
        "shortFloatPct": val("Short % of Float"),
        "daysToCover": val("Short Ratio (days to cover)"),
        "averageVolume": val("Average Volume (20 Days)"),
        "earningsDate": None if earnings is None else earnings["text"],
        "revenue": val("Revenue"),
        "freeCashFlow": val("Free Cash Flow"),
        "cash": val("Cash & Cash Equivalents"),
        "totalDebt": val("Total Debt"),
        "shareChangeYoY": val("Shares Change (YoY)"),
        "institutionalPct": val("Owned by Institutions (%)"),
    }


def parse_forecast_html(html: str) -> dict:
    rows = table_rows(html)
    header = next((i for i, row in enumerate(rows) if row and row[0]["text"] == "Target" and len(row) > 2 and row[1]["text"] == "Low" and row[2]["text"] == "Average"), -1)
    if header < 0 or header + 1 >= len(rows):
        raise RuntimeError("Analyst target range unavailable")
    row = rows[header + 1]
    if not row or row[0]["text"] != "Price" or len(row) < 5:
        raise RuntimeError("Analyst target range unavailable")
    return {
        "targetLow": _cell_number(row[1]),
        "target": _cell_number(row[2]),
        "targetMedian": _cell_number(row[3]),
        "targetHigh": _cell_number(row[4]),
    }


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def parse_yahoo_chart(body: str, ticker: str) -> dict:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Ticker not found or quote unavailable") from exc
    result = (payload.get("chart") or {}).get("result") or []
    chart = result[0] if result else None
    meta = (chart or {}).get("meta") or {}
    price = _finite(meta.get("regularMarketPrice"))
    if not chart or price is None:
        raise RuntimeError("Ticker not found or quote unavailable")
    quote = ((chart.get("indicators") or {}).get("quote") or [{}])[0]
    closes_raw = quote.get("close") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    volumes = quote.get("volume") or []
    points = []
    for index, stamp in enumerate(chart.get("timestamp") or []):
        close = _finite(closes_raw[index] if index < len(closes_raw) else None)
        if close is None:
            continue
        high = _finite(highs[index] if index < len(highs) else None)
        low = _finite(lows[index] if index < len(lows) else None)
        volume = _finite(volumes[index] if index < len(volumes) else None)
        when = datetime.fromtimestamp(int(stamp), timezone.utc).date().isoformat()
        points.append({"date": when, "close": close, "high": high if high is not None else close, "low": low if low is not None else close, "volume": volume})
    recent = points[-520:]
    volume_window = [point["volume"] for point in points[-21:-1] if point["volume"] is not None]
    average_volume = sum(volume_window) / len(volume_window) if len(volume_window) >= 10 else None
    change = _finite(meta.get("regularMarketChangePercent"))
    if change is None and len(points) > 1 and points[-2]["close"] > 0:
        change = (price / points[-2]["close"] - 1) * 100
    quote_at = None
    if _finite(meta.get("regularMarketTime")) is not None:
        quote_at = datetime.fromtimestamp(int(meta["regularMarketTime"]), timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    parsed = {
        "name": meta.get("longName") or meta.get("shortName") or ticker,
        "currency": meta.get("currency"),
        "exchange": meta.get("exchangeName"),
        "instrumentType": meta.get("instrumentType"),
        "price": price,
        "changePct": change,
        "quoteAt": quote_at,
        "high52": _finite(meta.get("fiftyTwoWeekHigh")),
        "low52": _finite(meta.get("fiftyTwoWeekLow")),
        "volume": _finite(meta.get("regularMarketVolume")),
        "closes": [point["close"] for point in recent],
        "closeDates": [point["date"] for point in recent],
    }
    if average_volume is not None:
        parsed["averageVolume"] = average_volume
    return parsed


def fetch_text(url: str, timeout: int = 16) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise RuntimeError("Provider rate limit; try again later") from exc
        if exc.code == 403:
            raise RuntimeError("Provider blocked this request") from exc
        raise RuntimeError(f"Provider returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("Feed could not be reached; try again later") from exc
    if len(body) < 100:
        raise RuntimeError("Provider returned an incomplete response")
    return body


def _equity_base(ticker: str) -> str:
    foreign = re.fullmatch(r"(.+)\.(DE|MC|PA)", ticker)
    if foreign:
        return f"https://stockanalysis.com/quote/{_MARKETS[foreign.group(2)]}/{urllib.parse.quote(foreign.group(1))}"
    return f"https://stockanalysis.com/stocks/{urllib.parse.quote(ticker.lower())}"


def _apply_source(snapshot: dict, key: str, name: str, url: str, parser, getter) -> None:
    now = snapshot["attemptedAt"]
    try:
        parsed = parser(getter(url))
    except Exception as exc:
        message = str(exc).strip() or "Source unavailable"
        if re.search(r"internal error|fetch failed|network|connection|timeout|aborted", message, flags=re.IGNORECASE):
            message = "Feed could not be reached; try again later"
        snapshot["sources"][key] = {"name": name, "url": url, "error": message[:180]}
        return
    for field, value in parsed.items():
        if value is not None:
            snapshot[field] = value
    snapshot["sources"][key] = {"name": name, "url": url, "fetchedAt": now}


def yahoo_chart_url(ticker: str, span: str = "2y") -> str:
    return f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?interval=1d&range={span}"


def fetch_trend_snapshot(raw: str, getter=None, span: str = "6mo") -> dict:
    """Daily closes for one symbol. Raises QuoteError when Yahoo does not return a price."""
    ticker = normalize_ticker(raw)
    get = getter or fetch_text
    quote_url = yahoo_chart_url(ticker, span)
    try:
        parsed = parse_yahoo_chart(get(quote_url), ticker)
    except Exception as exc:
        message = str(exc).strip()
        if message.startswith("Provider") or message.startswith("Feed"):
            raise QuoteError(f"{ticker}: {message}") from exc
        raise QuoteError(f"{ticker} did not return a price from Yahoo Finance.") from exc
    parsed["ticker"] = ticker
    return parsed


def refresh_quote(snapshot: dict, getter=None) -> dict:
    """Replace the quote on a copy of ``snapshot``. Other stored fields stay as they are.

    Yahoo Finance supplies the price, session change, and daily closes. Analyst
    targets, EPS, short interest, and borrow fields are left untouched. Raises
    QuoteError when Yahoo does not return a price, in which case the caller
    should keep the previous snapshot.
    """
    ticker = normalize_ticker(str(snapshot.get("ticker") or ""))
    get = getter or fetch_text
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    quote_url = yahoo_chart_url(ticker)
    try:
        parsed = parse_yahoo_chart(get(quote_url), ticker)
    except Exception as exc:
        message = str(exc).strip()
        if message.startswith("Provider") or message.startswith("Feed"):
            raise QuoteError(f"{ticker}: {message}") from exc
        raise QuoteError(f"{ticker} did not return a price from Yahoo Finance. The stored price was kept.") from exc
    updated = copy.deepcopy(snapshot)
    for field, value in parsed.items():
        if value is not None:
            updated[field] = value
    updated["ticker"] = ticker
    volume = updated.get("volume")
    average = updated.get("averageVolume")
    if isinstance(volume, (int, float)) and isinstance(average, (int, float)) and not isinstance(volume, bool) and not isinstance(average, bool) and average:
        updated["relativeVolume"] = volume / average
    sources = updated.get("sources")
    if not isinstance(sources, dict):
        sources = {}
        updated["sources"] = sources
    sources["quote"] = {"name": "Yahoo Finance", "url": quote_url, "fetchedAt": now, "asOf": updated.get("quoteAt")}
    updated["quoteFetchedAt"] = now
    return updated


def fetch_new_snapshot(raw: str, getter=None) -> dict:
    """Return a snapshot for one new ticker. Raises QuoteError when the price is missing."""
    ticker = normalize_ticker(raw)
    get = getter or fetch_text
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    quote_url = yahoo_chart_url(ticker)
    snapshot: dict = {"ticker": ticker, "name": ticker, "sources": {}, "attemptedAt": now, "origin": "fetched"}
    try:
        snapshot.update(parse_yahoo_chart(get(quote_url), ticker))
    except Exception as exc:
        message = str(exc).strip()
        if message.startswith("Provider") or message.startswith("Feed"):
            raise QuoteError(message) from exc
        raise QuoteError("That ticker did not return a price from Yahoo Finance, so it was not added.") from exc
    snapshot["sources"]["quote"] = {"name": "Yahoo Finance", "url": quote_url, "fetchedAt": now, "asOf": snapshot.get("quoteAt")}
    base = _equity_base(ticker)
    _apply_source(snapshot, "stats", "Stock Analysis", f"{base}/statistics/", parse_statistics_html, get)
    _apply_source(snapshot, "forecast", "Stock Analysis · analyst consensus", f"{base}/forecast/", parse_forecast_html, get)
    volume = snapshot.get("volume")
    average = snapshot.get("averageVolume")
    if isinstance(volume, (int, float)) and isinstance(average, (int, float)) and not isinstance(volume, bool) and average:
        snapshot["relativeVolume"] = volume / average
    return snapshot
