import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy import text

from quote_engine.application.ingest import (
    Accepted,
    Conflict,
    ConversationIn,
    Duplicate,
    MessageIn,
    ingest_conversation,
    ingest_message,
)

pytestmark = pytest.mark.integration

FIX = Path(__file__).parent.parent.parent / "fixtures" / "challenge"


def fx(name: str) -> dict:
    return json.loads((FIX / f"{name}.json").read_text())


async def count(uow) -> int:
    return (await uow.session.execute(text("SELECT count(*) FROM inbox"))).scalar_one()


async def test_new_message_accepted(uow_factory):
    async with uow_factory() as uow:
        r = await ingest_message(uow, MessageIn.model_validate(fx("event1")))
        assert isinstance(r, Accepted)
        assert await count(uow) == 1


async def test_same_payload_duplicate(uow_factory):
    p = MessageIn.model_validate(fx("event1"))
    async with uow_factory() as uow:
        a = await ingest_message(uow, p)
    async with uow_factory() as uow:
        d = await ingest_message(uow, p)
        assert isinstance(d, Duplicate)
        assert d.seq == a.seq
        assert await count(uow) == 1


async def test_same_id_different_text_conflict(uow_factory):
    async with uow_factory() as uow:
        a = await ingest_message(uow, MessageIn.model_validate(fx("event1")))
    async with uow_factory() as uow:
        r = await ingest_message(
            uow, MessageIn.model_validate({**fx("event1"), "text": "otra cosa"})
        )
        assert isinstance(r, Conflict)
        assert r.seq == a.seq


async def test_same_text_different_ids_both_accepted(uow_factory):
    async with uow_factory() as uow:
        r1 = await ingest_message(uow, MessageIn.model_validate(fx("event1")))
    async with uow_factory() as uow:
        r2 = await ingest_message(
            uow, MessageIn.model_validate({**fx("event1"), "message_id": "wamid.other"})
        )
        assert isinstance(r1, Accepted)
        assert isinstance(r2, Accepted)
        assert await count(uow) == 2


async def test_concurrent_same_id(uow_factory):
    p = MessageIn.model_validate(fx("event4"))

    async def go():
        async with uow_factory() as uow:
            return await ingest_message(uow, p)

    results = await asyncio.gather(go(), go())
    assert {type(r) for r in results} == {Accepted, Duplicate}
    async with uow_factory() as uow:
        assert await count(uow) == 1


async def test_conversation_accept_then_duplicate(uow_factory):
    p = ConversationIn.model_validate(fx("phase1"))
    async with uow_factory() as uow:
        a = await ingest_conversation(uow, p)
        assert isinstance(a, Accepted)
    async with uow_factory() as uow:
        d = await ingest_conversation(uow, p)
        assert isinstance(d, Duplicate)
        assert d.seq == a.seq
        row = (await uow.session.execute(text("SELECT kind, dedupe_key FROM inbox"))).one()
        assert row.kind == "conversation"
        assert row.dedupe_key.startswith("conv:wa-thread-411:")
