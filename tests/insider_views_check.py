import os, sys
from datetime import date
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import insider_views as v

TODAY = date(2026, 11, 28)


def _t(ticker, member, filed, typ="buy", code="ST", traded="2026-11-01"):
    return {"asset_code": code, "ticker": ticker, "asset": (ticker or "X") + " Inc", "member": member, "filed": filed,
            "traded": traded, "type": typ}


def test_congress_view_filters_window_type_and_asset():
    d = {"trades": [_t("AAA", "M1", "2026-11-20"), _t("AAA", "M2", "2026-11-21"), _t("AAA", "M3", "2026-11-22"),
                    _t("BBB", "M1", "2026-11-10", typ="sell"), _t("CCC", "M1", "2026-01-01"),
                    _t("DDD", "M1", "2026-11-20", code="CT"), _t(None, "M1", "2026-11-20"),
                    _t("EEE", "M4", "2026-11-25", typ="sell (partial)", traded="2026-12-30")]}
    r = v.congress_view(d, TODAY, 90, "buy")
    assert [s["ticker"] for s in r["summary"]] == ["AAA"] and r["summary"][0]["members"] == 3 and r["summary"][0]["cluster"]
    assert [x["filed"] for x in r["rows"]] == ["2026-11-22", "2026-11-21", "2026-11-20"]
    s = v.congress_view(d, TODAY, 90, "sell")
    assert {x["ticker"] for x in s["rows"]} == {"BBB", "EEE"} and [x for x in s["rows"] if x["ticker"] == "EEE"][0]["future"]
    assert len(v.congress_view(d, TODAY, 400, "all")["rows"]) == 6  # CT and no-ticker rows are excluded


def _b(ticker, person, filed, value, company="Co"):
    return {"ticker": ticker, "company": company, "person": person, "filed": filed, "traded": filed, "value": value}


def test_company_view_totals_clusters_and_min_value():
    d = {"buys": [_b("AAA", "P1", "2026-11-20", 100000.0), _b("AAA", "P2", "2026-11-21", 50000.0),
                  _b("AAA", "P3", "2026-11-22", None), _b("BBB", "P1", "2026-11-22", 500000.0),
                  _b("OLD", "P1", "2026-06-01", 1.0)]}
    r = v.company_view(d, TODAY, 30)
    a = next(s for s in r["summary"] if s["ticker"] == "AAA")
    assert a["people"] == 3 and a["buys"] == 3 and a["value"] == 150000.0 and a["unpriced"] == 1 and a["cluster"]
    assert [s["ticker"] for s in r["summary"]] == ["BBB", "AAA"] and len(r["rows"]) == 4
    big = v.company_view(d, TODAY, 30, min_value=100000)
    assert {x["ticker"] for x in big["rows"]} == {"AAA", "BBB"} and len(big["rows"]) == 2


def test_links_and_coverage():
    assert v.sec_link("https://www.sec.gov/Archives/x.txt") and v.sec_link("javascript:1") is None
    assert "2026-11-01 to 2026-11-27" in v.company_coverage({"coverage": {"days_from": "2026-11-01", "days_to": "2026-11-27"}})
    assert "No days" in v.company_coverage({})


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
    print("Insider views checks passed.")
