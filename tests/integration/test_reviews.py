import pytest
from helpers import ACR, state
from sqlalchemy import text

from quote_engine.application.reviews import (
    ResolveIn,
    ReviewNotOpen,
    StaleVersion,
    resolve_review,
)
from quote_engine.domain.quote import DomainError

pytestmark = pytest.mark.integration
C = "C-10029"


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
