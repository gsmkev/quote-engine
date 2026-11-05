import asyncio
import contextlib
from collections.abc import AsyncGenerator

import structlog
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from quote_engine.adapters.api.routes import router
from quote_engine.adapters.db.models import CatalogRow
from quote_engine.adapters.db.uow import make_engine
from quote_engine.adapters.extractors.factory import build_extractor
from quote_engine.application.ports import Extractor
from quote_engine.application.process import process_next
from quote_engine.config import Settings
from quote_engine.domain.catalog import Catalog, CatalogItem

log = structlog.get_logger()


async def _worker(app: FastAPI, extractor: Extractor, catalog: Catalog) -> None:
    s: Settings = app.state.settings
    while True:
        try:
            busy = await process_next(
                app.state.session_factory,
                extractor,
                catalog,
                max_attempts=s.max_attempts,
                context_window=s.context_window_messages,
            )
        except Exception:
            log.exception("worker_error")
            busy = False
        if not busy:
            await asyncio.sleep(s.poll_interval_s)


def create_app(
    settings: Settings, *, extractor: Extractor | None = None, run_inline_worker: bool = False
) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        engine = make_engine(settings.database_url)
        app.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
        task = None
        if run_inline_worker:
            async with app.state.session_factory() as s:
                rows = (await s.execute(select(CatalogRow))).scalars()
                catalog = Catalog(
                    items={
                        r.sku: CatalogItem(sku=r.sku, description=r.description, aliases=r.aliases)
                        for r in rows
                    }
                )
            task = asyncio.create_task(
                _worker(app, extractor or build_extractor(settings, catalog), catalog)
            )
        try:
            yield
        finally:
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            await engine.dispose()

    app = FastAPI(title="Quote & State Engine", lifespan=lifespan)
    app.state.settings = settings
    app.include_router(router)
    return app


def create_app_from_env() -> FastAPI:
    return create_app(Settings())
