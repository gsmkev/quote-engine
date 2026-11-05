import asyncio
import contextlib
import signal
from pathlib import Path

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from quote_engine.adapters.db.uow import make_engine
from quote_engine.adapters.extractors.factory import build_extractor
from quote_engine.application.ports import Extractor
from quote_engine.application.process import process_next
from quote_engine.config import Settings
from quote_engine.domain.catalog import Catalog
from quote_engine.logging import configure_logging

log = structlog.get_logger()


async def run(
    session_factory: async_sessionmaker[AsyncSession],
    extractor: Extractor,
    catalog: Catalog,
    settings: Settings,
    stop: asyncio.Event,
) -> None:
    """Drain the inbox; sleep `poll_interval_s` when idle; exit once `stop` is set."""
    while not stop.is_set():
        try:
            busy = await process_next(
                session_factory,
                extractor,
                catalog,
                max_attempts=settings.max_attempts,
                context_window=settings.context_window_messages,
            )
        except Exception:
            log.exception("worker_error")
            busy = False
        if not busy:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), settings.poll_interval_s)


async def main() -> None:
    configure_logging()
    settings = Settings()
    catalog = Catalog.from_json(Path("fixtures/catalog.json"))
    engine = make_engine(settings.database_url)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    log.info("worker_started", mode=settings.extractor_mode)
    try:
        await run(
            async_sessionmaker(engine, expire_on_commit=False),
            build_extractor(settings, catalog),
            catalog,
            settings,
            stop,
        )
    finally:
        await engine.dispose()
        log.info("worker_stopped")


if __name__ == "__main__":
    asyncio.run(main())
