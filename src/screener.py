"""Daily symbol screener built on KIS's trading-value ranking API.

Picks liquid, moving stocks for the day. Uses only the volume-rank endpoint
(one call, up to 30 rows, already carries price and day change); the
fluctuation ranking is skipped because it surfaces illiquid movers that a
tick strategy can't trade.
"""

import sys
from dataclasses import dataclass

from src.api.kis_rest import KISRestClient

VOLUME_RANK_PATH = "/uapi/domestic-stock/v1/quotations/volume-rank"
VOLUME_RANK_TR_ID = "FHPST01710000"
# 10 flags: 투자위험/경고/주의, 관리종목, 정리매매, 불성실공시, 우선주,
# 거래정지, ETF, ETN, 신용주문불가, SPAC. 1 = exclude.
EXCLUDE_ALL = "1111111111"


@dataclass(frozen=True)
class Candidate:
    symbol: str
    name: str
    price: float
    change_pct: float
    trading_value: float


def fetch_candidates(client: KISRestClient) -> list[Candidate]:
    body = client.get(VOLUME_RANK_PATH, VOLUME_RANK_TR_ID, {
        "FID_COND_MRKT_DIV_CODE": "J", "FID_COND_SCR_DIV_CODE": "20171",
        "FID_INPUT_ISCD": "0000", "FID_DIV_CLS_CODE": "0",
        "FID_BLNG_CLS_CODE": "3",  # 거래금액순
        "FID_TRGT_CLS_CODE": "111111111", "FID_TRGT_EXLS_CLS_CODE": EXCLUDE_ALL,
        "FID_INPUT_PRICE_1": "", "FID_INPUT_PRICE_2": "", "FID_VOL_CNT": "",
        "FID_INPUT_DATE_1": "",
    })
    candidates = []
    for row in body.get("output") or []:
        try:
            candidates.append(Candidate(
                symbol=row["mksc_shrn_iscd"], name=row["hts_kor_isnm"],
                price=float(row["stck_prpr"]), change_pct=float(row["prdy_ctrt"]),
                trading_value=float(row["acml_tr_pbmn"]),
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return candidates


def select_symbols(candidates: list[Candidate], top_n: int = 5, min_price: float = 1000,
                   min_change_pct: float = 1.0, max_change_pct: float = 15.0) -> list[Candidate]:
    """Highest trading value first, among stocks moving enough to trade but not
    pinned near the daily limit (max_change_pct keeps out limit-up chasing)."""
    picked = [c for c in candidates
              if c.price >= min_price and min_change_pct <= abs(c.change_pct) <= max_change_pct]
    return sorted(picked, key=lambda c: c.trading_value, reverse=True)[:top_n]


def main() -> int:
    from src.config import Settings
    settings = Settings()
    client = KISRestClient(settings.kis_base_url, settings.kis_appkey, settings.kis_appsecret)
    picks = select_symbols(fetch_candidates(client))
    for c in picks:
        print(f"{c.symbol} {c.name} price={c.price:.0f} change={c.change_pct:+.2f}% "
              f"value={c.trading_value / 1e8:.0f}억", file=sys.stderr)
    print(" ".join(c.symbol for c in picks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
