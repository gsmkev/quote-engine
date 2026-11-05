import pytest
from helpers import ACR, fx, ingest, open_reviews, run_all, state
from sqlalchemy import text

from quote_engine.application.process import synthetic_message_id
from quote_engine.application.reviews import (
    ResolveIn,
    ReviewNotOpen,
    StaleVersion,
    resolve_review,
)
from quote_engine.domain.quote import DomainError

pytestmark = pytest.mark.integration
C = "C-10029"
T411 = "wa-thread-411"


def body(**kw) -> ResolveIn:
    return ResolveIn.model_validate(
        {"action": "apply", "quote_id": "Q-002", "expected_version": 2, **kw}
    )


async def version(sf, quote_id="Q-002") -> int:
    async with sf() as s:
        return (
            await s.execute(text("SELECT version FROM quotes WHERE id=:i"), {"i": quote_id})
        ).scalar_one()


async def review_status(sf, rid) -> str:
    async with sf() as s:
        return (
            await s.execute(text("SELECT status FROM review_items WHERE id=:i"), {"i": rid})
        ).scalar_one()


async def test_apply_cancel(seeded_after_cancel, session_factory, uow_factory):
    rid = seeded_after_cancel
    v = await version(session_factory)
    async with uow_factory() as uow:
        review, quote = await resolve_review(
            uow, rid, body(expected_version=v, ops=[{"op": "cancel"}])
        )
        history = await uow.quotes.history("Q-002")
    assert quote is not None
    assert review["status"] == "resolved" and quote.status == "cancelled"
    assert (await state(session_factory, C))[1]["status"] == "cancelled"
    assert await review_status(session_factory, rid) == "resolved"
    last = history[-1]
    assert (last["type"], last["review_id"], last["message_id"]) == (
        "QuoteCancelled",
        rid,
        "wamid.411.0233",
    )


async def test_stale_version(seeded_after_cancel, session_factory, uow_factory):
    before = await state(session_factory, C)
    async with uow_factory() as uow:
        with pytest.raises(StaleVersion):
            await resolve_review(
                uow, seeded_after_cancel, body(expected_version=1, ops=[{"op": "cancel"}])
            )
    assert await state(session_factory, C) == before
    assert await review_status(session_factory, seeded_after_cancel) == "open"


async def test_resolve_twice(seeded_after_cancel, session_factory, uow_factory):
    v = await version(session_factory)
    async with uow_factory() as uow:
        await resolve_review(
            uow, seeded_after_cancel, body(expected_version=v, ops=[{"op": "cancel"}])
        )
    async with uow_factory() as uow:
        with pytest.raises(ReviewNotOpen):
            await resolve_review(
                uow, seeded_after_cancel, body(expected_version=v, ops=[{"op": "cancel"}])
            )


async def test_dismiss(seeded_after_cancel, session_factory, uow_factory):
    before = await state(session_factory, C)
    async with uow_factory() as uow:
        review, quote = await resolve_review(uow, seeded_after_cancel, ResolveIn(action="dismiss"))
    assert (review["status"], quote) == ("dismissed", None)
    assert await state(session_factory, C) == before


async def test_domain_error_rolls_back(seeded_after_cancel, session_factory, uow_factory):
    before = await state(session_factory, C)
    v = await version(session_factory)
    async with uow_factory() as uow:
        with pytest.raises(DomainError):
            await resolve_review(
                uow,
                seeded_after_cancel,
                body(
                    expected_version=v,
                    ops=[{"op": "set_qty", "sku": "ALFBTC-013-320100", "qty": 3}],
                ),
            )
    assert await state(session_factory, C) == before
    assert await review_status(session_factory, seeded_after_cancel) == "open"


async def test_new_quote(seeded_after_cancel, session_factory, uow_factory):
    async with uow_factory() as uow:
        _, quote = await resolve_review(
            uow,
            seeded_after_cancel,
            ResolveIn(
                action="apply", new_quote=True, ops=[{"op": "add_line", "sku": ACR, "qty": 2}]
            ),
        )
    assert quote is not None
    assert quote.id == "Q-003" and quote.line_items() == [(ACR, 2)]
    assert quote.conversations == {"wa-thread-411"}


class NoExtraction:
    async def interpret(self, ctx):
        return None

    async def extract_conversation(self, ctx):
        return None


async def test_resolve_conversation_review_new_quote(session_factory, uow_factory, catalog):
    await ingest(session_factory, fx("phase1"))
    await run_all(session_factory, NoExtraction(), catalog)
    [review] = await open_reviews(session_factory)
    assert review.reason == "extraction_failed"
    async with uow_factory() as uow:
        _, quote = await resolve_review(
            uow,
            review.id,
            ResolveIn(
                action="apply", new_quote=True, ops=[{"op": "add_line", "sku": ACR, "qty": 2}]
            ),
        )
    assert quote is not None
    assert quote.line_items() == [(ACR, 2)] and quote.conversations == {T411}
    last = fx("phase1")["conversation_history"][-1]
    mid = synthetic_message_id(T411, last["timestamp"], last["direction"], last["text"])
    async with uow_factory() as uow:
        history = await uow.quotes.history(quote.id)
        linked_by = (
            await uow.session.execute(
                text("SELECT linked_by_message_id FROM quote_conversations WHERE quote_id=:q"),
                {"q": quote.id},
            )
        ).scalar_one()
    assert {(e["message_id"], e["review_id"]) for e in history} == {(mid, review.id)}
    assert history[0]["message_text"] == last["text"]
    assert linked_by == mid


async def expect_422(sf, uow_factory, rid, resolve: ResolveIn) -> None:
    before = await state(sf, C)
    async with uow_factory() as uow:
        with pytest.raises(DomainError):
            await resolve_review(uow, rid, resolve)
    assert await state(sf, C) == before
    assert await review_status(sf, rid) == "open"


@pytest.mark.parametrize("op", ["add_line", "set_qty"])
async def test_non_catalog_sku_rejected(seeded_after_cancel, session_factory, uow_factory, op):
    v = await version(session_factory)
    bad = body(expected_version=v, ops=[{"op": op, "sku": "NOPE-1", "qty": 1}])
    await expect_422(session_factory, uow_factory, seeded_after_cancel, bad)


async def test_unknown_conversation_rejected(seeded_after_cancel, session_factory, uow_factory):
    v = await version(session_factory)
    bad = body(expected_version=v, ops=[{"op": "link_conversation", "conversation_id": "nope"}])
    await expect_422(session_factory, uow_factory, seeded_after_cancel, bad)


async def test_foreign_conversation_rejected(seeded_after_cancel, session_factory, uow_factory):
    async with session_factory() as s:
        await s.execute(text("INSERT INTO customers VALUES ('C-OTHER')"))
        await s.execute(text("INSERT INTO conversations VALUES ('wa-other', 'C-OTHER')"))
        await s.commit()
    v = await version(session_factory)
    bad = body(expected_version=v, ops=[{"op": "link_conversation", "conversation_id": "wa-other"}])
    await expect_422(session_factory, uow_factory, seeded_after_cancel, bad)


@pytest.mark.parametrize(
    "ops",
    [[], [{"op": "add_line", "sku": ACR, "qty": 2}, {"op": "cancel"}]],
    ids=["no-add-line", "non-add-line-op"],
)
async def test_new_quote_ops_validated(seeded_after_cancel, session_factory, uow_factory, ops):
    bad = ResolveIn(action="apply", new_quote=True, ops=ops)
    await expect_422(session_factory, uow_factory, seeded_after_cancel, bad)
