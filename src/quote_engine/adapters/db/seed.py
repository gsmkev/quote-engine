from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from quote_engine.adapters.db.models import CatalogRow
from quote_engine.domain.catalog import Catalog


async def seed_catalog(session: AsyncSession, catalog: Catalog) -> None:
    rows = [
        {"sku": i.sku, "description": i.description, "aliases": i.aliases}
        for i in catalog.items.values()
    ]
    stmt = insert(CatalogRow).values(rows)
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=["sku"],
            set_={"description": stmt.excluded.description, "aliases": stmt.excluded.aliases},
        )
    )
