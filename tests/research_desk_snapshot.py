"""Research Desk page uses stored snapshots and does not fill missing figures."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from datetime import date, datetime, timedelta, timezone

from research_desk_page import (
    CLOSE_WINDOWS,
    DEFAULT_CLOSE_WINDOW,
    BREADTH_SOURCES,
    MACRO_MARKETS,
    THESES,
    _at_high,
    _at_low,
    _is_fresh,
    _return_over_days,
    _snapshot_fetched_at,
    aggregate_4h,
    average_position,
    close_window,
    compute_macro_spider,
    daily_trend,
    breadth_summary,
    breadth_text,
    constituent_symbols,
    load_breadth,
    load_macro_rows,
    load_quote_cache,
    macro_trend_for,
    macro_trends_html,
    load_snapshots,
    rsi_14,
    save_quote_cache,
    sma,
    squeeze_checks,
    thesis_for,
    trend_text,
    upside,
    valuation_sentence,
    watchlist_html,
    watchlist_rows,
    weekly_trend,
)
from research_desk_quotes import (
    QuoteError,
    fetch_candles,
    fetch_new_snapshot,
    fetch_news_rss,
    normalize_ticker,
    number_value,
    parse_forecast_html,
    parse_headlines,
    parse_insider,
    parse_statistics_html,
    parse_yahoo_chart,
    refresh_quote,
    search_symbols,
    yahoo_chart_url,
)


def test_seed_tickers_and_missing_forward_pe() -> None:
    snapshots = {row["ticker"]: row for row in load_snapshots()}
    assert list(snapshots) == ["USAR", "IBRX", "ALMU", "NVO", "UUUU", "SMR"]
    assert snapshots["USAR"].get("forwardPE") is None
    assert snapshots["NVO"]["forwardPE"] == 11.708
    assert snapshots["NVO"].get("shortFloatPct") is None


def test_upside_matches_repo_formula() -> None:
    snapshots = {row["ticker"]: row for row in load_snapshots()}
    usar = snapshots["USAR"]
    assert upside(usar) == (usar["target"] / usar["price"] - 1) * 100
    assert upside({"price": 10, "target": 15}) == 50
    assert upside({"price": 0, "target": 15}) is None
    assert upside({"price": 10}) is None
    assert upside({"target": 15}) is None


def test_missing_squeeze_input_stays_unknown() -> None:
    checks = {row["label"]: row for row in squeeze_checks({"shortFloatPct": None, "daysToCover": 3, "borrowFee": 10})}
    assert checks["Short float ≥ 20%"]["known"] is False
    assert checks["Short float ≥ 20%"]["passed"] is False
    assert checks["Days to cover ≥ 3"]["passed"] is True
    assert checks["Borrow fee ≥ 10%"]["passed"] is True
    assert checks["Available shares ≤ 100k"]["known"] is False
    assert checks["Day volume / 20d avg ≥ 1.5×"]["passed"] is False

    nvo = {row["label"]: row for row in squeeze_checks(next(s for s in load_snapshots() if s["ticker"] == "NVO"))}
    assert nvo["Short float ≥ 20%"]["known"] is False
    assert nvo["Days to cover ≥ 3"]["passed"] is False


def test_seed_squeeze_counts() -> None:
    expected = {"USAR": 1, "IBRX": 2, "ALMU": 2, "NVO": 0, "UUUU": 2, "SMR": 1}
    rows = {row["ticker"]: row for row in watchlist_rows()}
    assert [row["ticker"] for row in watchlist_rows()][0] == "USAR"
    for ticker, met in expected.items():
        assert rows[ticker]["squeeze_met"] == met
    assert rows["NVO"]["squeeze_unknown"] == 1
    assert rows["USAR"]["forward_pe"] is None
    assert rows["NVO"]["forward_pe"] == 11.708
    assert rows["USAR"]["thesis"].startswith("Rare-earth")


def test_thesis_text_is_the_repo_playbook() -> None:
    source = (ROOT / "research-desk" / "lib" / "research.ts").read_text(encoding="utf-8")
    assert thesis_for("NOT_A_TICKER") is None
    for ticker, thesis in THESES.items():
        assert thesis["title"] in source
        assert thesis["case"] in source
        assert thesis["proof"] in source
        assert thesis["invalid"] in source
        assert thesis_for(ticker)["title"] == thesis["title"]


def test_valuation_sentence_uses_stored_numbers_only() -> None:
    usar = next(row for row in load_snapshots() if row["ticker"] == "USAR")
    sentence = valuation_sentence(usar)
    assert "$9.27" in sentence
    assert "$35.13" in sentence
    assert "+279.2%" in sentence
    assert "Forward P/E is not in the snapshot." in sentence
    nvo = next(row for row in load_snapshots() if row["ticker"] == "NVO")
    nvo_sentence = valuation_sentence(nvo)
    assert "11.7×" in nvo_sentence
    assert "$3.86" in nvo_sentence


def _label_from_closes(latest: float, previous: list[float]) -> str:
    if all(latest > item for item in previous):
        return "Up"
    if all(latest < item for item in previous):
        return "Down"
    return "Flat"


def _week_label(dates: list[str], closes: list[float]) -> str | None:
    pairs = [(date.fromisoformat(day), close) for day, close in zip(dates, closes)]
    latest_day = pairs[-1][0]
    this_key = latest_day.isocalendar()[:2]
    previous_key = (latest_day - timedelta(days=7)).isocalendar()[:2]
    this_closes = [close for day, close in pairs if day.isocalendar()[:2] == this_key]
    previous_closes = [close for day, close in pairs if day.isocalendar()[:2] == previous_key]
    if not this_closes or not previous_closes:
        return None
    if this_closes[-1] > previous_closes[-1]:
        return "Up"
    if this_closes[-1] < previous_closes[-1]:
        return "Down"
    return "Flat"


def test_daily_and_weekly_trends_use_stored_series() -> None:
    snapshots = {row["ticker"]: row for row in load_snapshots()}
    usar = snapshots["USAR"]
    closes = usar["closes"]
    assert daily_trend(usar) == _label_from_closes(closes[-1], closes[-4:-1])
    assert daily_trend(usar) in {"Up", "Down", "Flat"}
    assert weekly_trend(usar) == _week_label(usar["closeDates"], closes)
    assert daily_trend({"closes": [1, 2, 3, 4]}) == "Up"
    assert daily_trend({"closes": [4, 3, 2, 1]}) == "Down"
    assert daily_trend({"closes": [1, 5, 2, 3]}) == "Flat"
    assert daily_trend({"closes": [5, 4, 6, 5]}) == "Flat"
    assert daily_trend({"closes": [10, 12]}) is None
    assert trend_text(None) == "Not enough closes"
    assert trend_text("Flat") == "Flat"
    same_week = {"closes": [10, 11, 12], "closeDates": ["2026-10-26", "2026-10-27", "2026-10-28"]}
    assert weekly_trend(same_week) is None
    assert weekly_trend({"closes": [10, 12], "closeDates": ["2026-10-23", "2026-10-30"]}) == "Up"
    assert weekly_trend({"closes": [12, 10], "closeDates": ["2026-10-23", "2026-10-30"]}) == "Down"
    assert weekly_trend({"closes": [10, 10], "closeDates": ["2026-10-23", "2026-10-30"]}) == "Flat"
    assert weekly_trend({"closes": [1, 2, 3]}) is None
    rising = list(range(1, 21))
    assert rsi_14({"closes": rising}) == 100
    assert rsi_14({"closes": list(reversed(rising))}) == 0
    assert rsi_14({"closes": [1, 2, 3]}) is None
    flat_ma = {"closes": [2.0] * 200, "price": 2.0}
    assert average_position(flat_ma) == "At the average"
    assert average_position({"closes": [1.0] * 199, "price": 5}) is None
    assert average_position({"closes": [1.0] * 200, "price": 2}) == "Above"
    assert average_position({"closes": [3.0] * 200, "price": 2}) == "Below"
    windowed = {"closes": [float(day) for day in range(1, 31)], "closeDates": [f"2026-10-{day:02d}" for day in range(1, 31)]}
    last_30, last_dates = close_window(windowed, 30)
    assert last_dates[0] == "2026-10-01" and last_dates[-1] == "2026-10-30"
    assert len(last_30) == 30
    shorter, shorter_dates = close_window(windowed, 60)
    assert shorter_dates[0] == "2026-10-01"
    assert daily_trend(windowed) == daily_trend({"closes": windowed["closes"], "closeDates": windowed["closeDates"]})
    assert DEFAULT_CLOSE_WINDOW == 365
    assert set(CLOSE_WINDOWS) == {90, 365, 1825}
    rows = {row["ticker"]: row for row in watchlist_rows()}
    assert rows["USAR"]["daily_trend"] == daily_trend(usar)
    assert rows["USAR"]["weekly_trend"] == weekly_trend(usar)
    assert rows["USAR"]["rsi"] != "Not enough closes"
    assert rows["USAR"]["average"] == "Not enough closes"
    page = (ROOT / "research_desk_page.py").read_text(encoding="utf-8")
    assert "Open a stock" not in page
    assert "Price as of" not in page
    assert "session change" not in page
    assert 'st.button("Refresh prices"' in page
    assert "width=\"stretch\"" in page
    table = watchlist_html(watchlist_rows())
    assert 'href="?ticker=USAR"' in table
    assert 'href="?ticker=NVO"' in table
    assert 'target="_blank"' in table
    assert 'rel="noopener"' in table
    assert 'target="_self"' not in table
    assert "Back to the watchlist" in page
    assert "on its own page" in page
    assert "Daily trend" in table and "Weekly trend" in table
    assert "Daily RSI (14)" in table and "Weekly RSI (14)" in table
    assert "Daily 200-day average" in table and "Weekly 200-day average" in table
    assert "Price as of" not in table
    assert " UK" not in table


def test_added_snapshot_uses_only_returned_fields() -> None:
    yahoo = {
        "chart": {
            "result": [
                {
                    "meta": {
                        "longName": "Example Co",
                        "currency": "USD",
                        "regularMarketPrice": 20,
                        "regularMarketChangePercent": 1.5,
                        "regularMarketTime": 1700000000,
                        "regularMarketVolume": 1000,
                        "exchangeName": "NMS",
                    },
                    "timestamp": [1700000000 + i * 86400 for i in range(6)],
                    "indicators": {"quote": [{"close": [10, 11, 12, 13, 14, 16], "volume": [1, 1, 1, 1, 1, 1]}]},
                }
            ]
        }
    }
    stats = """
    <table>
      <tr><td>Market Cap</td><td title="100">100</td></tr>
      <tr><td>Shares Outstanding</td><td title="10">10</td></tr>
      <tr><td>Earnings Per Share (EPS)</td><td title="1.5">$1.50</td></tr>
      <tr><td>Short % of Float</td><td title="22">22%</td></tr>
    </table>
    """
    forecast = """
    <table>
      <tr><td>Target</td><td>Low</td><td>Average</td><td>Median</td><td>High</td></tr>
      <tr><td>Price</td><td>$10</td><td>$30</td><td>$28</td><td>$40</td></tr>
    </table>
    """
    pages = {
        "https://query1.finance.yahoo.com/v8/finance/chart/EX?interval=1d&range=5y": __import__("json").dumps(yahoo),
        "https://stockanalysis.com/stocks/ex/statistics/": stats,
        "https://stockanalysis.com/stocks/ex/forecast/": forecast,
    }

    def getter(url: str) -> str:
        if url not in pages:
            raise RuntimeError(f"unexpected {url}")
        return pages[url]

    snapshot = fetch_new_snapshot("ex", getter)
    assert snapshot["ticker"] == "EX"
    assert snapshot["name"] == "Example Co"
    assert snapshot["price"] == 20
    assert snapshot["changePct"] == 1.5
    assert snapshot["eps"] == 1.5
    assert snapshot.get("forwardPE") is None
    assert snapshot["target"] == 30
    assert snapshot["shortFloatPct"] == 22
    assert "borrowFee" not in snapshot
    assert daily_trend(snapshot) == "Up"
    assert rsi_14(snapshot) is None
    assert number_value("n/a") is None
    assert parse_statistics_html(stats)["forwardPE"] is None
    try:
        parse_forecast_html("<table><tr><td>Other</td></tr></table>")
    except RuntimeError:
        pass
    else:
        raise AssertionError("forecast parser accepted a page with no target")
    try:
        fetch_new_snapshot("nope!", getter)
    except QuoteError:
        pass
    else:
        raise AssertionError("invalid ticker was accepted")


def test_refresh_quote_updates_price_and_keeps_fundamentals() -> None:
    usar = next(row for row in load_snapshots() if row["ticker"] == "USAR")
    stored_price = usar["price"]
    yahoo = {
        "chart": {
            "result": [
                {
                    "meta": {
                        "longName": "USA Rare Earth, Inc.",
                        "currency": "USD",
                        "regularMarketPrice": 21.5,
                        "regularMarketChangePercent": 2.25,
                        "regularMarketTime": 1762800000,
                        "regularMarketVolume": 2500,
                        "exchangeName": "NGM",
                    },
                    "timestamp": [1762800000 - i * 86400 for i in range(6, 0, -1)],
                    "indicators": {"quote": [{"close": [18, 19, 20, 20.5, 21, 21.5], "volume": [1, 1, 1, 1, 1, 2500]}]},
                }
            ]
        }
    }

    def getter(url: str) -> str:
        if "query1.finance.yahoo.com" not in url or "/USAR?" not in url:
            raise RuntimeError(f"unexpected {url}")
        return __import__("json").dumps(yahoo)

    updated = refresh_quote(usar, getter)
    assert updated is not usar
    assert usar["price"] == stored_price
    assert updated["price"] == 21.5
    assert updated["changePct"] == 2.25
    assert updated["target"] == usar["target"]
    assert updated["eps"] == usar["eps"]
    assert updated["shortFloatPct"] == usar["shortFloatPct"]
    assert updated["borrowFee"] == usar["borrowFee"]
    assert updated["closes"][-1] == 21.5
    assert daily_trend(updated) == "Up"
    assert updated["relativeVolume"] == 2500 / usar["averageVolume"]
    assert updated["quoteFetchedAt"]
    assert updated["sources"]["quote"]["name"] == "Yahoo Finance"
    assert "stockanalysis.com" not in updated["sources"]["quote"]["url"]

    def fail(url: str) -> str:
        raise RuntimeError("Provider rate limit; try again later")

    try:
        refresh_quote(usar, fail)
    except QuoteError as exc:
        assert "USAR" in str(exc)
        assert "rate limit" in str(exc)
    else:
        raise AssertionError("a failed refresh was treated as a new price")
    assert usar["price"] == stored_price
    page = (ROOT / "research_desk_page.py").read_text(encoding="utf-8")
    assert 'st.button("Refresh prices"' in page
    cache = ROOT / "tests" / "_quote_cache.json"
    save_quote_cache({"refreshed": {"USAR": {"ticker": "USAR", "price": 21.5}}, "added": {}, "refresh_at": "2026-11-10T09:40:00Z", "errors": []}, cache)
    loaded = load_quote_cache(cache)
    assert loaded["refreshed"]["USAR"]["price"] == 21.5
    assert loaded["refresh_at"] == "2026-11-10T09:40:00Z"
    cache.unlink()
    assert load_quote_cache(cache) == {}


def test_macro_trends_follow_the_desk_rules() -> None:
    dates = [f"2026-10-{day:02d}" for day in range(1, 31)]
    closes = list(range(1, 31))
    stamps = [int(__import__("datetime").datetime.fromisoformat(day).replace(tzinfo=__import__("datetime").timezone.utc).timestamp()) for day in dates]
    body = __import__("json").dumps(
        {
            "chart": {
                "result": [
                    {
                        "meta": {"regularMarketPrice": 30, "shortName": "Macro"},
                        "timestamp": stamps,
                        "indicators": {"quote": [{"close": closes, "high": closes, "low": closes}]},
                    }
                ]
            }
        }
    )
    hour_stamps = [int(__import__("datetime").datetime(2026, 11, 20, tzinfo=__import__("datetime").timezone.utc).timestamp()) + hour * 3600 for hour in range(100)]
    hour_closes = [float(100 + hour) for hour in range(100)]
    hourly_body = __import__("json").dumps(
        {
            "chart": {
                "result": [
                    {
                        "meta": {"regularMarketPrice": 199, "shortName": "Macro hourly"},
                        "timestamp": hour_stamps,
                        "indicators": {"quote": [{"close": hour_closes, "high": hour_closes, "low": hour_closes}]},
                    }
                ]
            }
        }
    )
    expected = {yahoo_chart_url(symbol, "6mo"): body for _, symbol in MACRO_MARKETS}
    failed = yahoo_chart_url("^GDAXI", "6mo")

    def getter(url: str) -> str:
        if "GDAXI" in url:
            raise RuntimeError("Ticker not found or quote unavailable")
        if url == failed:
            raise RuntimeError("Ticker not found or quote unavailable")
        if url in expected:
            return expected[url]
        if "news.google.com/rss" in url:
            return '<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>'
        if "query1.finance.yahoo.com" in url:
            if "interval=1h" in url or "interval=60m" in url:
                return hourly_body
            return body
        raise RuntimeError(f"unexpected {url}")

    rows = load_macro_rows(getter)
    assert [row["label"] for row in rows] == ["BTCUSD", "US500", "US100", "US30", "ETHUSD", "UK100", "GER30", "EURUSD", "GBPJPY", "USDJPY"]
    assert [symbol for _, symbol in MACRO_MARKETS[-3:]] == ["EURUSD=X", "GBPJPY=X", "USDJPY=X"]
    assert normalize_ticker("^GSPC") == "^GSPC"
    for row in rows:
        if row["label"] == "GER30":
            assert row["available"] is False
            assert row["daily"] is None and row["weekly"] is None
        else:
            assert row["available"] is True
            assert row["daily"] == "Up"
            assert row["weekly"] == "Up"
    html = macro_trends_html(rows)
    assert "BTCUSD" in html and "GER30" in html
    assert "EURUSD" in html and "GBPJPY" in html and "USDJPY" in html
    assert ">Daily <" in html and ">Weekly <" in html
    assert "4-hour" in html
    assert "Unavailable" in html
    assert "RSI" not in html and "200-day" not in html and "$" not in html
    assert 'href="?breadth=US500"' in html
    assert 'href="?breadth=UK100"' in html
    assert 'href="?breadth=BTCUSD"' not in html
    assert 'href="?breadth=ETHUSD"' not in html
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert source.index("render_macro_trends()") < source.index("st.navigation(")


def test_breadth_uses_published_highs_and_lows_only() -> None:
    table = """
    <table>
      <tr><td>Company</td><td>Exchange</td><td>Symbol</td></tr>
      <tr><td>Apple</td><td>NASDAQ</td><td>AAPL</td></tr>
      <tr><td>Microsoft</td><td>NASDAQ</td><td>MSFT</td></tr>
      <tr><td>Coca-Cola</td><td>NYSE</td><td>KO</td></tr>
      <tr><td>IBM</td><td>NYSE</td><td>IBM</td></tr>
      <tr><td>Date added</td><td>NYSE</td><td>Date added</td></tr>
    </table>
    """
    symbols = constituent_symbols(table, "US30")
    assert symbols == ["AAPL", "MSFT", "KO", "IBM"]
    assert constituent_symbols(
        "<table><tr><td>Company</td><td>Exchange</td><td>Symbol</td></tr><tr><td>Berkshire</td><td>NYSE</td><td>BRK.B</td></tr></table>",
        "US30",
    ) == ["BRK-B"]
    uk = constituent_symbols(
        "<table><tr><td>Company</td><td>Ticker</td></tr><tr><td>3i</td><td>III</td></tr></table>",
        "UK100",
    )
    assert uk == ["III.L"]
    assert constituent_symbols(
        "<table><tr><td>Company</td><td>Ticker</td></tr><tr><td>BT Group</td><td>BT.A</td></tr></table>",
        "UK100",
    ) == ["BT-A.L"]
    german = constituent_symbols(
        "<table><tr><td>Ticker</td><td>Company</td></tr><tr><td>ADS.DE</td><td>Adidas</td></tr><tr><td>AIR.PA</td><td>Airbus</td></tr></table>",
        "GER30",
    )
    assert german == ["ADS.DE", "AIR.PA"]

    def chart(day_high, day_low, high_52, low_52) -> str:
        return __import__("json").dumps(
            {
                "chart": {
                    "result": [
                        {
                            "meta": {
                                "regularMarketDayHigh": day_high,
                                "regularMarketDayLow": day_low,
                                "fiftyTwoWeekHigh": high_52,
                                "fiftyTwoWeekLow": low_52,
                            }
                        }
                    ]
                }
            }
        )

    quotes = {
        yahoo_chart_url("AAPL", "5d"): chart(10, 9, 10, 5),
        yahoo_chart_url("MSFT", "5d"): chart(8, 5, 12, 5),
        yahoo_chart_url("KO", "5d"): chart(8, 6, 12, 4),
    }

    def getter(url: str) -> str:
        if url == BREADTH_SOURCES["US30"]["url"]:
            return table
        if url not in quotes:
            raise RuntimeError("missing quote")
        return quotes[url]

    summary = load_breadth("US30", getter)
    assert summary["ready"] is True
    assert summary["measured"] == 3
    assert summary["unknown"] == 1
    assert summary["highs"] == 1
    assert summary["lows"] == 1
    assert summary["high_pct"] == (1 / 3) * 100
    text = breadth_text(summary)
    assert "33.3%" in text
    assert "52-week high" in text and "52-week low" in text
    assert "left out" in text
    crypto = breadth_text(load_breadth("BTCUSD", getter))
    assert crypto == "Underlying highs and lows do not apply to BTCUSD."
    neither = breadth_summary("US30", ["AAA"], [None])
    assert neither["ready"] is False
    assert "percentage" in breadth_text({**neither, "applies": True})

    # The desk rule is "near": within 1% of the 52-week extreme.
    assert _at_high(9.95, 10) is True
    assert _at_high(9.9, 10) is True
    assert _at_high(9.5, 10) is False
    assert _at_low(5.05, 5) is True
    assert _at_low(5.5, 5) is False
    near_high = breadth_summary("US30", ["NEAR"], [{"day_high": 9.95, "day_low": 9, "high_52": 10, "low_52": 5}])
    assert near_high["highs"] == 1 and near_high["lows"] == 0
    not_high = breadth_summary("US30", ["NEAR"], [{"day_high": 9.5, "day_low": 9, "high_52": 10, "low_52": 5}])
    assert not_high["highs"] == 0
    near_low = breadth_summary("US30", ["NEAR"], [{"day_high": 8, "day_low": 5.05, "high_52": 12, "low_52": 5}])
    assert near_low["lows"] == 1 and near_low["highs"] == 0


def test_parse_headlines_caps_at_five_and_truncates_titles() -> None:
    words = [f"Word{number}" for number in range(1, 26)]
    long_title = " ".join(words)
    items = []
    for index in range(7):
        title = long_title if index == 0 else f"Apple reports record quarter {index}"
        items.append(
            f'<h3><a href="/stocks/aapl/news/story-{index}">{title}</a></h3>'
            f'<div><span title="2026-11-{20 - index:02d}T09:30:00Z">Nov {20 - index}, 2026</span></div>'
        )
    parsed = parse_headlines("\n".join(items))
    headlines = parsed["headlines"]
    assert len(headlines) == 5
    first = headlines[0]
    assert first["title"].startswith(" ".join(words[:20]))
    assert len(first["title"].split()) == 20
    assert "Word21" not in first["title"]
    assert first["url"] == "https://stockanalysis.com/stocks/aapl/news/story-0"
    assert "2026-11-20" in str(first["date"])
    assert headlines[1]["title"] == "Apple reports record quarter 1"
    assert headlines[1]["url"] == "https://stockanalysis.com/stocks/aapl/news/story-1"
    assert "2026" in str(headlines[1]["date"])
    assert [item["url"] for item in headlines] == [f"https://stockanalysis.com/stocks/aapl/news/story-{index}" for index in range(5)]


def test_parse_insider_parses_table_and_raises_on_no_trades() -> None:
    table = """
    <table>
      <tr><td>Date</td><td>Insider</td><td>Transaction</td><td>Shares</td><td>Price</td><td>Value</td></tr>
      <tr><td>2026-11-18</td><td>Jane Smith</td><td>Buy</td><td>1,000</td><td>$150.25</td><td>$150,250</td></tr>
      <tr><td>2026-11-10</td><td>John Doe</td><td>Sale</td><td>500</td><td>$148.00</td><td>$74,000</td></tr>
    </table>
    """
    parsed = parse_insider(table)
    trades = parsed["insiderTrades"]
    assert len(trades) == 2
    assert trades[0] == {"date": "2026-11-18", "insider": "Jane Smith", "type": "buy", "shares": 1000, "price": 150.25, "value": 150250}
    assert trades[1] == {"date": "2026-11-10", "insider": "John Doe", "type": "sell", "shares": 500, "price": 148.0, "value": 74000}
    rows = "".join(
        f"<tr><td>2026-11-{day:02d}</td><td>Insider {day}</td><td>Buy</td><td>100</td><td>$10.00</td><td>$1,000</td></tr>"
        for day in range(1, 13)
    )
    assert len(parse_insider(f"<table>{rows}</table>")["insiderTrades"]) == 10
    try:
        parse_insider("<table><tr><td>Date</td><td>Insider</td></tr></table>")
    except (RuntimeError, ValueError):
        pass
    else:
        raise AssertionError("insider parser accepted a page with no trades")


def test_search_symbols_returns_yahoo_matches() -> None:
    payload = {
        "quotes": [
            {"symbol": "AAPL", "shortname": "Apple Inc.", "longname": "Apple Inc.", "exchange": "NMS", "exchDisp": "NASDAQ", "quoteType": "EQUITY"},
            {"symbol": "MSFT", "shortname": "Microsoft Corporation", "longname": "Microsoft Corporation", "exchange": "NMS", "exchDisp": "NASDAQ", "quoteType": "EQUITY"},
        ]
    }
    seen: list[str] = []

    def getter(url: str) -> str:
        seen.append(url)
        return __import__("json").dumps(payload)

    results = search_symbols("AAPL", getter)
    assert "v1/finance/search" in seen[0]
    assert "q=AAPL" in seen[0]
    assert [row["symbol"] for row in results] == ["AAPL", "MSFT"]
    assert [row["name"] for row in results] == ["Apple Inc.", "Microsoft Corporation"]
    assert [row["exchange"] for row in results] == ["NMS", "NMS"]


def _chart_body(stamps: list[int], closes: list[float], highs: list[float] | None = None, lows: list[float] | None = None) -> str:
    return __import__("json").dumps(
        {
            "chart": {
                "result": [
                    {
                        "meta": {"regularMarketPrice": closes[-1], "shortName": "Example"},
                        "timestamp": stamps,
                        "indicators": {"quote": [{"close": closes, "high": highs if highs is not None else closes, "low": lows if lows is not None else closes}]},
                    }
                ]
            }
        }
    )


def test_fetch_candles_returns_daily_points() -> None:
    stamps = [int(datetime(2026, 11, day, tzinfo=timezone.utc).timestamp()) for day in (18, 19, 20)]
    seen: list[str] = []

    def getter(url: str) -> str:
        seen.append(url)
        return _chart_body(stamps, [10, 11, 12], [10.5, 11.5, 12.5], [9.5, 10.5, 11.5])

    candles = fetch_candles("AAPL", getter=getter)
    assert "range=5y" in seen[0] and "interval=1d" in seen[0]
    assert len(candles) == 3
    assert [candle["date"] for candle in candles] == ["2026-11-18", "2026-11-19", "2026-11-20"]
    assert [candle["close"] for candle in candles] == [10, 11, 12]
    assert [candle["high"] for candle in candles] == [10.5, 11.5, 12.5]
    assert [candle["low"] for candle in candles] == [9.5, 10.5, 11.5]
    fetch_candles("AAPL", interval="1h", span="5d", getter=getter)
    assert "interval=1h" in seen[-1] and "range=5d" in seen[-1]


def test_fetch_news_rss_caps_at_five_and_returns_empty_on_failure() -> None:
    items = "".join(
        f"<item><title><![CDATA[Market news {number}]]></title><link>https://example.com/news/{number}</link>"
        f"<pubDate>Mon, 23 Nov 2026 10:00:00 GMT</pubDate></item>"
        for number in range(1, 7)
    )
    rss = f'<?xml version="1.0"?><rss version="2.0"><channel>{items}</channel></rss>'
    seen: list[str] = []

    def getter(url: str) -> str:
        seen.append(url)
        return rss

    news = fetch_news_rss("US500", getter)
    assert "news.google.com/rss/search" in seen[0]
    assert "q=US500" in seen[0]
    assert len(news) == 5
    assert [item["title"] for item in news] == [f"Market news {number}" for number in range(1, 6)]
    assert news[0]["url"] == "https://example.com/news/1"
    assert "2026" in str(news[0]["date"])

    def fail(url: str) -> str:
        raise RuntimeError("Feed could not be reached; try again later")

    assert fetch_news_rss("US500", fail) == []


def test_parse_yahoo_chart_keeps_about_1300_closes() -> None:
    stamps = [int(datetime(2021, 1, 1, tzinfo=timezone.utc).timestamp()) + index * 86400 for index in range(1400)]
    parsed = parse_yahoo_chart(_chart_body(stamps, [float(index + 1) for index in range(1400)]), "AAPL")
    assert len(parsed["closes"]) == 1300
    assert len(parsed["closeDates"]) == 1300
    assert parsed["closes"][0] == 101
    assert parsed["closes"][-1] == 1400
    short = parse_yahoo_chart(_chart_body(stamps[:6], [10, 11, 12, 13, 14, 16]), "AAPL")
    assert len(short["closes"]) == 6


def test_sma_returns_last_period_average() -> None:
    assert sma([1, 2, 3, 4, 5], 3) == 4.0
    assert sma([10, 20, 30], 2) == 25.0
    assert sma([1, 2], 5) is None


def _trend_candles(closes: list[float]) -> list[dict]:
    return [
        {"date": f"2026-11-{index + 1:02d}", "close": close, "high": close + 1, "low": close - 1}
        for index, close in enumerate(closes)
    ]


def test_aggregate_4h_groups_four_hourly_candles() -> None:
    hourly = [
        {"date": f"2026-11-26T{9 + hour:02d}:00:00", "close": float(10 + hour), "high": float(11 + hour), "low": float(9 + hour)}
        for hour in range(8)
    ]
    grouped = aggregate_4h(hourly)
    assert len(grouped) == 2
    assert grouped[0]["date"] == "2026-11-26T12:00:00"
    assert grouped[0]["close"] == 13 and grouped[0]["high"] == 14 and grouped[0]["low"] == 9
    assert grouped[1]["date"] == "2026-11-26T16:00:00"
    assert grouped[1]["close"] == 17 and grouped[1]["high"] == 18 and grouped[1]["low"] == 13
    assert len(aggregate_4h(hourly[:5])) == 1


def test_macro_trend_for_labels() -> None:
    bullish = macro_trend_for(_trend_candles([float(100 + index) for index in range(25)]))
    assert bullish["label"] == "Bullish"
    assert bullish["aboveSma20"] is True
    assert abs(bullish["changePct"] - (124 / 123 - 1) * 100) < 1e-9
    bearish = macro_trend_for(_trend_candles([float(124 - index) for index in range(25)]))
    assert bearish["label"] == "Bearish"
    assert bearish["aboveSma20"] is False
    assert abs(bearish["changePct"] - (100 / 101 - 1) * 100) < 1e-9
    up_below_average = macro_trend_for(_trend_candles([130.0] * 20 + [120, 115, 110, 108, 112]))
    assert up_below_average["label"] == "Mixed"
    assert up_below_average["aboveSma20"] is False
    down_above_average = macro_trend_for(_trend_candles([100.0] * 20 + [120, 125, 130, 135, 132]))
    assert down_above_average["label"] == "Mixed"
    assert down_above_average["aboveSma20"] is True
    short = macro_trend_for(_trend_candles([10, 11, 12, 13, 14]))
    assert short["label"] == "Unavailable"
    assert isinstance(short["note"], str)


def test_compute_macro_spider_crowded_not_broken() -> None:
    # Technical 7: daily share 2/4 x4 (=2) + weekly 4/4 x3 (=3) + 4-hour 0/4 x1 (=0)
    # + breadth net (27-5)/100 = 0.22 mapped to the full 2 points. Sentiment 8:
    # crowded share 27/100 mapped to 4.5 + daily 2/4 x3 (=1.5) + weekly 4/4 x2 (=2).
    # Fundamental 6: 6 of 10 desk snapshots are cheap (forward P/E < 20) and
    # profitable (EPS > 0); the other 4 are neither.
    def instrument(label: str, daily: str, weekly: str, four_hour: str) -> dict:
        return {"label": label, "daily": {"label": daily}, "weekly": {"label": weekly}, "four_hour": {"label": four_hour}}

    instruments = [
        instrument("US500", "Bullish", "Bullish", "Bearish"),
        instrument("US100", "Bullish", "Bullish", "Bearish"),
        instrument("UK100", "Bearish", "Bullish", "Bearish"),
        instrument("GER30", "Bearish", "Bullish", "Bearish"),
    ]
    breadth = [
        {"highs": 27, "lows": 5, "total": 100},
        {"highs": 27, "lows": 5, "total": 100},
    ]
    snapshots = [{"forwardPE": 15, "eps": 2.0}] * 6 + [{"forwardPE": 40, "eps": -1.0}] * 4
    spider = compute_macro_spider(instruments, breadth, snapshots)
    scores = {axis["axis"]: axis["score"] for axis in spider["axes"]}
    assert [axis["axis"] for axis in spider["axes"]] == ["Technical", "Sentiment", "Fundamental"]
    assert scores == {"Technical": 7, "Sentiment": 8, "Fundamental": 6}
    for axis in spider["axes"]:
        assert axis["score"] is None or 0 <= axis["score"] <= 10
        assert isinstance(axis["note"], str)
    assert spider["verdict"] == "Crowded, not broken"
    assert isinstance(spider["verdict_note"], str) and spider["verdict_note"]


def test_compute_macro_spider_has_no_scores_without_inputs() -> None:
    spider = compute_macro_spider([], [], [])
    assert {axis["axis"]: axis["score"] for axis in spider["axes"]} == {"Technical": None, "Sentiment": None, "Fundamental": None}
    assert isinstance(spider["verdict"], str) and spider["verdict"]
    assert isinstance(spider["verdict_note"], str)


def test_return_over_days_is_date_anchored() -> None:
    snapshot = {"closes": [float(day) for day in range(1, 31)], "closeDates": [f"2026-10-{day:02d}" for day in range(1, 31)]}
    assert abs(_return_over_days(snapshot, 7) - (30 / 23 - 1) * 100) < 1e-9
    assert abs(_return_over_days(snapshot, 29) - (30 / 1 - 1) * 100) < 1e-9
    short = {"closes": [10, 12], "closeDates": ["2026-10-29", "2026-10-30"]}
    assert _return_over_days(short, 90) is None


def test_snapshot_fetched_at_and_is_fresh() -> None:
    now = datetime.now(timezone.utc)

    def stamp(moment: datetime) -> str:
        return moment.strftime("%Y-%m-%dT%H:%M:%SZ")

    recent = {"quoteFetchedAt": stamp(now - timedelta(minutes=1)), "attemptedAt": stamp(now - timedelta(minutes=30))}
    assert _snapshot_fetched_at(recent) == (now - timedelta(minutes=1)).replace(microsecond=0)
    attempted_only = {"attemptedAt": stamp(now - timedelta(minutes=2))}
    assert _snapshot_fetched_at(attempted_only) == (now - timedelta(minutes=2)).replace(microsecond=0)
    assert _snapshot_fetched_at({}) is None
    assert _is_fresh(recent) is True
    assert _is_fresh(attempted_only) is True
    old = {"quoteFetchedAt": stamp(now - timedelta(minutes=10))}
    assert _is_fresh(old) is False
    assert _is_fresh(old, minutes=15) is True


def test_quote_cache_round_trips_theses() -> None:
    cache = ROOT / "tests" / "_quote_cache_theses.json"
    payload = {
        "refreshed": {"USAR": {"ticker": "USAR", "price": 21.5}},
        "added": {},
        "refresh_at": "2026-11-10T09:40:00Z",
        "errors": [],
        "theses": {"USAR": "Rare-earth supply-chain upside, with funding discipline", "NVO": "A profitable medical franchise after an expectations reset"},
    }
    save_quote_cache(payload, cache)
    loaded = load_quote_cache(cache)
    assert loaded["theses"] == payload["theses"]
    assert loaded["refreshed"]["USAR"]["price"] == 21.5
    assert loaded["refresh_at"] == "2026-11-10T09:40:00Z"
    cache.unlink()
    save_quote_cache({"refreshed": {}, "added": {}, "refresh_at": None, "errors": []}, cache)
    assert load_quote_cache(cache)["theses"] == {}
    cache.unlink()


def test_add_search_is_one_box() -> None:
    """Adding a ticker is one box: ticker or company name, not two boxes."""
    page = (ROOT / "research_desk_page.py").read_text(encoding="utf-8")
    assert 'Add a ticker — search by ticker or company name' in page
    assert 'st.text_input("Add a ticker"' not in page
    assert 'st.text_input("Search by company name"' not in page
    assert "desk_company_search" not in page
    # The watchlist filter is a different box and must stay.
    assert 'st.text_input("Search watchlist"' in page
    assert "_run_add_search" in page
    assert "search_symbols" in page


def test_trading_edge_page_remains_the_default() -> None:
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert 'st.title("Validated Trading Edge Dashboard")' in source
    assert 'title="Trading Edge"' in source
    assert "default=True" in source
    assert 'title="Research Desk"' in source
    assert "def main() -> None:" in source


if __name__ == "__main__":
    test_seed_tickers_and_missing_forward_pe()
    test_upside_matches_repo_formula()
    test_missing_squeeze_input_stays_unknown()
    test_seed_squeeze_counts()
    test_thesis_text_is_the_repo_playbook()
    test_valuation_sentence_uses_stored_numbers_only()
    test_daily_and_weekly_trends_use_stored_series()
    test_added_snapshot_uses_only_returned_fields()
    test_refresh_quote_updates_price_and_keeps_fundamentals()
    test_macro_trends_follow_the_desk_rules()
    test_breadth_uses_published_highs_and_lows_only()
    test_parse_headlines_caps_at_five_and_truncates_titles()
    test_parse_insider_parses_table_and_raises_on_no_trades()
    test_search_symbols_returns_yahoo_matches()
    test_fetch_candles_returns_daily_points()
    test_fetch_news_rss_caps_at_five_and_returns_empty_on_failure()
    test_parse_yahoo_chart_keeps_about_1300_closes()
    test_sma_returns_last_period_average()
    test_aggregate_4h_groups_four_hourly_candles()
    test_macro_trend_for_labels()
    test_compute_macro_spider_crowded_not_broken()
    test_compute_macro_spider_has_no_scores_without_inputs()
    test_return_over_days_is_date_anchored()
    test_snapshot_fetched_at_and_is_fresh()
    test_quote_cache_round_trips_theses()
    test_trading_edge_page_remains_the_default()
    test_add_search_is_one_box()
    print("Research desk snapshot checks passed.")
