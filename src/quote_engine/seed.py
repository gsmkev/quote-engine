import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker

from quote_engine.adapters.db.seed import seed_catalog
from quote_engine.adapters.db.uow import make_engine
from quote_engine.config import Settings
from quote_engine.domain.catalog import Catalog


async def main() -> None:
    engine = make_engine(Settings().database_url)
    async with async_sessionmaker(engine)() as s:
        await seed_catalog(s, Catalog.from_json(Path("fixtures/catalog.json")))
        await s.commit()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
