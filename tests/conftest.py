import asyncio
import os
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker
from testcontainers.community.postgres import PostgresContainer

from alembic import command
from quote_engine.adapters.db.seed import seed_catalog
from quote_engine.adapters.db.uow import UnitOfWork, make_engine
from quote_engine.domain.catalog import Catalog

ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="session")
def catalog() -> Catalog:
    return Catalog.from_json(ROOT / "fixtures" / "catalog.json")


@pytest.fixture(scope="session")
def pg_url(catalog):
    with PostgresContainer("postgres:17", driver="asyncpg") as pg:
        url = pg.get_connection_url()
        os.environ["DATABASE_URL"] = url
        command.upgrade(Config(str(ROOT / "alembic.ini")), "head")

        async def seed():
            engine = make_engine(url)
            async with async_sessionmaker(engine)() as s:
                await seed_catalog(s, catalog)
                await s.commit()
            await engine.dispose()

        asyncio.run(seed())
        yield url


@pytest.fixture
async def session_factory(pg_url):
    engine = make_engine(pg_url)
    async with engine.begin() as conn:
        tables = (
            (
                await conn.execute(
                    text(
                        "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                        "AND tablename NOT IN ('catalog','alembic_version')"
                    )
                )
            )
            .scalars()
            .all()
        )
        await conn.execute(text(f"TRUNCATE {','.join(tables)} RESTART IDENTITY CASCADE"))
        await conn.execute(text("ALTER SEQUENCE quote_seq RESTART WITH 1"))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def uow_factory(session_factory):
    return lambda: UnitOfWork(session_factory)
