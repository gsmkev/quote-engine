from typing import Self

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from quote_engine.adapters.db.repos import InboxRepo, MessageRepo, QuoteRepo, ReviewRepo


def make_engine(url: str) -> AsyncEngine:
    return create_async_engine(url)


class UnitOfWork:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._factory = session_factory

    async def __aenter__(self) -> Self:
        self.session = self._factory()
        self.quotes = QuoteRepo(self.session)
        self.inbox = InboxRepo(self.session)
        self.reviews = ReviewRepo(self.session)
        self.messages = MessageRepo(self.session)
        return self

    async def __aexit__(self, *exc) -> None:
        await self.session.rollback()
        await self.session.close()

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
