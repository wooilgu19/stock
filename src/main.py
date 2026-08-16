"""Production entrypoint: run the KIS tick collector and trading loop together.

Two independent long-running components share one Redis stream:

  1. an asyncio task that pulls the KIS WebSocket feed and publishes ticks
  2. a background thread running ``TradingRuntime``'s poll loop, which reads
     those ticks, generates signals, and submits orders

``build_runtime``/``build_pipeline`` (src/application.py) already assemble
the signal-to-order pipeline from ``Settings``; this module only wires the
two loops together, an optional health server, and graceful shutdown. If
either the collector or the trading loop dies, the other is stopped too
instead of running a half-alive pipeline unnoticed.
"""

import argparse
import asyncio
import logging
import signal
import threading

from src.api.kis_websocket import KISWebSocketClient
from src.application import build_health_app, build_runtime
from src.config import Settings
from src.monitoring.metrics import RuntimeMetrics
from src.queue.redis_queue import RedisQueue
from src.strategies.moving_average import MovingAverageStrategy

logger = logging.getLogger(__name__)


def _run_trading_loop(settings: Settings, queue: RedisQueue, metrics: RuntimeMetrics,
                       stop_event: threading.Event, poll_interval: float, quantity: int) -> None:
    predictor = MovingAverageStrategy()
    runtime = build_runtime(
        settings, predictor, queue=queue, quantity=quantity,
        metrics=metrics, poll_interval=poll_interval,
    )
    try:
        cycles = runtime.run(stop_event, count=10)
        logger.info("trading loop stopped after %d cycles", cycles)
    except Exception:
        logger.exception("trading loop crashed")
    finally:
        stop_event.set()


async def _run_collector(settings: Settings, symbols: list[str], queue: RedisQueue,
                          stop_event: threading.Event) -> None:
    client = KISWebSocketClient(
        settings.kis_appkey, settings.kis_appsecret,
        paper_trading=settings.is_paper, base_url=settings.kis_base_url,
    )
    stream_task = asyncio.ensure_future(client.stream_to_queue(symbols, queue))
    stop_task = asyncio.ensure_future(asyncio.to_thread(stop_event.wait))
    done, pending = await asyncio.wait({stream_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    if stream_task in done:
        exc = stream_task.exception()
        if exc is not None:
            logger.error("tick collector stopped with an error: %s", exc)
        # Either the collector crashed or reconnects were exhausted; either
        # way ticks have stopped, so the trading loop should stop too rather
        # than keep polling a Redis stream nothing is publishing to.
        stop_event.set()


def _run_health_server(settings: Settings, queue: RedisQueue, metrics: RuntimeMetrics,
                        port: int, stop_event: threading.Event) -> None:
    import uvicorn

    app = build_health_app(settings, queue=queue, metrics=metrics)
    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning"))

    def _watch_stop() -> None:
        stop_event.wait()
        server.should_exit = True

    threading.Thread(target=_watch_stop, daemon=True).start()
    server.run()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the KIS tick collector and trading loop")
    parser.add_argument("symbols", nargs="+", help="six-digit domestic stock symbols to trade")
    parser.add_argument("--quantity", type=int, default=1, help="shares per order (default: 1)")
    parser.add_argument("--poll-interval", type=float, default=1.0,
                        help="trading loop poll interval in seconds (default: 1.0)")
    parser.add_argument("--health-port", type=int, default=None,
                        help="serve /health and /metrics on this port (optional)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    settings = Settings()
    if not settings.kis_appkey.strip() or not settings.kis_appsecret.strip():
        raise SystemExit("KIS_APPKEY and KIS_APPSECRET are required to start the tick collector")
    if not settings.is_paper:
        settings.validate_for_live()

    queue = RedisQueue(settings.redis_host, settings.redis_port)
    metrics = RuntimeMetrics()
    stop_event = threading.Event()

    def _handle_signal(signum: int, _frame: object) -> None:
        logger.info("received signal %s, shutting down", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    threads = [threading.Thread(
        target=_run_trading_loop,
        args=(settings, queue, metrics, stop_event, args.poll_interval, args.quantity),
        name="trading-loop", daemon=True,
    )]
    if args.health_port is not None:
        threads.append(threading.Thread(
            target=_run_health_server,
            args=(settings, queue, metrics, args.health_port, stop_event),
            name="health-server", daemon=True,
        ))
    for thread in threads:
        thread.start()

    logger.info("tick collector starting for symbols=%s paper=%s", args.symbols, settings.is_paper)
    try:
        asyncio.run(_run_collector(settings, args.symbols, queue, stop_event))
    finally:
        stop_event.set()
        for thread in threads:
            thread.join(timeout=10)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
