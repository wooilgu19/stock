from src.screener import Candidate, fetch_candidates, select_symbols
from tests.test_kis_rest import FakeResponse, FakeSession
from src.api.kis_rest import KISRestClient


def _row(symbol, price, change, value):
    return {"mksc_shrn_iscd": symbol, "hts_kor_isnm": symbol, "stck_prpr": str(price),
            "prdy_ctrt": str(change), "acml_tr_pbmn": str(value)}


def test_fetch_candidates_parses_rows_and_skips_malformed():
    session = FakeSession([
        FakeResponse({"rt_cd": "0", "access_token": "t", "expires_in": 3600}),
        FakeResponse({"rt_cd": "0", "output": [_row("005930", 286500, 3.62, 5e12),
                                                {"mksc_shrn_iscd": "bad"}]}),
    ])
    client = KISRestClient("https://example.test", "key", "secret", session=session)

    candidates = fetch_candidates(client)

    assert [c.symbol for c in candidates] == ["005930"]
    assert candidates[0].change_pct == 3.62
    params = session.calls[1][2]["params"]
    assert params["FID_BLNG_CLS_CODE"] == "3"
    assert params["FID_TRGT_EXLS_CLS_CODE"] == "1111111111"


def test_select_symbols_filters_and_ranks_by_trading_value():
    candidates = [
        Candidate("A", "A", 50000, 2.0, 100),
        Candidate("B", "B", 50000, 5.0, 300),
        Candidate("C", "C", 500, 5.0, 900),      # penny stock
        Candidate("D", "D", 50000, 0.2, 800),    # barely moving
        Candidate("E", "E", 50000, 29.9, 700),   # near limit-up
        Candidate("F", "F", 50000, -3.0, 200),   # falling still counts
    ]

    assert [c.symbol for c in select_symbols(candidates, top_n=2)] == ["B", "F"]
    assert [c.symbol for c in select_symbols(candidates)] == ["B", "F", "A"]
