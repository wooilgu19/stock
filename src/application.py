"""Application wiring for the trading order pipeline.

This module assembles dependencies without starting workers or making network
requests.  Keeping construction separate from execution makes startup checks
safe to run in tests and deployment health checks.
"""

from typing import Any

from fastapi import FastAPI

from src.api.kis_rest import KISOrderExecutor, KISOrderStatusProvider, KISRestClient
from src.api.health import create_health_app
from src.config import Settings
from src.database.sqlite import TradeRepository
from src.engine.market_hours import MarketHours
from src.engine.order_manager import OrderManager
from src.engine.portfolio import PortfolioState
from src.engine.risk import RiskGate
from src.engine.reconciliation import OrderReconciler
from src.engine.signal_router import SignalOrderRouter
from src.inference.worker import InferenceWorker, SignalPredictor, TickQueue
from src.monitoring.health import HealthMonitor
from src.monitoring.metrics import RuntimeMetrics
from src.monitoring.notifications import TelegramNotifier
from src.queue.redis_queue import RedisQueue
from src.runtime import TradingRuntime


def build_order_manager(settings: Settings, session: Any = None,
                        enforce_market_hours: bool = True) -> OrderManager:
    """Build a paper-safe order manager from application settings.

    Paper mode does not need credentials or an executor.  Live mode validates
    credentials and injects the KIS executor, but still performs no API call
    until ``OrderManager.submit`` is invoked. ``enforce_market_hours=False``
    skips the wall-clock market-hours check entirely — used when replaying
    recorded ticks outside trading hours (see src/replay.py), where the
    replay's real-time clock legitimately disagrees with the ticks' original
    market time.
    """
    repository = TradeRepository(settings.database_path)
    executor = None
    if not settings.is_paper:
        settings.validate_for_live()
        client = KISRestClient(
            settings.kis_base_url,
            settings.kis_appkey,
            settings.kis_appsecret,
            session=session,
        )
        executor = KISOrderExecutor(
            client,
            settings.kis_cano,
            settings.kis_acnt_prdt_cd,
            paper_trading=False,
        )

    return OrderManager(
        repository=repository,
        risk_gate=RiskGate(
            settings.min_signal_strength,
            settings.max_order_value,
            settings.max_daily_loss,
            min_signal_strength_by_strategy={"lstm": settings.min_signal_strength_lstm},
        ),
        paper_trading=settings.is_paper,
        market_hours=MarketHours.from_settings(settings) if enforce_market_hours else None,
        portfolio=(
            PortfolioState.from_repository(repository, settings.paper_starting_cash)
            if settings.is_paper else None
        ),
        executor=executor,
    )


def build_health_app(settings: Settings, queue: Any = None,
                     metrics: RuntimeMetrics | None = None) -> FastAPI:
    """Build the readiness app from settings without contacting dependencies."""
    health_queue = queue if queue is not None else RedisQueue(
        settings.redis_host, settings.redis_port
    )
    repository = TradeRepository(settings.database_path)
    return create_health_app(HealthMonitor(repository, health_queue.ping), metrics)


def build_reconciler(settings: Settings, session: Any = None) -> OrderReconciler | None:
    """Build the live KIS reconciliation adapter; keep paper mode local-only."""
    if settings.is_paper:
        return None
    settings.validate_for_live()
    client = KISRestClient(
        settings.kis_base_url,
        settings.kis_appkey,
        settings.kis_appsecret,
        session=session,
    )
    provider = KISOrderStatusProvider(
        client,
        settings.kis_cano,
        settings.kis_acnt_prdt_cd,
        paper_trading=False,
        lookback_days=settings.kis_order_lookback_days,
    )
    return OrderReconciler(TradeRepository(settings.database_path), provider)


def build_signal_router(settings: Settings, order_manager: OrderManager,
                        quantity: Any = 1, on_result: Any = None) -> SignalOrderRouter:
    """Build a signal router whose automation behavior follows settings."""
    return SignalOrderRouter(
        order_manager,
        quantity=quantity,
        on_result=on_result,
        automation_enabled=settings.automation_enabled,
    )


def build_pipeline(settings: Settings, predictor: SignalPredictor,
                   queue: TickQueue | None = None, quantity: Any = 1,
                   on_result: Any = None, enforce_market_hours: bool = True) -> InferenceWorker:
    """Build the tick-to-order pipeline without starting its processing loop."""
    pipeline_queue = queue if queue is not None else RedisQueue(
        settings.redis_host, settings.redis_port
    )
    manager = build_order_manager(settings, enforce_market_hours=enforce_market_hours)
    router = build_signal_router(settings, manager, quantity, on_result)
    return InferenceWorker(pipeline_queue, predictor, router.route,
                            cursor_store=manager.repository,
                            cursor_name=getattr(pipeline_queue, "stream", "stock:ticks"))


def build_runtime(settings: Settings, predictor: SignalPredictor,
                  queue: TickQueue | None = None, quantity: Any = 1,
                  on_result: Any = None, poll_interval: float = 1.0,
                  reconciler: OrderReconciler | None = None,
                  metrics: RuntimeMetrics | None = None,
                  on_error: Any = None, enforce_market_hours: bool = True) -> TradingRuntime:
    """Build a stoppable runtime around the configured trading pipeline."""
    worker = build_pipeline(settings, predictor, queue, quantity, on_result,
                            enforce_market_hours=enforce_market_hours)
    active_reconciler = reconciler if reconciler is not None else build_reconciler(settings)
    error_handler = on_error
    if error_handler is None and settings.telegram_enabled:
        error_handler = TelegramNotifier(settings.telegram_token, settings.telegram_chat_id)
    return TradingRuntime(
        worker, reconciler=active_reconciler, poll_interval=poll_interval,
        metrics=metrics,
        on_error=error_handler,
    )
