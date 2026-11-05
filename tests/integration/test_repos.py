import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from quote_engine.domain.quote import Cause, Quote

pytestmark = pytest.mark.integration

SKUS = ["ALFBTC-013-320100", "ALMCLC-0909-320100", "AVMICS-1A-137050"]


async def make_quote(uow, conv="wa-thread-411", cust="C1", msg="m1"):
    await uow.messages.upsert_customer_conversation(cust, conv)
    q = Quote.create(
        await uow.quotes.next_id(),
        cust,
        [(SKUS[0], 10), (SKUS[1], 5), (SKUS[2], 2)],
        conv,
        Cause(msg),
    )
    await uow.quotes.save(q)
    return q


async def test_next_id_format(uow_factory):
    async with uow_factory() as uow:
        assert await uow.quotes.next_id() == "Q-001"
        assert await uow.quotes.next_id() == "Q-002"


async def test_save_and_load_roundtrip(uow_factory):
    async with uow_factory() as uow:
        q = await make_quote(uow)
        await uow.commit()
    assert q.pending_events == []
    async with uow_factory() as uow:
        got = await uow.quotes.get_for_update(q.id)
        assert got is not None
        assert got.line_items() == q.line_items()
        assert got.conversations == {"wa-thread-411"}
        assert got.version == q.version
        assert await uow.quotes.get_for_update("Q-999") is None


async def test_save_syncs_lines_and_links(uow_factory):
    from quote_engine.domain.quote import AddLine, LinkConversation, RemoveLine, SetQty

    async with uow_factory() as uow:
        q = await make_quote(uow)
        await uow.messages.upsert_customer_conversation("C1", "wa-2")
        await uow.commit()
    async with uow_factory() as uow:
        q = await uow.quotes.get_for_update(q.id)
        q.apply(
            [
                RemoveLine(SKUS[1]),
                SetQty(SKUS[0], 7),
                AddLine(SKUS[1], 1),
                LinkConversation("wa-2"),
            ],
            Cause("m2"),
        )
        await uow.quotes.save(q)
        await uow.commit()
    async with uow_factory() as uow:
        got = await uow.quotes.get_for_update(q.id)
        assert got.line_items() == [(SKUS[0], 7), (SKUS[2], 2), (SKUS[1], 1)]
        assert got.conversations == {"wa-thread-411", "wa-2"}
        assert got.version == 2


async def test_events_persisted_with_cause(uow_factory):
    async with uow_factory() as uow:
        q = await make_quote(uow)
        await uow.commit()
    async with uow_factory() as uow:
        hist = await uow.quotes.history(q.id)
        assert hist[0]["type"] == "QuoteCreated"
        assert hist[0]["message_id"] == "m1"
        assert [h["type"] for h in hist].count("LineAdded") == 3


async def test_fk_rejects_foreign_sku(uow_factory):
    async with uow_factory() as uow:
        q = await make_quote(uow)
        with pytest.raises(IntegrityError):
            await uow.session.execute(
                text("INSERT INTO quote_lines VALUES (:q, 'FAKE-1', 1, 9)"), {"q": q.id}
            )


async def test_open_views_excludes_cancelled(uow_factory):
    from quote_engine.domain.quote import Cancel

    async with uow_factory() as uow:
        a = await make_quote(uow, msg="m1")
        b = await make_quote(uow, msg="m2")
        a.apply([Cancel()], Cause("m3"))
        await uow.quotes.save(a)
        await uow.commit()
    async with uow_factory() as uow:
        views = await uow.quotes.open_views("C1")
        assert [v.id for v in views] == [b.id]
        assert views[0].lines[SKUS[0]] == 10
        assert views[0].conversations == frozenset({"wa-thread-411"})
        assert [q.id for q in await uow.quotes.list_by_customer("C1")] == [a.id, b.id]


async def test_messages_add_and_recent(uow_factory):
    from datetime import UTC, datetime, timedelta

    t = datetime(2026, 1, 1, tzinfo=UTC)
    async with uow_factory() as uow:
        await uow.messages.upsert_customer_conversation("C1", "c")
        await uow.messages.upsert_customer_conversation("C1", "c")
        for i in range(3):
            await uow.messages.add(f"m{i}", "c", "C1", "inbound", t + timedelta(minutes=i), f"t{i}")
        await uow.messages.add("m0", "c", "C1", "inbound", t, "dup")
        assert await uow.messages.recent("c", 2) == [("inbound", "t1"), ("inbound", "t2")]
