"""Environment-backed application settings."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import os

from src.engine.holiday_calendar import parse_holiday_dates


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
    automation_mode: str = os.getenv("AUTOMATION_MODE", "auto").strip().lower()
    min_signal_strength: float = float(os.getenv("MIN_SIGNAL_STRENGTH", "0.60"))
    max_order_value: int = int(os.getenv("MAX_ORDER_VALUE", "1000000"))
    max_daily_loss: int = int(os.getenv("MAX_DAILY_LOSS", "100000"))
    kis_order_lookback_days: int = int(os.getenv("KIS_ORDER_LOOKBACK_DAYS", "1"))
    paper_starting_cash: float = float(os.getenv("PAPER_STARTING_CASH", "10000000"))
    telegram_token: str = os.getenv("TELEGRAM_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    market_holidays: frozenset[date] = parse_holiday_dates(
        os.getenv("MARKET_HOLIDAYS", "")
    )

    def __post_init__(self) -> None:
        if self.automation_mode not in {"auto", "manual"}:
            raise ValueError("automation_mode must be 'auto' or 'manual'")
        if self.kis_order_lookback_days <= 0:
            raise ValueError("kis_order_lookback_days must be positive")
        if self.paper_starting_cash < 0:
            raise ValueError("paper_starting_cash cannot be negative")
        if not 0 <= self.min_signal_strength <= 1:
            raise ValueError("min_signal_strength must be between 0 and 1")
        if self.max_order_value < 0:
            raise ValueError("max_order_value cannot be negative")
        if self.max_daily_loss < 0:
            raise ValueError("max_daily_loss cannot be negative")
        if bool(self.telegram_token.strip()) != bool(self.telegram_chat_id.strip()):
            raise ValueError("telegram_token and telegram_chat_id must be configured together")

    @property
    def automation_enabled(self) -> bool:
        return self.automation_mode == "auto"

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_token.strip() and self.telegram_chat_id.strip())

    def validate_for_live(self) -> None:
        """Reject incomplete credentials before constructing a live pipeline."""
        required = {
            "KIS_CANO": self.kis_cano,
            "KIS_APPKEY": self.kis_appkey,
            "KIS_APPSECRET": self.kis_appsecret,
        }
        missing = [name for name, value in required.items() if not value.strip()]
        if missing:
            raise ValueError(f"live trading credentials are missing: {', '.join(missing)}")


settings = Settings()
