"""Seasonality, pasted X sentiment and US insider filings for the Macro Desk.

Numbers come from the caller: Yahoo closes, a Grok answer the user pastes,
or an SEC Form 4 document. A missing source stays missing. Nothing here
is estimated, and sample posts are never invented.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

# Sentiment weights from the implementation plan, section 4 step 6.
NEWS_WEIGHT = 0.6
SOCIAL_WEIGHT = 0.4
MIN_SOURCE_ITEMS = 3
TREND_DEADBAND = 3.0

INDEX_ALIASES: dict[str, str] = {
    "dax": "dax",
    "germany 40": "dax",
    "ger30": "dax",
    "uk100": "uk100",
    "ftse": "uk100",
    "ftse 100": "uk100",
    "us100": "ndx",
    "nasdaq": "ndx",
    "nasdaq 100": "ndx",
    "ndx": "ndx",
    "us30": "dow",
    "dow": "dow",
    "dow jones": "dow",
    "dow jones 30": "dow",
    "us500": "spx",
    "spx": "spx",
    "s&p": "spx",
    "s&p 500": "spx",
    "sp500": "spx",
}

SEC_UA = "Tradinglabs MacroDesk research@tradinglabs.app"
_FORM4_CODES = {"P": "buy", "S": "sell"}


def subject_id(name: str, extra: dict[str, str] | None = None) -> str | None:
    """Map a pasted subject name to an index id or a watchlist ticker.

    Matching is exact against the alias table. An unknown name returns
    None so the caller can skip it instead of guessing.
    """
    key = (name or "").strip().lstrip("$").lower()
    if not key:
        return None
    table = dict(INDEX_ALIASES)
    if extra:
        for alias, target in extra.items():
            table[alias.strip().lower()] = target
    return table.get(key)


def _tone(value: str) -> str:
    text = (value or "").strip().lower()
    if text.startswith("bull"):
        return "bullish"
    if text.startswith("bear"):
        return "bearish"
    return "neutral"


def _clamp_score(value: str) -> int:
    match = re.search(r"-?\d+", value or "")
    if match is None:
        return 0
    return max(-100, min(100, int(match.group(0))))


def parse_grok_import(text: str, extra_aliases: dict[str, str] | None = None) -> dict:
    """Parse a pasted Grok answer into reviewed blocks.

    Posts stay inside the SUBJECT block they were written in. A block
    whose subject is not in the alias table is skipped and named in
    ``unknown``. The tone and score are the ones Grok wrote.
    """
    items: list[dict] = []
    unknown: list[str] = []
    current: dict | None = None

    def push() -> None:
        nonlocal current
        if current is None:
            return
        if current.get("subject"):
            items.append(current)
        current = None

    for raw in (text or "").splitlines():
        line = raw.replace("**", "").strip()
        if not line:
            continue
        if re.fullmatch(r"-{3,}", line):
            push()
            continue
        match = re.match(r"^(SUBJECT|TONE|SCORE|SUMMARY|POST)\s*:\s*(.*)$", line, flags=re.IGNORECASE)
        if match is None:
            continue
        key = match.group(1).upper()
        value = match.group(2).strip()
        if key == "SUBJECT":
            push()
            found = subject_id(value, extra_aliases)
            current = {"subject": found, "label": value, "tone": "neutral", "score": 0, "summary": "", "posts": []}
            if found is None and value:
                unknown.append(value)
            continue
        if current is None:
            continue
        if key == "TONE":
            current["tone"] = _tone(value)
        elif key == "SCORE":
            current["score"] = _clamp_score(value)
        elif key == "SUMMARY":
            current["summary"] = value
        else:
            parts = [part.strip() for part in value.split("|")]
            if len(parts) < 3:
                continue
            link = ""
            if parts[-1].lower().startswith("http://") or parts[-1].lower().startswith("https://"):
                link = parts.pop()
            author = parts[0]
            tone = _tone(parts[1]) if len(parts) > 1 else "neutral"
            body = " | ".join(parts[2:]).strip()
            if author and body:
                current["posts"].append({"author": author, "tone": tone, "text": body, "link": link})
    push()
    return {"items": items, "unknown": unknown}


def score_day(news_score: float | None, news_count: int, social_score: float | None, social_count: int) -> dict:
    """One day's combined score. A thin source drops out and the day is low volume."""
    news_ok = news_score is not None and news_count >= MIN_SOURCE_ITEMS
    social_ok = social_score is not None and social_count >= MIN_SOURCE_ITEMS
    if news_ok and social_ok:
        combined = NEWS_WEIGHT * float(news_score) + SOCIAL_WEIGHT * float(social_score)
        return {"score": combined, "low_volume": False, "news": float(news_score), "social": float(social_score)}
    if news_ok:
        return {"score": float(news_score), "low_volume": True, "news": float(news_score), "social": None}
    if social_ok:
        return {"score": float(social_score), "low_volume": True, "news": None, "social": float(social_score)}
    return {"score": None, "low_volume": True, "news": None, "social": None}


def _on_date(history: dict, day: date) -> dict | None:
    entry = history.get(day.isoformat())
    return entry if isinstance(entry, dict) else None


def sentiment_view(history: dict | None, today: date, news_score: float | None = None, news_count: int = 0) -> dict:
    """Today's score, the 7-day change, and the stored daily series.

    ``history`` maps an ISO date to ``{"score", "posts", "summary", "tone"}``
    from confirmed imports. News is optional. Days that were never saved
    are left out of the series.
    """
    stored = history if isinstance(history, dict) else {}
    series: list[dict] = []
    combined_by_day: dict[date, float] = {}
    for key, entry in stored.items():
        if not isinstance(entry, dict):
            continue
        try:
            day = date.fromisoformat(str(key))
        except ValueError:
            continue
        posts = entry.get("posts") if isinstance(entry.get("posts"), list) else []
        social = entry.get("score") if isinstance(entry.get("score"), (int, float)) else None
        # News is only known for today. Older days keep the social import.
        day_news = news_score if day == today else None
        day_news_count = news_count if day == today else 0
        scored = score_day(day_news, day_news_count, social, len(posts))
        if scored["score"] is None:
            continue
        point = {"date": day.isoformat(), "combined": scored["score"], "news": scored["news"], "social": scored["social"]}
        series.append(point)
        combined_by_day[day] = float(scored["score"])
    series.sort(key=lambda point: point["date"])

    today_entry = _on_date(stored, today) or {}
    today_posts = today_entry.get("posts") if isinstance(today_entry.get("posts"), list) else []
    today_social = today_entry.get("score") if isinstance(today_entry.get("score"), (int, float)) else None
    today_scored = score_day(news_score, news_count, today_social, len(today_posts))

    def window(end: date) -> float | None:
        values = [combined_by_day[end - timedelta(days=offset)] for offset in range(3) if (end - timedelta(days=offset)) in combined_by_day]
        if len(values) < 3:
            return None
        return sum(values) / 3

    recent = window(today)
    earlier = window(today - timedelta(days=7))
    change = None if recent is None or earlier is None else recent - earlier
    label = None
    if change is not None and abs(change) > TREND_DEADBAND:
        label = "Improving" if change > 0 else "Worsening"
    latest = None
    dated = [key for key in stored if isinstance(stored.get(key), dict)]
    if dated:
        latest_key = max(dated)
        latest = dict(stored[latest_key])
        latest["date"] = latest_key
    return {
        "score": today_scored["score"],
        "low_volume": today_scored["low_volume"],
        "news": today_scored["news"],
        "social": today_scored["social"],
        "change": change,
        "label": label,
        "series": series,
        "latest": latest,
        "posts": today_posts,
        "summary": str(today_entry.get("summary") or ""),
    }


def _closes_by_date(candles: list[dict]) -> list[tuple[date, float]]:
    pairs: list[tuple[date, float]] = []
    for candle in candles or []:
        if not isinstance(candle, dict):
            continue
        try:
            day = date.fromisoformat(str(candle.get("date")))
        except ValueError:
            continue
        close = candle.get("close")
        if isinstance(close, bool) or not isinstance(close, (int, float)):
            continue
        pairs.append((day, float(close)))
    pairs.sort(key=lambda item: item[0])
    return pairs


def seasonality_from_candles(candles: list[dict], today: date) -> dict:
    """Year-to-date percent from each year's first close, for this year and the two before.

    Monthly cells with no published close stay None. Months after the
    current month in the current year stay blank. The current month is
    partial because it uses the latest close so far.
    """
    pairs = _closes_by_date(candles)
    years = [today.year, today.year - 1, today.year - 2]
    by_year: dict[int, list[tuple[date, float]]] = {year: [(day, close) for day, close in pairs if day.year == year and day <= today] for year in years}
    # Prior years keep their full calendar. The current year stops at today.
    by_year[today.year - 1] = [(day, close) for day, close in pairs if day.year == today.year - 1]
    by_year[today.year - 2] = [(day, close) for day, close in pairs if day.year == today.year - 2]

    def path(year: int) -> list[tuple[date, float]]:
        rows = by_year.get(year) or []
        if not rows:
            return []
        base = rows[0][1]
        if base == 0:
            return []
        return [(day, (close / base - 1) * 100) for day, close in rows]

    paths = {year: path(year) for year in years}
    current_path = paths.get(today.year) or []
    anchor = current_path[-1][0] if current_path else today

    def at_same_point(year: int) -> float | None:
        rows = paths.get(year) or []
        chosen = [pct for day, pct in rows if (day.month, day.day) <= (anchor.month, anchor.day)]
        return chosen[-1] if chosen else None

    summary = {str(year): at_same_point(year) for year in years}

    def month_return(year: int, month: int) -> float | None:
        if year == today.year and month > today.month:
            return None
        rows = by_year.get(year) or []
        in_month = [close for day, close in rows if day.month == month]
        if not in_month:
            return None
        before = [close for day, close in rows if day.month < month]
        if not before:
            earlier = [close for day, close in pairs if day < date(year, month, 1)]
            if not earlier:
                return None
            previous = earlier[-1]
        else:
            previous = before[-1]
        if previous == 0:
            return None
        return (in_month[-1] / previous - 1) * 100

    monthly = {str(year): [month_return(year, month) for month in range(1, 13)] for year in years}
    previous = [monthly[str(today.year - 1)], monthly[str(today.year - 2)]]
    average: list[float | None] = []
    for month in range(12):
        values = [row[month] for row in previous if row[month] is not None]
        average.append(sum(values) / len(values) if len(values) == 2 else None)

    keys = []
    cursor = date(2025, 1, 1)
    while cursor.year == 2025:
        keys.append(cursor.month * 100 + cursor.day)
        cursor += timedelta(days=1)
    chart: dict[str, list[float | None]] = {str(year): [None] * len(keys) for year in years}
    index_of = {key: position for position, key in enumerate(keys)}
    for year in years:
        for day, pct in paths.get(year) or []:
            key = day.month * 100 + day.day
            if day.month == 2 and day.day == 29:
                key = 228
            position = index_of.get(key)
            if position is not None:
                chart[str(year)][position] = pct
    return {
        "years": years,
        "as_of": anchor.isoformat(),
        "summary": summary,
        "monthly": monthly,
        "average": average,
        "average_label": f"Avg {today.year - 2}–{today.year - 1}",
        "partial_month": today.month,
        "labels": [f"{key // 100:02d}-{key % 100:02d}" for key in keys],
        "chart": chart,
    }


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(node: ET.Element | None) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.strip()


def _find(node: ET.Element, name: str) -> ET.Element | None:
    for child in node.iter():
        if _local(child.tag) == name:
            return child
    return None


def _child_text(node: ET.Element, name: str) -> str:
    for child in list(node):
        if _local(child.tag) == name:
            return _text(child) or _child_text(child, "value")
    found = _find(node, name)
    if found is None:
        return ""
    return _text(found) or _child_text(found, "value")


def parse_form4(xml_text: str, filed_at: str = "") -> list[dict]:
    """Open-market and other transactions from one Form 4 XML document.

    Code P is an open-market buy and code S is a sale. Awards and option
    exercises stay type "other". A missing price or share count stays None.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    owner = ""
    role = ""
    for node in root.iter():
        if _local(node.tag) == "rptOwnerName" and not owner:
            owner = _text(node)
        if _local(node.tag) == "officerTitle" and _text(node) and not role:
            role = _text(node)
        if _local(node.tag) == "isDirector" and _text(node) in {"1", "true"} and not role:
            role = "Director"
    trades: list[dict] = []
    for node in root.iter():
        if _local(node.tag) not in {"nonDerivativeTransaction", "derivativeTransaction"}:
            continue
        code = ""
        traded = ""
        shares = None
        price = None
        for child in node.iter():
            local = _local(child.tag)
            if local == "transactionCode" and _text(child):
                code = _text(child).upper()
            elif local == "transactionDate" and not traded:
                traded = _child_text(child, "value") or _text(child)
            elif local == "transactionShares" and shares is None:
                shares = _number(_child_text(child, "value") or _text(child))
            elif local == "transactionPricePerShare" and price is None:
                price = _number(_child_text(child, "value") or _text(child))
        if not code and not traded:
            continue
        if price is not None and price <= 0:
            price = None
        value = shares * price if shares is not None and price is not None else None
        trades.append({
            "person": owner or "Name not in filing",
            "role": role or "Role not in filing",
            "type": _FORM4_CODES.get(code, "other"),
            "code": code,
            "traded_at": traded,
            "filed_at": filed_at,
            "shares": shares,
            "price": price,
            "value": value,
        })
    return trades


def _number(value: str) -> float | None:
    try:
        number = float(str(value).replace(",", ""))
    except ValueError:
        return None
    return number


def insider_summary(trades: list[dict], today: date, days: int = 30) -> dict:
    """Net open-market activity over the last ``days`` calendar days.

    Only code P and code S count toward the net. A filing with no price
    still counts as a buy or a sale, and its value stays out of the total.
    """
    start = today - timedelta(days=days)
    window: list[dict] = []
    for trade in trades:
        try:
            traded = date.fromisoformat(str(trade.get("traded_at") or "")[:10])
        except ValueError:
            continue
        if start <= traded <= today:
            window.append(trade)
    buy_value = sum(float(trade["value"]) for trade in window if trade.get("type") == "buy" and isinstance(trade.get("value"), (int, float)))
    sell_value = sum(float(trade["value"]) for trade in window if trade.get("type") == "sell" and isinstance(trade.get("value"), (int, float)))
    buys = sum(1 for trade in window if trade.get("type") == "buy")
    sells = sum(1 for trade in window if trade.get("type") == "sell")
    valued = any(isinstance(trade.get("value"), (int, float)) for trade in window if trade.get("type") in {"buy", "sell"})
    net = buy_value - sell_value if valued else None
    if buys <= 0:
        buying = False
    elif sells == 0:
        buying = True
    else:
        buying = net is not None and net > 0
    return {
        "trades": window,
        "buys": buys,
        "sells": sells,
        "net_value": net,
        "insider_buying": buying,
    }


def _sec_get(url: str, timeout: int = 16) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": SEC_UA, "Accept": "application/json,application/xml,text/xml"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"SEC returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("SEC filings could not be reached") from exc


def form4_xml_name(names: list[str], primary: str) -> str:
    """Prefer the raw Form 4 XML over the styled HTML copy."""
    plain = [name for name in names if name.lower().endswith(".xml") and "xsl" not in name.lower()]
    for name in plain:
        if name.lower().endswith("form4.xml"):
            return name
    return plain[0] if plain else primary


def fetch_us_insider_trades(ticker: str, getter=None, today: date | None = None) -> dict:
    """Recent Form 4 transactions for a US ticker, or an unavailable result.

    ``getter`` maps a URL to a response body in tests. Live calls use the
    SEC company ticker list and the submissions JSON.
    """
    symbol = (ticker or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{1,5}", symbol):
        return {"available": False, "reason": "not-us", "trades": [], "summary": insider_summary([], today or date.today())}
    get = getter or _sec_get
    as_of = today or date.today()
    try:
        raw = json.loads(get("https://www.sec.gov/files/company_tickers.json"))
    except Exception:
        return {"available": False, "reason": "lookup-failed", "trades": [], "summary": insider_summary([], as_of)}
    cik = None
    if isinstance(raw, dict):
        for row in raw.values():
            if isinstance(row, dict) and str(row.get("ticker") or "").upper() == symbol:
                cik = str(row.get("cik_str") or "")
                break
    if not cik:
        return {"available": False, "reason": "no-cik", "trades": [], "summary": insider_summary([], as_of)}
    cik_padded = cik.zfill(10)
    try:
        submissions = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik_padded}.json"))
    except Exception:
        return {"available": False, "reason": "filings-failed", "trades": [], "summary": insider_summary([], as_of)}
    recent = ((submissions.get("filings") or {}).get("recent") or {}) if isinstance(submissions, dict) else {}
    forms = recent.get("form") or []
    filed = recent.get("filingDate") or []
    accessions = recent.get("accessionNumber") or []
    documents = recent.get("primaryDocument") or []
    trades: list[dict] = []
    fetched = 0
    for index, form in enumerate(forms):
        if str(form).strip() != "4" or index >= len(accessions) or index >= len(documents):
            continue
        filed_at = str(filed[index]) if index < len(filed) else ""
        try:
            filed_day = date.fromisoformat(filed_at[:10])
        except ValueError:
            continue
        if filed_day < as_of - timedelta(days=60):
            continue
        accession = str(accessions[index]).replace("-", "")
        folder = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession}"
        document = str(documents[index]).lstrip("/")
        try:
            listing = json.loads(get(folder + "/index.json"))
            names = [item.get("name") for item in ((listing.get("directory") or {}).get("item") or []) if isinstance(item, dict)]
            document = form4_xml_name([name for name in names if isinstance(name, str)], document)
        except Exception:
            pass
        try:
            xml_text = get(f"{folder}/{document}")
        except Exception:
            continue
        trades.extend(parse_form4(xml_text, filed_at))
        fetched += 1
        if fetched >= 6:
            break
    return {"available": True, "reason": "", "trades": trades, "summary": insider_summary(trades, as_of)}


def fetch_bluesky_posts(query: str, getter=None) -> dict:
    """Recent public Bluesky posts for a search. No tone is assigned.

    The v1 desk does not run a classifier, so each post is unscored.
    A failed request stays unavailable.
    """
    text = (query or "").strip()
    if not text:
        return {"available": False, "posts": []}
    url = "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts?q=" + urllib.parse.quote(text) + "&limit=5"
    get = getter or _sec_get
    try:
        payload = json.loads(get(url))
    except Exception:
        return {"available": False, "posts": []}
    posts = []
    for item in (payload.get("posts") or []) if isinstance(payload, dict) else []:
        if not isinstance(item, dict):
            continue
        record = item.get("record") if isinstance(item.get("record"), dict) else {}
        author = item.get("author") if isinstance(item.get("author"), dict) else {}
        body = str(record.get("text") or "").strip()
        handle = str(author.get("handle") or "").strip()
        if not body or not handle:
            continue
        posts.append({"author": handle, "text": body, "tone": "unscored", "created": str(record.get("createdAt") or item.get("indexedAt") or "")})
    return {"available": True, "posts": posts}
