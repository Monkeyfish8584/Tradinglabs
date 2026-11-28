import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import house_nightly as n


def test_normalize():
    assert n.normalize_name("Danaher Corporation Common Stock (DHR) [ST]") == "danaher"
    assert n.normalize_name("Amazon.com, Inc. - Common Stock") == "amazon com"
    assert n.normalize_name("Procter & Gamble Company") == "procter and gamble"


def test_ticker_map():
    sec = {"0": {"title": "DANAHER CORP", "ticker": "DHR"}, "1": {"title": "Alphabet Inc.", "ticker": "GOOGL"},
           "2": {"title": "ALPHABET INC.", "ticker": "GOOG"}}
    m = n.build_ticker_map(sec, {"Meta Platforms": "META"})
    assert m["danaher"] == "DHR" and m["meta platforms"] == "META"
    assert "alphabet" not in m  # ambiguous names are not guessed


def test_late():
    assert n.is_late("2025-01-01", "2025-02-20") is True
    assert n.is_late("2025-01-01", "2025-02-14") is False


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
    print("House nightly checks passed.")
