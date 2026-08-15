"""Environment-backed application settings."""

from dataclasses import dataclass
from pathlib import Path
import os


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    kis_base_url: str = os.getenv("KIS_BASE_URL", "https://openapi.koreainvestment.com:9443")
    kis_cano: str = os.getenv("KIS_CANO", "")
    kis_acnt_prdt_cd: str = os.getenv("KIS_ACNT_PRDT_CD", "01")
    kis_appkey: str = os.getenv("KIS_APPKEY", "")
    kis_appsecret: str = os.getenv("KIS_APPSECRET", "")
    redis_host: str = os.getenv("REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
    database_path: Path = Path(os.getenv("DATABASE_PATH", "./data/trading.sqlite3"))
    model_path: Path = Path(os.getenv("MODEL_PATH", "./models/latest_model.pt"))
    paper_trading: bool = _env_bool("PAPER_TRADING", True)
    min_signal_strength: float = float(os.getenv("MIN_SIGNAL_STRENGTH", "0.60"))
    max_order_value: int = int(os.getenv("MAX_ORDER_VALUE", "1000000"))
    max_daily_loss: int = int(os.getenv("MAX_DAILY_LOSS", "100000"))


settings = Settings()
