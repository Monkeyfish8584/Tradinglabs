"""Research Desk page uses stored snapshots and does not fill missing figures."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research_desk_page import (
    THESES,
    daily_trend,
    load_snapshots,
    squeeze_checks,
    thesis_for,
    trend_text,
    upside,
    valuation_sentence,
    watchlist_html,
    watchlist_rows,
    weekly_trend,
)
from research_desk_quotes import QuoteError, fetch_new_snapshot, number_value, parse_forecast_html, parse_statistics_html


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


def test_daily_and_weekly_trends_use_stored_series() -> None:
    snapshots = {row["ticker"]: row for row in load_snapshots()}
    usar = snapshots["USAR"]
    closes = usar["closes"]
    assert daily_trend(usar) == usar["changePct"]
    assert weekly_trend(usar) == (closes[-1] / closes[-6] - 1) * 100
    assert weekly_trend({"closes": [1, 2, 3]}) is None
    assert abs(daily_trend({"closes": [10, 12]}) - 20) < 1e-9
    rows = {row["ticker"]: row for row in watchlist_rows()}
    assert rows["USAR"]["daily_trend"] == usar["changePct"]
    assert rows["USAR"]["weekly_trend"] == weekly_trend(usar)
    assert trend_text(usar["changePct"]).startswith("Down ")
    assert trend_text(None) == "Not in snapshot"
    page = (ROOT / "research_desk_page.py").read_text(encoding="utf-8")
    assert "Open a stock" not in page
    table = watchlist_html(watchlist_rows())
    assert 'href="?ticker=USAR"' in table
    assert 'href="?ticker=NVO"' in table
    assert "Daily trend" in table and "Weekly trend" in table


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
        "https://query1.finance.yahoo.com/v8/finance/chart/EX?interval=1d&range=1y": __import__("json").dumps(yahoo),
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
    assert weekly_trend(snapshot) == (16 / 10 - 1) * 100
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
    test_trading_edge_page_remains_the_default()
    print("Research desk snapshot checks passed.")
