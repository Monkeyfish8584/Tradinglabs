"""Macro Desk checks: the Research Desk is replaced, per the spec.

Pure-function checks for the spec's EMA50 trend, breadth definitions,
event-to-index mapping and 7-day calendar, plus source checks that the
old desk's thesis / CANSLIM / spider / insider / squeeze code is gone
and the Data Hub is untouched. Reused provider checks (headlines,
symbol search, candles, news RSS, Yahoo chart) still apply.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from datetime import date, datetime, timedelta, timezone

from research_desk_page import (
    EVENT_INDEX_MAP,
    MACRO_INDICES,
    MACRO_THEME_CSS,
    TREND_EMA_PERIOD,
    _link_with_theme,
    _macro_css,
    _normalize_theme,
    _theme_query_value,
    affected_indices,
    breadth_summary,
    session_extreme,
    _strip_card,
    calendar_days,
    constituent_symbols,
    event_notes,
    sma,
)
from research_desk_quotes import (
    ema_series,
    fetch_candles,
    fetch_news_rss,
    fetch_red_folder_events,
    parse_ff_calendar,
    parse_headlines,
    parse_yahoo_chart,
    search_symbols,
    trend_from_closes,
    weekly_closes_from_daily,
)


def test_macro_indices_are_five_in_spec_order() -> None:
    assert [item["id"] for item in MACRO_INDICES] == ["dax", "uk100", "ndx", "dow", "spx"]
    assert [item["label"] for item in MACRO_INDICES] == ["DAX", "UK100", "US100", "US30", "US500"]
    assert [item["currency"] for item in MACRO_INDICES] == ["EUR", "GBP", "USD", "USD", "USD"]
    assert TREND_EMA_PERIOD == 50


def test_ema_trend_bullish_when_above_rising_ema() -> None:
    rising = [100.0 + index * 0.5 for index in range(80)]
    assert trend_from_closes(rising, 50) == "Bullish"
    falling = [140.0 - index * 0.5 for index in range(80)]
    assert trend_from_closes(falling, 50) == "Bearish"
    assert trend_from_closes([100.0] * 10, 50) is None
    series = ema_series([100.0] * 60, 50)
    assert series is not None and len(series) == 11
    assert series[0] == 100.0


def test_weekly_closes_group_by_iso_week() -> None:
    dates = ["2026-11-23", "2026-11-24", "2026-11-25", "2026-11-30", "2026-12-01"]
    closes = [10.0, 11.0, 12.0, 13.0, 14.0]
    assert weekly_closes_from_daily(dates, closes) == [12.0, 14.0]


def test_breadth_summary_counts_per_spec() -> None:
    per_symbol = [
        {"above50": True, "new_high": True},
        {"above50": True, "new_high": False},
        {"above50": False, "new_high": False},
        None,
        {"above50": None, "new_high": None},
    ]
    summary = breadth_summary("dax", per_symbol)
    assert summary["above50"] == 2
    assert summary["new_highs"] == 1
    assert summary["new_lows"] == 0
    assert summary["measured"] == 3
    assert summary["unknown"] == 2
    assert summary["listed"] == 5
    assert summary["ready"] is True
    assert breadth_summary("dax", [None, None])["ready"] is False
    outside = [
        {"above50": True, "new_high": True, "new_low": False},
        {"above50": False, "new_high": False, "new_low": True},
        {"above50": True, "new_high": True, "new_low": True},
    ]
    both = breadth_summary("spx", outside)
    assert both["new_highs"] == 2
    assert both["new_lows"] == 2
    assert both["above50"] == 2


def test_session_extreme_compares_the_previous_session() -> None:
    new_high, new_low = session_extreme({"high": 10, "low": 8}, {"high": 9, "low": 7})
    assert new_high is True and new_low is False
    new_high, new_low = session_extreme({"high": 9, "low": 6}, {"high": 9, "low": 7})
    assert new_high is False and new_low is True
    new_high, new_low = session_extreme({"high": 11, "low": 5}, {"high": 10, "low": 6})
    assert new_high is True and new_low is True
    new_high, new_low = session_extreme({"high": None, "low": 4}, {"high": 8, "low": 5})
    assert new_high is False and new_low is True
    assert session_extreme(None, {"high": 1, "low": 1}) == (False, False)


def test_strip_card_shows_the_lows_gauge() -> None:
    item = next(entry for entry in MACRO_INDICES if entry["id"] == "dax")
    data = {
        "available": True,
        "change_pct": 0.42,
        "weekly_trend": "Bullish",
        "daily_trend": "Bullish",
        "four_hour_trend": "Bearish",
        "breadth": {"ready": True, "listed": 40, "above50": 27, "new_highs": 9, "new_lows": 3},
    }
    card = _strip_card(item, data, False)
    assert "Lows" in card
    assert "3/40" in card
    assert "9/40" in card
    assert "27/40" in card
    assert "new low vs the previous day" in card


def test_event_index_mapping_per_spec() -> None:
    assert EVENT_INDEX_MAP["EUR"] == ("dax",)
    assert EVENT_INDEX_MAP["GBP"] == ("uk100",)
    assert EVENT_INDEX_MAP["USD"] == ("ndx", "dow", "spx")
    assert affected_indices({"country": "EUR", "title": "German prelim CPI m/m"}) == ["dax"]
    assert affected_indices({"country": "GBP", "title": "UK CPI"}) == ["uk100"]
    assert affected_indices({"country": "USD", "title": "ISM manufacturing PMI"}) == ["ndx", "dow", "spx"]
    # Major US events also affect DAX (spec 3.2, optional).
    assert "dax" in affected_indices({"country": "USD", "title": "Fed Beige Book"})


def test_calendar_days_is_seven_with_weekends() -> None:
    calendar = {"events": [], "available": True, "partial": False}
    days = calendar_days(calendar, today=date(2026, 11, 26))
    assert len(days) == 7
    assert [day["date"].isoformat() for day in days] == [
        "2026-11-26", "2026-11-27", "2026-11-28", "2026-11-29",
        "2026-11-30", "2026-12-01", "2026-12-02",
    ]
    assert [day["weekend"] for day in days] == [False, False, True, True, False, False, False]
    assert all(day["events"] == [] for day in days)


def test_red_folder_events_are_high_impact_only() -> None:
    payload = [
        {"title": "CPI", "country": "USD", "date": "2026-12-01T13:30:00-05:00", "impact": "High", "forecast": "3.1%", "previous": "3.0%", "actual": ""},
        {"title": "Retail Sales", "country": "USD", "date": "2026-12-01T13:30:00-05:00", "impact": "Medium", "forecast": "", "previous": "", "actual": ""},
    ]
    events = parse_ff_calendar(payload)
    assert len(events) == 1
    assert events[0]["title"] == "CPI"
    assert events[0]["forecast"] == "3.1%"
    assert events[0]["actual"] == ""

    def getter(url: str) -> str:
        return __import__("json").dumps(payload)

    result = fetch_red_folder_events(getter=getter, now=datetime(2026, 11, 26, tzinfo=timezone.utc))
    assert result["available"] is True
    assert len(result["events"]) == 1


def test_event_notes_are_generic_not_invented() -> None:
    expected, reaction = event_notes("German prelim CPI m/m")
    assert "inflation" in expected.lower()
    assert "3.1%" not in expected and "3.1%" not in reaction
    expected, _ = event_notes("Something nobody has named")
    assert expected.startswith("What it measures: a high-impact economic release.")


def test_macro_desk_replaces_research_desk() -> None:
    page = (ROOT / "research_desk_page.py").read_text(encoding="utf-8")
    assert "Macro Desk" in page
    assert "render_macro_desk" in page
    # Old desk features are gone: thesis, spider, insider, squeeze, playbooks.
    for gone in ("compute_stock_spider", "thesis_for", "parse_insider", "squeeze_checks", "THESES", "SQUEEZE_RULES", "_spider_svg"):
        assert gone not in page, gone
    assert "Crypto" not in page or "Crypto has no" in page
    # Spec columns and placeholder are present.
    for wanted in ("Analyst target", "Fwd P/E", "50MA", "200MA", "Weekly", "Daily", "Your watchlist is empty", "Import X sentiment", "Insider transactions", "Seasonality"):
        assert wanted in page, wanted
    assert "To be designed – coming soon" not in page


def test_app_has_macro_desk_and_untouched_data_hub() -> None:
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert 'title="Macro Desk"' in source
    assert 'title="Research Desk"' not in source
    assert 'title="Trading Edge"' in source
    assert "default=True" in source
    assert 'st.title("Validated Trading Edge Dashboard")' in source
    assert "DATA_DIR" in source and "data" in source.lower()


def test_macro_theme_has_explicit_light_and_dark_palettes() -> None:
    # Regression test for 2026-11-26: Light mode stayed dark because there
    # was no explicit light theme — only a dark card style was injected.
    # Both themes must now inject a full explicit palette, light first.
    assert set(MACRO_THEME_CSS) == {"Light", "Dark"}
    light = MACRO_THEME_CSS["Light"]
    dark = MACRO_THEME_CSS["Dark"]
    assert light != dark
    assert "color-scheme: light" in light
    assert "color-scheme: dark" in dark
    # Light is genuinely light: pale page background, white cards, dark text.
    assert "#f8fafc" in light and "#ffffff" in light and "#111827" in light
    # Dark is genuinely dark: dark page background, dark cards, light text.
    assert "#0f172a" in dark and "#1e293b" in dark and "#f1f5f9" in dark
    # The combined CSS is base + chosen theme, theme last so it wins.
    assert _macro_css("Light").endswith(light)
    assert _macro_css("Dark").endswith(dark)
    assert _macro_css() == _macro_css("Light")


def test_macro_theme_persists_across_pages() -> None:
    # Regression test for 2026-11-26: the theme reset to Light on every
    # page change (e.g. clicking a stock to its placeholder page). The
    # choice lived only in session state, but stock/index links are plain
    # <a href="?stock=..."> / "?index=..." anchors — a full browser
    # reload that starts a new Streamlit session, losing session state.
    # The fix carries the theme in the URL as theme=dark|light, the
    # Streamlit equivalent of the preview fix.
    assert _normalize_theme("dark") == "Dark"
    assert _normalize_theme("Dark") == "Dark"
    assert _normalize_theme("LIGHT") == "Light"
    assert _normalize_theme("banana") is None
    assert _normalize_theme(None) is None
    assert _normalize_theme(["dark"]) == "Dark"
    assert _theme_query_value("Dark") == "dark"
    assert _theme_query_value("Light") == "light"
    assert _theme_query_value(None) == "light"
    # Outside a Streamlit run the current theme is Light, so links carry it.
    assert _link_with_theme("index=dax") == "?index=dax&theme=light"
    assert _link_with_theme("stock=SAP") == "?stock=SAP&theme=light"
    page = (ROOT / "research_desk_page.py").read_text(encoding="utf-8")
    # The desk reads the theme from the URL and syncs it at the top of
    # render_macro_desk, and every navigation link carries it.
    assert "_sync_theme()" in page
    assert "_theme_from_query_params" in page
    assert "_link_with_theme(f\"index={item['id']}\")" in page
    assert "_link_with_theme(\"stock=\" + urllib.parse.quote(ticker))" in page
    # Back buttons keep the theme instead of wiping the query params:
    # no live st.query_params.clear() call remains (only a docstring
    # mention of why it is not used).
    assert "\n        st.query_params.clear()" not in page
    assert "_clear_macro_route()" in page


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
    assert len(headlines[0]["title"].split()) == 20
    assert "Word21" not in headlines[0]["title"]


def test_search_symbols_returns_yahoo_matches() -> None:
    payload = {
        "quotes": [
            {"symbol": "AAPL", "shortname": "Apple Inc.", "longname": "Apple Inc.", "exchange": "NMS", "exchDisp": "NASDAQ", "quoteType": "EQUITY"},
            {"symbol": "MSFT", "shortname": "Microsoft Corporation", "longname": "Microsoft Corporation", "exchange": "NMS", "exchDisp": "NASDAQ", "quoteType": "EQUITY"},
        ]
    }

    def getter(url: str) -> str:
        return __import__("json").dumps(payload)

    results = search_symbols("AAPL", getter)
    assert [row["symbol"] for row in results] == ["AAPL", "MSFT"]


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

    def getter(url: str) -> str:
        return _chart_body(stamps, [10, 11, 12], [10.5, 11.5, 12.5], [9.5, 10.5, 11.5])

    candles = fetch_candles("AAPL", getter=getter)
    assert [candle["close"] for candle in candles] == [10, 11, 12]
    assert [candle["high"] for candle in candles] == [10.5, 11.5, 12.5]


def test_fetch_news_rss_caps_at_five_and_returns_empty_on_failure() -> None:
    items = "".join(
        f"<item><title><![CDATA[Market news {number}]]></title><link>https://example.com/news/{number}</link>"
        f"<pubDate>Mon, 23 Nov 2026 10:00:00 GMT</pubDate></item>"
        for number in range(1, 7)
    )
    rss = f'<?xml version="1.0"?><rss version="2.0"><channel>{items}</channel></rss>'

    def getter(url: str) -> str:
        return rss

    news = fetch_news_rss("US500", getter)
    assert len(news) == 5
    assert news[0]["url"] == "https://example.com/news/1"

    def fail(url: str) -> str:
        raise RuntimeError("Feed could not be reached; try again later")

    assert fetch_news_rss("US500", fail) == []


def test_parse_yahoo_chart_keeps_about_1300_closes() -> None:
    stamps = [int(datetime(2021, 1, 1, tzinfo=timezone.utc).timestamp()) + index * 86400 for index in range(1400)]
    parsed = parse_yahoo_chart(_chart_body(stamps, [float(index + 1) for index in range(1400)]), "AAPL")
    assert len(parsed["closes"]) == 1300
    assert parsed["closes"][0] == 101


def test_sma_returns_last_period_average() -> None:
    assert sma([1, 2, 3, 4, 5], 3) == 4.0


def test_grok_import_files_blocks_and_skips_unknown_names() -> None:
    from macro_desk_insights import parse_grok_import

    text = """
SUBJECT: US100
TONE: bullish
SCORE: 140
SUMMARY: Buyers are defending the open.
POST: @desk | bullish | Still bid above the 50. | https://x.com/desk/status/1
POST: @other | bearish | Too extended for me.
---
SUBJECT: Not A Real Name
TONE: bearish
SCORE: -20
SUMMARY: Ignored.
POST: @x | bearish | Skip.
"""
    parsed = parse_grok_import(text, {"nvda": "NVDA"})
    assert parsed["unknown"] == ["Not A Real Name"]
    assert len(parsed["items"]) == 1
    item = parsed["items"][0]
    assert item["subject"] == "ndx"
    assert item["score"] == 100
    assert item["tone"] == "bullish"
    assert item["posts"][0]["link"] == "https://x.com/desk/status/1"
    assert item["posts"][1]["link"] == ""
    named = parse_grok_import("SUBJECT: NVIDIA\nTONE: neutral\nSCORE: 4\nSUMMARY: Quiet.\nPOST: @a | neutral | Waiting.\n", {"nvidia": "NVDA"})
    assert named["items"][0]["subject"] == "NVDA"


def test_sentiment_score_uses_the_published_weights_and_a_minimum() -> None:
    from macro_desk_insights import score_day, sentiment_view

    both = score_day(50, 3, -10, 3)
    assert both["score"] == 0.6 * 50 + 0.4 * -10
    assert both["low_volume"] is False
    social_only = score_day(None, 0, 20, 3)
    assert social_only["score"] == 20 and social_only["low_volume"] is True
    assert score_day(None, 0, 20, 2)["score"] is None
    history = {}
    for offset, score in enumerate([10, 10, 10, 0, 0, 0, 0, 30, 30, 30]):
        day = date(2026, 11, 17) + timedelta(days=offset)
        history[day.isoformat()] = {"score": score, "posts": [{}, {}, {}], "summary": "saved", "tone": "bullish"}
    view = sentiment_view(history, date(2026, 11, 26))
    assert view["score"] == 30
    assert view["label"] == "Improving"
    assert view["change"] == 20
    quiet = sentiment_view(
        {
            "2026-11-24": {"score": 10, "posts": [{}, {}, {}]},
            "2026-11-25": {"score": 10, "posts": [{}, {}, {}]},
            "2026-11-26": {"score": 12, "posts": [{}, {}, {}]},
            "2026-11-17": {"score": 10, "posts": [{}, {}, {}]},
            "2026-11-18": {"score": 10, "posts": [{}, {}, {}]},
            "2026-11-19": {"score": 10, "posts": [{}, {}, {}]},
        },
        date(2026, 11, 26),
    )
    assert quiet["label"] is None


def test_seasonality_uses_published_closes_only() -> None:
    from macro_desk_insights import seasonality_from_candles

    candles = []
    for year, start in ((2024, 100.0), (2025, 80.0), (2026, 50.0)):
        for month, close in ((1, start), (6, start * 1.1), (11, start * 1.2)):
            candles.append({"date": f"{year}-{month:02d}-15", "close": close})
    candles.append({"date": "2026-12-15", "close": 90.0})
    report = seasonality_from_candles(candles, date(2026, 11, 26))
    assert round(report["summary"]["2026"], 4) == 20
    assert report["as_of"] == "2026-11-15"
    assert report["monthly"]["2026"][11] is None
    assert report["monthly"]["2026"][10] is not None
    assert report["monthly"]["2024"][10] is not None
    assert all(value is None or isinstance(value, float) for value in report["average"])


def test_form4_keeps_open_market_buys_separate_from_awards() -> None:
    from macro_desk_insights import form4_xml_name, insider_summary, parse_form4

    assert form4_xml_name(["xslF345X06/form4.xml", "form4.xml"], "xslF345X06/form4.xml") == "form4.xml"

    xml = """
    <ownershipDocument>
      <reportingOwner><reportingOwnerId><rptOwnerName>Ada Lovelace</rptOwnerName></reportingOwnerId>
      <reportingOwnerRelationship><officerTitle>CFO</officerTitle></reportingOwnerRelationship></reportingOwner>
      <nonDerivativeTable>
        <nonDerivativeTransaction>
          <transactionDate><value>2026-11-20</value></transactionDate>
          <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
          <transactionAmounts>
            <transactionShares><value>100</value></transactionShares>
            <transactionPricePerShare><value>10</value></transactionPricePerShare>
          </transactionAmounts>
        </nonDerivativeTransaction>
        <nonDerivativeTransaction>
          <transactionDate><value>2026-11-01</value></transactionDate>
          <transactionCoding><transactionCode>A</transactionCode></transactionCoding>
          <transactionAmounts>
            <transactionShares><value>50</value></transactionShares>
            <transactionPricePerShare><value>0</value></transactionPricePerShare>
          </transactionAmounts>
        </nonDerivativeTransaction>
      </nonDerivativeTable>
    </ownershipDocument>
    """
    trades = parse_form4(xml, "2026-11-22")
    assert [trade["type"] for trade in trades] == ["buy", "other"]
    assert trades[0]["person"] == "Ada Lovelace"
    assert trades[0]["value"] == 1000
    summary = insider_summary(trades, date(2026, 11, 26))
    assert summary["buys"] == 1
    assert summary["insider_buying"] is True
    assert summary["net_value"] == 1000


def test_insider_net_stays_unknown_until_every_trade_has_a_price() -> None:
    from macro_desk_insights import insider_summary, is_form4, sec_symbol

    trades = [
        {"person": "A", "type": "sell", "traded_at": "2026-11-20", "value": 100, "filed_at": "2026-11-21"},
        {"person": "A", "type": "buy", "traded_at": "2026-11-18", "value": None, "filed_at": "2026-11-19"},
    ]
    summary = insider_summary(trades, date(2026, 11, 26))
    assert summary["net_value"] is None
    assert summary["buys"] == 1 and summary["sells"] == 1
    assert summary["insider_buying"] is False
    assert sec_symbol("BRK.B") == "BRK-B"
    assert sec_symbol("brk-b") == "BRK-B"
    assert sec_symbol("SAP.DE") is None
    assert sec_symbol("^GSPC") is None
    assert is_form4("4/A") and is_form4("4")
    assert not is_form4("8-K")


def test_form4_amendment_replaces_the_original_rows() -> None:
    from macro_desk_insights import insider_summary

    original = {"person": "Ada Lovelace", "type": "sell", "traded_at": "2026-11-16", "filed_at": "2026-11-18", "value": 1000, "amended": False, "period": "2026-11-16"}
    extra = {"person": "Ada Lovelace", "type": "sell", "traded_at": "2026-11-15", "filed_at": "2026-11-18", "value": 400, "amended": False, "period": "2026-11-16"}
    amended = {"person": "Ada Lovelace", "type": "sell", "traded_at": "2026-11-16", "filed_at": "2026-11-20", "value": 50, "amended": True, "period": "2026-11-16"}
    later = {"person": "Ada Lovelace", "type": "buy", "traded_at": "2026-11-22", "filed_at": "2026-11-24", "value": 10, "amended": False, "period": "2026-11-22"}
    summary = insider_summary([original, extra, amended, later], date(2026, 11, 26))
    assert sorted(trade["value"] for trade in summary["trades"]) == [10, 50]
    assert summary["net_value"] == -40


def test_price_figure_is_fixed_size_with_range_buttons() -> None:
    import research_desk_page as page

    dates = [(date(2021, 11, 26) + timedelta(days=i)).isoformat() for i in range(1300)]
    closes = [100.0 + i * 0.1 for i in range(1300)]
    fig = page.build_price_figure(dates, closes, "Light")
    assert fig.layout.height == page.CHART_HEIGHT == 340
    assert fig.data[1].marker.size == 9 and len(fig.data[1].x) == 1
    labels = [b.label for b in fig.layout.xaxis.rangeselector.buttons]
    assert labels == ["1M", "6M", "1Y", "3Y", "5Y"]
    start, end = fig.layout.xaxis.range
    assert 360 <= (end - start).days <= 370
    assert page.build_price_figure(dates[:1], closes[:1], "Light") is None
    assert page.build_price_figure(dates, [None] * 1300, "Dark") is None


def test_breadth_table_says_yes_or_no_and_index_page_has_no_red_folder_list() -> None:
    import inspect
    import research_desk_page as page

    assert page._yes_no(True) == "Yes" and page._yes_no(False) == "No" and page._yes_no(None) == "No"
    body = inspect.getsource(page.render_index_page)
    assert "\u25cf" not in body and "\u25cb" not in body
    assert "render_red_folder_list" not in body
    assert "news_col, breadth_col = st.columns" in body


def test_one_search_box_suggests_symbols_as_you_type() -> None:
    import research_desk_page as page

    original = page.search_symbols
    try:
        page.search_symbols = lambda q, getter=None: [{"symbol": "NVDA", "name": "NVIDIA Corporation"}, {"symbol": "", "name": "skip"}]
        assert page._suggest_symbols("Nvid") == [("NVDA \u2014 NVIDIA Corporation", "NVDA")]
        assert page._suggest_symbols("N") == []

        def boom(q, getter=None):
            raise RuntimeError("down")

        page.search_symbols = boom
        assert page._suggest_symbols("Nvid") == []
    finally:
        page.search_symbols = original


def test_red_folder_falls_back_to_last_good_feed_and_is_not_cached_when_partial() -> None:
    import json as _json
    import time as _time

    import research_desk_quotes as q

    now = datetime(2026, 11, 27, 7, 0, tzinfo=timezone.utc)
    this_week = _json.dumps([{"title": "Inflation Rate YoY Prel", "country": "FR", "date": "2026-11-27T08:45:00+00:00", "impact": "High", "forecast": "3.4%", "previous": "3.4%", "actual": ""}] * 1 + [{"title": "pad", "country": "XX", "date": "2026-11-27T08:45:00+00:00", "impact": "Low"}] * 5)
    next_week = _json.dumps([{"title": "ISM Manufacturing PMI", "country": "USD", "date": "2026-12-01T10:00:00-05:00", "impact": "High", "forecast": "49.0", "previous": "48.7", "actual": ""}] + [{"title": "pad", "country": "XX", "date": "2026-12-01T10:00:00-05:00", "impact": "Low"}] * 5)
    urls = q.FF_CALENDAR_URLS

    def only_this(url):
        if url == urls[0]:
            return this_week
        raise RuntimeError("Provider rate limit; try again later")

    partial = q.fetch_red_folder_events(getter=only_this, now=now)
    assert partial["partial"] is True and len(partial["events"]) == 1

    # live path: a refused next-week feed reuses its last good copy
    q._FF_STATE.clear()
    original = q.fetch_text
    original_sleep = _time.sleep
    calls = {"n": 0, "fail_next": False}

    def live(url, timeout=16):
        calls["n"] += 1
        if url == urls[1] and calls["fail_next"]:
            raise RuntimeError("Provider rate limit; try again later")
        return this_week if url == urls[0] else next_week

    try:
        q.fetch_text = live
        _time.sleep = lambda s: None
        first = q.fetch_red_folder_events(now=now)
        assert first["partial"] is False and first["stale"] is False and len(first["events"]) == 2
        q._FF_STATE[urls[1]]["ok_at"] -= 10
        q._FF_STATE[urls[0]]["failed_at"] = 0.0
        calls["fail_next"] = True
        second = q.fetch_red_folder_events(now=now)
        assert second["partial"] is False and second["stale"] is True and len(second["events"]) == 2
        before = calls["n"]
        q.fetch_red_folder_events(now=now)
        assert calls["n"] - before == 1  # the refused feed is not hit again straight away
    finally:
        q.fetch_text = original
        _time.sleep = original_sleep
        q._FF_STATE.clear()


def test_seasonality_figure_bridges_gaps_and_counts_months_beating_average() -> None:
    import research_desk_page as page

    labels = ["01-01", "01-02", "01-03", "01-04"]
    report = {
        "years": [2026, 2025, 2024],
        "labels": labels,
        "chart": {"2026": [0.0, None, 2.0, 3.0], "2025": [0.0, 1.0, None, 5.0], "2024": [0.0, 1.0, 2.0, 4.0]},
        "monthly": {"2026": [3.0, -1.0, None], "2025": [1.0, 2.0, 1.0], "2024": [1.0, 0.0, 1.0]},
        "average": [1.0, 1.0, 1.0],
        "average_label": "Avg 2024\u20132025",
    }
    fig = page.build_seasonality_figure(report, "Light")
    lines = [trace for trace in fig.data if trace.mode == "lines"]
    assert len(lines) == 3 and all(trace.connectgaps for trace in lines)
    assert lines[0].line.width > lines[1].line.width
    assert page.months_beating_average(report) == (1, 2)
    assert page.months_beating_average({"years": [], "monthly": {}, "average": []}) is None
    assert page.build_seasonality_figure({"years": [2026], "labels": [], "chart": {}}, "Dark") is None


def test_free_feed_sentiment_scores_headlines_and_hides_x() -> None:
    import json as _json
    import research_desk_page as page
    from macro_desk_insights import auto_sentiment_view, fetch_reddit_posts, score_text, score_texts, tone_of

    assert score_text("Shares surge as profits beat estimates") > 0.5
    assert score_text("Stock plunges after profit warning") < -0.5
    assert score_text("Results did not beat estimates") < 0
    assert score_text("Company holds annual meeting") == 0.0
    assert tone_of(0.5) == "bullish" and tone_of(-0.5) == "bearish" and tone_of(0.0) == "neutral" and tone_of(None) == "neutral"
    assert score_texts([]) == {"score": None, "count": 0}
    assert score_texts(["Shares surge", "Stock plunges"])["score"] == 0.0

    today = date(2026, 11, 27)
    history = {(today - timedelta(days=o)).isoformat(): {"news": 10.0 + o, "news_n": 5, "social": None, "social_n": 0} for o in list(range(1, 3)) + list(range(7, 10))}
    view = auto_sentiment_view(history, today, {"news": 80.0, "news_n": 5, "social": 20.0, "social_n": 4})
    assert view["score"] == 0.6 * 80.0 + 0.4 * 20.0 and view["low_volume"] is False
    assert view["change"] is not None and view["label"] == "Improving"
    thin = auto_sentiment_view({}, today, {"news": 40.0, "news_n": 2, "social": None, "social_n": 0})
    assert thin["score"] is None

    assert fetch_reddit_posts("NVDA", None, None) == {"configured": False, "available": False, "posts": []}
    calls = []

    def fake(url, headers=None, data=None, timeout=16):
        calls.append(url)
        if "access_token" in url:
            return _json.dumps({"access_token": "tok"})
        return _json.dumps({"data": {"children": [{"data": {"title": "NVDA rally continues", "selftext": "", "author": "bob", "subreddit": "stocks", "permalink": "/r/stocks/1"}}, {"data": {"title": "", "author": "x"}}]}})

    got = fetch_reddit_posts("NVDA", "id", "secret", http=fake)
    assert got["available"] and len(got["posts"]) == 1 and got["posts"][0]["author"] == "u/bob"
    assert got["posts"][0]["link"] == "https://www.reddit.com/r/stocks/1" and len(calls) == 2

    def broken(url, headers=None, data=None, timeout=16):
        raise OSError("down")

    assert fetch_reddit_posts("NVDA", "id", "secret", http=broken)["available"] is False
    assert page.SHOW_X_SENTIMENT is False


def test_watchlist_delete_is_a_link_at_the_end_of_each_row_and_removes_the_stock() -> None:
    from streamlit.testing.v1 import AppTest

    def app() -> None:
        import sys

        sys.path.insert(0, str(__import__("os").environ["TL_ROOT"]))
        import research_desk_page as page

        snap = lambda t: {"ticker": t, "name": t + " Inc", "price": 100.0, "currency": "USD", "closes": [90.0] * 60, "closeDates": [], "target": 120.0}
        saved = __import__("builtins").__dict__.setdefault("_wl_saved", [])
        page.load_watchlist_cache = lambda path=None: {"added": {"NVDA": snap("NVDA"), "SAP": snap("SAP")}}
        page.save_watchlist_cache = lambda payload, path=None: saved.append(sorted(payload["added"]))
        page.render_strip = lambda active_id=None: {}
        page.cached_red_folder = lambda *a, **k: {"events": [], "available": True, "partial": False}
        page.render_calendar = lambda *a, **k: None
        page.render_event_detail = lambda *a, **k: None
        page.cached_insider_batch = lambda *a, **k: {}
        page.render_macro_desk()

    import os

    os.environ["TL_ROOT"] = str(ROOT)
    at = AppTest.from_function(app)
    at.run(timeout=60)
    assert not at.exception
    table = next(m.value for m in at.markdown if "md-watchlist" in m.value and "<table" in m.value)
    assert table.count("md-remove") >= 2 and "remove=NVDA" in table and "remove=SAP" in table
    assert not [b for b in at.button if b.label == "\u2715"]

    at2 = AppTest.from_function(app)
    at2.query_params["remove"] = "NVDA"
    at2.run(timeout=60)
    assert not at2.exception
    table2 = next(m.value for m in at2.markdown if "md-watchlist" in m.value and "<table" in m.value)
    assert "remove=NVDA" not in table2 and "remove=SAP" in table2
    assert "remove" not in at2.query_params


def test_house_trades_table_shows_matches_coverage_and_the_unavailable_state() -> None:
    import house_trades as ht
    from datetime import date as _d

    data = {
        "generated_at": "2026-11-28T03:00:00+00:00",
        "coverage": {"filings_seen": 10, "parsed": 8, "not_read": 2},
        "trades": [
            {"asset_code": "ST", "ticker": "BRK-B", "traded": "2026-05-01", "filed": "2026-05-10", "member": "A <b>X</b>", "district": "TX01", "owner": "Self", "type": "buy", "amount_low": 1001, "amount_high": 15000, "late": False, "link": "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2026/1.pdf"},
            {"asset_code": "ST", "ticker": "NVDA", "traded": "2026-12-26", "filed": "2026-02-09", "member": "B", "district": "CA01", "owner": "Spouse", "type": "sell", "amount_low": 50000001, "amount_high": None, "late": True, "link": "javascript:alert(1)"},
            {"asset_code": "CT", "ticker": "NVDA", "traded": "2026-01-01", "filed": "2026-01-02", "member": "C", "district": "CA02", "owner": "Self", "type": "buy", "amount_low": 1, "amount_high": 2, "late": False, "link": ""},
        ],
    }
    rows = ht.trades_for_ticker(data, "BRK.B", _d(2026, 11, 28))
    assert [r["member"] for r in rows] == ["A <b>X</b>"]
    nv = ht.trades_for_ticker(data, "nvda", _d(2026, 11, 28))
    assert len(nv) == 1 and nv[0]["future"] is True  # crypto/other asset rows never appear on stock pages
    assert ht.safe_link(nv[0]["link"]) is None and ht.safe_link(rows[0]["link"])
    assert ht.amount_text(50000001, None) == "Over $50,000,001"
    assert "8 of 10" in ht.coverage_text(data) and "2 not read" in ht.coverage_text(data)

    from streamlit.testing.v1 import AppTest

    def app() -> None:
        import json as _j, os, sys

        sys.path.insert(0, os.environ["TL_ROOT"])
        import research_desk_page as page

        page.cached_house_data = lambda: _j.loads(os.environ["TL_HOUSE"]) if os.environ.get("TL_HOUSE") else None
        page._render_government_block(os.environ["TL_TICKER"])

    import json, os

    os.environ["TL_ROOT"] = str(ROOT)
    os.environ["TL_TICKER"] = "BRK-B"
    os.environ["TL_HOUSE"] = json.dumps(data)
    at = AppTest.from_function(app)
    at.run(timeout=60)
    assert not at.exception
    body = " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption)
    assert "&lt;b&gt;X&lt;/b&gt;" in body and "<b>X</b>" not in body and "8 of 10" in body

    os.environ["TL_TICKER"] = "AAPL"
    at = AppTest.from_function(app); at.run(timeout=60)
    assert any("No House trades found for AAPL" in c.value for c in at.caption)

    os.environ["TL_HOUSE"] = ""
    at = AppTest.from_function(app); at.run(timeout=60)
    assert any("unavailable right now" in c.value for c in at.caption)


def test_dark_and_light_themes_style_the_sidebar_and_buttons() -> None:
    from research_desk_page import MACRO_THEME_CSS

    for name, bg in (("Dark", "#0b1220"), ("Light", "#eef2f7")):
        css = MACRO_THEME_CSS[name]
        assert 'stSidebar"] { background: ' + bg in css
        assert "stSidebar" in css and ".stButton button" in css and "table.md-watchlist a" in css


if __name__ == "__main__":
    test_macro_indices_are_five_in_spec_order()
    test_ema_trend_bullish_when_above_rising_ema()
    test_weekly_closes_group_by_iso_week()
    test_breadth_summary_counts_per_spec()
    test_session_extreme_compares_the_previous_session()
    test_strip_card_shows_the_lows_gauge()
    test_event_index_mapping_per_spec()
    test_calendar_days_is_seven_with_weekends()
    test_red_folder_events_are_high_impact_only()
    test_event_notes_are_generic_not_invented()
    test_macro_desk_replaces_research_desk()
    test_app_has_macro_desk_and_untouched_data_hub()
    test_parse_headlines_caps_at_five_and_truncates_titles()
    test_search_symbols_returns_yahoo_matches()
    test_fetch_candles_returns_daily_points()
    test_fetch_news_rss_caps_at_five_and_returns_empty_on_failure()
    test_parse_yahoo_chart_keeps_about_1300_closes()
    test_sma_returns_last_period_average()
    test_macro_theme_has_explicit_light_and_dark_palettes()
    test_macro_theme_persists_across_pages()
    test_grok_import_files_blocks_and_skips_unknown_names()
    test_sentiment_score_uses_the_published_weights_and_a_minimum()
    test_seasonality_uses_published_closes_only()
    test_form4_keeps_open_market_buys_separate_from_awards()
    test_insider_net_stays_unknown_until_every_trade_has_a_price()
    test_form4_amendment_replaces_the_original_rows()
    test_price_figure_is_fixed_size_with_range_buttons()
    test_breadth_table_says_yes_or_no_and_index_page_has_no_red_folder_list()
    test_one_search_box_suggests_symbols_as_you_type()
    test_red_folder_falls_back_to_last_good_feed_and_is_not_cached_when_partial()
    test_seasonality_figure_bridges_gaps_and_counts_months_beating_average()
    test_free_feed_sentiment_scores_headlines_and_hides_x()
    test_watchlist_delete_is_a_link_at_the_end_of_each_row_and_removes_the_stock()
    test_house_trades_table_shows_matches_coverage_and_the_unavailable_state()
    test_dark_and_light_themes_style_the_sidebar_and_buttons()
    print("Macro Desk checks passed.")
