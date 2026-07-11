"""CLI entrypoint for radio-feed-watch."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from radio_feed_watch.api.app import create_app
from radio_feed_watch.bus import EventBus
from radio_feed_watch.config import load_config
from radio_feed_watch.mqtt.publisher import MqttPublisher
from radio_feed_watch.pipeline import Pipeline
from radio_feed_watch.sources.manager import SourceManager
from radio_feed_watch.storage.clips import ClipStore
from radio_feed_watch.stt.factory import build_transcriber

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("radio_feed_watch")


async def run(config_path: str) -> None:
    load_dotenv()
    app = load_config(config_path)
    logger.info(
        "locale=%s sources=%d stt=%s dashboard=%s http://%s:%s",
        app.locale.id,
        len([s for s in app.locale.sources if s.enabled]),
        app.stt.provider,
        app.dashboard.mode,
        app.dashboard.host,
        app.dashboard.port,
    )

    store = ClipStore(app.clips)
    store.purge_expired()
    transcriber = build_transcriber(app)
    mqtt = MqttPublisher(app.mqtt)
    await mqtt.connect()
    bus = EventBus()

    pipeline = Pipeline(
        app,
        store,
        transcriber,
        mqtt=mqtt if mqtt.enabled else None,
        bus=bus,
    )
    manager = SourceManager(app)
    api = create_app(app, bus, store)

    stop = asyncio.Event()

    def _stop(*_args) -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            pass

    config = uvicorn.Config(
        api,
        host=app.dashboard.host,
        port=app.dashboard.port,
        log_level="info",
        loop="asyncio",
    )
    server = uvicorn.Server(config)
    server.install_signal_handlers = False

    async def _purge_loop() -> None:
        interval = max(60, int(app.clips.purge_interval_s))
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
                break
            except asyncio.TimeoutError:
                try:
                    store.purge_expired()
                except Exception:
                    logger.exception("Clip retention purge failed")

    worker = asyncio.create_task(manager.run(pipeline.handle_clip), name="sources")
    web = asyncio.create_task(server.serve(), name="dashboard")
    purge = asyncio.create_task(_purge_loop(), name="purge")

    await stop.wait()
    logger.info("Shutting down…")
    server.should_exit = True
    worker.cancel()
    purge.cancel()
    await manager.close()
    await mqtt.close()
    await asyncio.gather(worker, web, purge, return_exceptions=True)


def main() -> None:
    parser = argparse.ArgumentParser(prog="radio-feed-watch")
    parser.add_argument(
        "-c",
        "--config",
        default="config.yaml",
        help="Path to config.yaml (falls back to config.example.yaml)",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Load config and print summary, then exit",
    )
    args = parser.parse_args()

    if args.check_config:
        load_dotenv()
        app = load_config(args.config)
        enabled = [s.id for s in app.locale.sources if s.enabled]
        print(f"locale: {app.locale.id} ({app.locale.label})")
        print(f"locale_path: {app.locale_path}")
        print(f"stt.provider: {app.stt.provider}")
        print(f"enabled_sources: {enabled}")
        print(f"waypoints: {len(app.waypoints)}")
        print(f"mqtt.enabled: {app.mqtt.enabled}")
        print(f"dashboard.mode: {app.dashboard.mode}")
        host = "127.0.0.1" if app.dashboard.host in ("0.0.0.0", "::") else app.dashboard.host
        print(f"dashboard.url: http://{host}:{app.dashboard.port}/")
        return

    if not Path(args.config).exists() and not Path("config.example.yaml").exists():
        raise SystemExit(f"Config not found: {args.config}")

    asyncio.run(run(args.config))


if __name__ == "__main__":
    main()
