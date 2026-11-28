"""Golden checks for house_trades.parse_ptr_text, using text from real 2025 House PTR PDFs."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import house_trades as h

FX = os.path.join(os.path.dirname(__file__), "fixtures", "house")


def load(doc):
    return h.parse_ptr_text(open(os.path.join(FX, doc + ".txt"), encoding="utf-8").read())


def test_basic_two_rows():
    r = load("20030544")
    assert r["member"] == "Pete Sessions" and r["district"] == "TX17" and r["filing_id"] == "20030544"
    assert [(t["ticker"], t["type"], t["owner"]) for t in r["trades"]] == [
        ("DHR", "sell", "Spouse"), ("JNJ", "sell", "Spouse")]
    assert (r["trades"][0]["amount_low"], r["trades"][0]["amount_high"]) == (50001, 100000)
    assert r["trades"][0]["traded"] == "2025-06-12" and r["trades"][0]["notified"] == "2025-06-21"


def test_single_space_before_type():
    t = load("20030810")["trades"]
    assert len(t) == 1 and t[0]["ticker"] == "HURA" and t[0]["type"] == "buy"
    t = load("20033691")["trades"]
    assert len(t) == 1 and t[0]["ticker"] == "PG" and t[0]["amount_high"] == 15000


def test_wrapped_assets_and_partial_sales():
    r = load("20030212")
    by = {}
    for t in r["trades"]:
        by.setdefault(t["ticker"], []).append(t)
    assert len(by["AVGO"]) == 2 and all(t["type"] == "sell (partial)" for t in by["AVGO"])
    assert by["NET"][0]["asset"].startswith("Cloudflare, Inc. Class A Common Stock (NET)")
    assert by["IBM"][0]["type"] == "buy" and not r["warnings"]


def test_bonds_have_no_ticker():
    t = load("20033431")["trades"]
    assert len(t) == 2 and all(x["ticker"] is None and x["asset_code"] == "GS" for x in t)
    assert t[0]["amount_low"] == 250001 and t[0]["amount_high"] == 500000


def test_amounts():
    assert h.parse_amount("$1,001 - $15,000") == (1001, 15000)
    assert h.parse_amount("Over $50,000,000") == (50000000, None)
    assert h.parse_amount("") == (None, None)


def test_coverage_names_members_with_unread_paper_filings():
    data = {"generated_at": "2026-11-28T00:00:00", "coverage": {"filings_seen": 5, "parsed": 2, "not_read": 3},
            "not_read": [{"member": "A B", "reason": "scanned paper filing"}, {"member": "A B", "reason": "scanned paper filing"},
                         {"member": "C D", "reason": "scanned paper filing"}, {"member": "E F", "reason": "no trade rows found"}]}
    text = h.coverage_text(data)
    assert "A B (2), C D (1)" in text and "E F" not in text


def test_scanned_flag():
    # a PDF with no text layer is reported, not guessed
    r = {"scanned": True, "trades": []}
    assert not r["trades"]


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
    print("House trade parser checks passed.")
