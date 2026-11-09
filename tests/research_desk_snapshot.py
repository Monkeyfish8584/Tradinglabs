"""Research Desk page uses stored snapshots and does not fill missing figures."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research_desk_page import (
    THESES,
    load_snapshots,
    squeeze_checks,
    thesis_for,
    upside,
    valuation_sentence,
    watchlist_rows,
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
    test_trading_edge_page_remains_the_default()
    print("Research desk snapshot checks passed.")
