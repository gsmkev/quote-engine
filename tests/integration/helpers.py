"""Shared helpers for pipeline-level integration tests."""

import json
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from quote_engine.adapters.db.uow import UnitOfWork
from quote_engine.adapters.extractors.cascade import CascadeExtractor
from quote_engine.adapters.extractors.replay import ReplayExtractor
from quote_engine.adapters.extractors.rules import RuleExtractor
from quote_engine.application.ingest import (
    ConversationIn,
    IngestResult,
    MessageIn,
    ingest_conversation,
    ingest_message,
)
from quote_engine.application.ports import Extractor
from quote_engine.application.process import process_next
from quote_engine.domain.catalog import Catalog

ROOT = Path(__file__).parent.parent.parent
CHALLENGE = ROOT / "fixtures" / "challenge"
REPLAY_DIR = ROOT / "fixtures" / "llm_replay"

SessionFactory = async_sessionmaker[AsyncSession]

FBT = "ALFBTC-013-320100"
MCL = "ALMCLC-0909-320100"
MIC = "AVMICS-1A-137050"
ACR = "ARACBL-03-122244"


def fx(name: str) -> dict[str, Any]:
    return json.loads((CHALLENGE / f"{name}.json").read_text())


def replay_extractor(catalog: Catalog) -> Extractor:
    return CascadeExtractor(RuleExtractor(catalog), ReplayExtractor(REPLAY_DIR, catalog))


async def ingest(sf: SessionFactory, payload: dict[str, Any]) -> IngestResult:
    async with UnitOfWork(sf) as uow:
        if "conversation_history" in payload:
            return await ingest_conversation(uow, ConversationIn.model_validate(payload))
        return await ingest_message(uow, MessageIn.model_validate(payload))


async def run_all(sf: SessionFactory, extractor: Extractor, catalog: Catalog) -> int:
    """Process inbox rows until none is claimable; return how many were handled."""
    n = 0
    while await process_next(sf, extractor, catalog):
        n += 1
    return n


async def state(sf: SessionFactory, customer_id: str) -> list[dict[str, Any]]:
    """Quotes of a customer in the challenge's `quotes` JSON shape."""
    async with UnitOfWork(sf) as uow:
        quotes = await uow.quotes.list_by_customer(customer_id)
    return [
        {
            "quote_id": q.id,
            "status": q.status,
            "conversations": sorted(q.conversations),
            "line_items": [{"sku": sku, "qty": qty} for sku, qty in q.line_items()],
        }
        for q in quotes
    ]


async def inbox_rows(sf: SessionFactory) -> list[Any]:
    async with UnitOfWork(sf) as uow:
        return list(
            (
                await uow.session.execute(
                    text(
                        "SELECT seq, dedupe_key, status, attempts, decision, error, processed_at"
                        " FROM inbox ORDER BY seq"
                    )
                )
            ).all()
        )


async def open_reviews(sf: SessionFactory) -> list[Any]:
    async with UnitOfWork(sf) as uow:
        return list(
            (
                await uow.session.execute(
                    text("SELECT * FROM review_items WHERE status = 'open' ORDER BY id")
                )
            ).all()
        )
