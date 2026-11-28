import os, sys
from datetime import date
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import insider_nightly as n

IDX = """Form Type   Company Name   CIK   Date Filed   File Name
4           ACME CORP                                                     111111      20261124    edgar/data/111111/0001111111-26-000001.txt
4           SMITH JOHN                                                    222222      20261124    edgar/data/111111/0001111111-26-000001.txt
4           BETA INC                                                      333333      20261124    edgar/data/333333/0003333333-26-000002.txt
8-K         OTHER                                                         444444      20261124    edgar/data/444444/0004444444-26-000003.txt
"""


def sub(code, ticker="ACME", price="12.50", shares="1000", name="Acme Corp", person="Smith John"):
    return f"""<SEC-DOCUMENT><XML><ownershipDocument><issuer><issuerName>{name}</issuerName>
<issuerTradingSymbol>{ticker}</issuerTradingSymbol></issuer>
<reportingOwner><reportingOwnerId><rptOwnerName>{person}</rptOwnerName></reportingOwnerId>
<reportingOwnerRelationship><officerTitle>CEO</officerTitle></reportingOwnerRelationship></reportingOwner>
<nonDerivativeTable><nonDerivativeTransaction><transactionDate><value>2026-11-20</value></transactionDate>
<transactionCoding><transactionCode>{code}</transactionCode></transactionCoding>
<transactionAmounts><transactionShares><value>{shares}</value></transactionShares>
<transactionPricePerShare><value>{price}</value></transactionPricePerShare></transactionAmounts>
</nonDerivativeTransaction></nonDerivativeTable></ownershipDocument></XML></SEC-DOCUMENT>"""


def test_index_dedupes_filings_and_keeps_only_form_4():
    e = n.parse_index(IDX)
    assert [x["accession"] for x in e] == ["0001111111-26-000001", "0003333333-26-000002"]
    assert e[0]["filed"] == "2026-11-24"


def test_only_open_market_buys_are_kept_with_price_and_value():
    e = n.parse_index(IDX)[0]
    b = n.buys_from_submission(sub("P"), e)
    assert len(b) == 1 and b[0]["ticker"] == "ACME" and b[0]["price"] == 12.5 and b[0]["value"] == 12500
    assert b[0]["role"] == "CEO" and b[0]["link"].startswith("https://www.sec.gov/Archives/")
    assert n.buys_from_submission(sub("S"), e) == [] and n.buys_from_submission(sub("A"), e) == []


def test_run_is_resumable_and_idempotent():
    today = date(2026, 11, 25)
    pages = {"https://www.sec.gov/Archives/edgar/daily-index/2026/QTR4/form.20261124.idx": IDX,
             "https://www.sec.gov/Archives/edgar/data/111111/0001111111-26-000001.txt": sub("P"),
             "https://www.sec.gov/Archives/edgar/data/333333/0003333333-26-000002.txt": sub("P", "BETA", name="Beta Inc")}

    def fetch(url):
        return pages.get(url)
    fetch.state = {}
    data = {"buys": [], "days_done": []}
    assert n.run(data, today, fetch, initial_days=3) is False
    assert {b["ticker"] for b in data["buys"]} == {"ACME", "BETA"} and "2026-11-24" in data["days_done"]
    before = list(data["buys"])
    n.run(data, today, fetch, initial_days=3)
    assert data["buys"] == before


def test_amended_filing_replaces_the_original():
    a = {"ticker": "X", "person": "P", "traded": "2026-11-01", "shares": 1, "price": 2.0, "amended": False, "filed": "2026-11-02"}
    b = dict(a, amended=True, filed="2026-11-05")
    assert n.dedupe([a, b]) == [b] and n.dedupe([b, a]) == [b]


def test_aborts_after_repeated_failures_without_marking_the_day_done():
    today = date(2026, 11, 25)
    idx = "https://www.sec.gov/Archives/edgar/daily-index/2026/QTR4/form.20261124.idx"

    def fetch(url):
        if url == idx:
            return "\n".join(f"4  CO{i}  {100+i}  20261124  edgar/data/{100+i}/000{i}-26-00000{i}.txt" for i in range(6))
        fetch.state["fail_streak"] = fetch.state.get("fail_streak", 0) + 1
        return None
    fetch.state = {}
    data = {"buys": [], "days_done": []}
    assert n.run(data, today, fetch, initial_days=3) is True
    assert "2026-11-24" not in data["days_done"]


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
    print("Insider nightly checks passed.")
