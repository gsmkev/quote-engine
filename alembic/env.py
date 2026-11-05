import asyncio
import os

from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://quote:quote@postgres:5432/quote")


def _run(connection):
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()


async def _run_online():
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        await conn.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=url, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(_run_online())
