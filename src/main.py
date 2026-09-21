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
from src.queue.recording_queue import RecordingQueue
from src.queue.redis_queue import RedisQueue
from src.replay import replay_ticks
from src.strategies.moving_average import MovingAverageStrategy

logger = logging.getLogger(__name__)


def _log_signal_result(signal: object, result: object) -> None:
    if result is None:  # HOLD signals or automation disabled never reach here
        return
    outcome = "accepted" if result.accepted else "rejected"  # type: ignore[attr-defined]
    detail = result.order_id if result.accepted else result.reason  # type: ignore[attr-defined]
    logger.info("signal %s %s strength=%.2f price=%g -> %s (%s)",
               signal.symbol, signal.action.value, signal.strength, signal.price,  # type: ignore[attr-defined]
               outcome, detail)


def _run_trading_loop(settings: Settings, queue: RedisQueue, metrics: RuntimeMetrics,
                       stop_event: threading.Event, poll_interval: float, quantity: int,
                       enforce_market_hours: bool = True) -> None:
    predictor = MovingAverageStrategy()
    runtime = build_runtime(
        settings, predictor, queue=queue, quantity=quantity,
        on_result=_log_signal_result, metrics=metrics, poll_interval=poll_interval,
        enforce_market_hours=enforce_market_hours,
    )
    try:
        cycles = runtime.run(stop_event, count=10)
        logger.info("trading loop stopped after %d cycles", cycles)
    except Exception:
        logger.exception("trading loop crashed")
    finally:
        stop_event.set()


def _run_status_logger(metrics: RuntimeMetrics, stop_event: threading.Event, interval: float) -> None:
    """Print a periodic one-line snapshot so a quiet console still shows life.

    Actionable signals are already logged immediately by _log_signal_result;
    this covers the (usual) case where nothing actionable has happened yet.
    """
    while not stop_event.wait(interval):
        logger.info("status cycles=%d signals=%d errors=%d last_error=%s",
                    metrics.cycles, metrics.signals, metrics.errors, metrics.last_error)


async def _run_collector(settings: Settings, symbols: list[str], queue: RedisQueue,
                          stop_event: threading.Event) -> None:
    client = KISWebSocketClient(
        settings.kis_appkey, settings.kis_appsecret,
        paper_trading=settings.is_paper, base_url=settings.kis_base_url,
        max_reconnects=30,  # 1,2,4..60s backoff ≈ 25 min of outage tolerance
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


async def _run_replay(path: str, queue: RedisQueue, stop_event: threading.Event,
                       speed: float = 1.0) -> None:
    try:
        await replay_ticks(path, queue, stop_event, speed=speed)
        # Give the trading loop one more chance to drain the last published
        # ticks before stopping it — TradingRuntime.run only checks
        # stop_event at the top of each cycle, so ticks published right
        # before replay finishes (or an entire short recording) could
        # otherwise never be read.
        await asyncio.sleep(2.0)
    finally:
        # Replay finished (or hit an error) — nothing is publishing ticks
        # anymore, so the trading loop must stop instead of polling forever.
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
    parser.add_argument("--status-interval", type=float, default=10.0,
                        help="seconds between console status snapshots, 0 to disable (default: 10.0)")
    parser.add_argument("--record", default=None,
                        help="append every published tick to this JSONL file for later replay")
    parser.add_argument("--replay", default=None,
                        help="replay ticks from this JSONL file instead of the live KIS websocket")
    parser.add_argument("--replay-speed", type=float, default=1.0,
                        help="replay this many times faster than the recorded pace, e.g. 60 "
                             "replays an 11-hour recording in ~11 minutes (default: 1.0, ignored "
                             "without --replay)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.record and args.replay:
        raise SystemExit("--record and --replay cannot be used together")

    settings = Settings()
    if args.replay is None:
        if not settings.kis_appkey.strip() or not settings.kis_appsecret.strip():
            raise SystemExit("KIS_APPKEY and KIS_APPSECRET are required to start the tick collector")
        if not settings.is_paper:
            settings.validate_for_live()
    elif not settings.is_paper:
        # Replaying skips the wall-clock market-hours check (see
        # build_order_manager's enforce_market_hours=False below), so
        # replaying old ticks in live mode could submit real orders against
        # a real brokerage account with that safety check disabled.
        raise SystemExit(
            "--replay requires PAPER_TRADING=true; refusing to replay recorded ticks against a live account"
        )

    raw_queue = RedisQueue(settings.redis_host, settings.redis_port)
    queue = RecordingQueue(raw_queue, args.record) if args.record else raw_queue
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
        kwargs={"enforce_market_hours": args.replay is None},
        name="trading-loop", daemon=True,
    )]
    if args.health_port is not None:
        threads.append(threading.Thread(
            target=_run_health_server,
            args=(settings, queue, metrics, args.health_port, stop_event),
            name="health-server", daemon=True,
        ))
    if args.status_interval > 0:
        threads.append(threading.Thread(
            target=_run_status_logger,
            args=(metrics, stop_event, args.status_interval),
            name="status-logger", daemon=True,
        ))
    for thread in threads:
        thread.start()

    logger.info("tick collector starting for symbols=%s paper=%s replay=%s",
                args.symbols, settings.is_paper, args.replay is not None)
    try:
        if args.replay is not None:
            try:
                asyncio.run(_run_replay(args.replay, queue, stop_event, speed=args.replay_speed))
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
        else:
            asyncio.run(_run_collector(settings, args.symbols, queue, stop_event))
    finally:
        stop_event.set()
        for thread in threads:
            thread.join(timeout=10)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
