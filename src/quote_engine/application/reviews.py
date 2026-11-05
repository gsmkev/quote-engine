from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import text

from quote_engine.adapters.db.uow import UnitOfWork
from quote_engine.application.process import synthetic_message_id
from quote_engine.domain import quote as q
from quote_engine.domain.quote import Cause, DomainError, Quote


class CancelIn(BaseModel):
    op: Literal["cancel"]


class SetQtyIn(BaseModel):
    op: Literal["set_qty"]
    sku: str
    qty: int


class AddLineIn(BaseModel):
    op: Literal["add_line"]
    sku: str
    qty: int


class RemoveLineIn(BaseModel):
    op: Literal["remove_line"]
    sku: str


class LinkConversationIn(BaseModel):
    op: Literal["link_conversation"]
    conversation_id: str | None = None


OpIn = Annotated[
    CancelIn | SetQtyIn | AddLineIn | RemoveLineIn | LinkConversationIn, Field(discriminator="op")
]


class ResolveIn(BaseModel):
    action: Literal["apply", "dismiss"]
    quote_id: str | None = None
    expected_version: int | None = None
    ops: list[OpIn] = []
    new_quote: bool = False


class ReviewNotOpen(Exception):
    pass


class StaleVersion(Exception):
    def __init__(self, current: Quote):
        super().__init__(f"quote {current.id} is at version {current.version}")
        self.current = current


def _to_domain(op: Any, default_conv: str) -> q.Op:
    match op:
        case CancelIn():
            return q.Cancel()
        case SetQtyIn():
            return q.SetQty(op.sku, op.qty)
        case AddLineIn():
            return q.AddLine(op.sku, op.qty)
        case RemoveLineIn():
            return q.RemoveLine(op.sku)
        case LinkConversationIn():
            return q.LinkConversation(op.conversation_id or default_conv)
    raise DomainError(f"unknown op {op!r}")


def _source_message_id(payload: dict[str, Any]) -> str | None:
    """The message a review stems from; Phase 1 conversations use their last message's id."""
    if "message_id" in payload:
        return payload["message_id"]
    history = payload.get("conversation_history") or []
    if not history:
        return None
    last = history[-1]
    return synthetic_message_id(
        payload["conversation_id"], last["timestamp"], last["direction"], last["text"]
    )


async def resolve_review(
    uow: UnitOfWork, review_id: int, body: ResolveIn
) -> tuple[dict[str, Any], Quote | None]:
    """Resolve a review in one transaction; any failure rolls back and leaves it open."""
    try:
        found = await uow.reviews.get_for_update(review_id)
        if found is None or found[0].status != "open":
            raise ReviewNotOpen(f"review {review_id} is not open")
        review, payload = found
        await uow.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:c))"), {"c": review.customer_id}
        )
        quote: Quote | None = None
        if body.action == "apply":
            cause = Cause(_source_message_id(payload), review_id)
            conv = payload["conversation_id"]
            ops = [_to_domain(o, conv) for o in body.ops]
            if body.new_quote:
                lines = [(o.sku, o.qty) for o in ops if isinstance(o, q.AddLine)]
                quote = Quote.create(
                    await uow.quotes.next_id(), review.customer_id, lines, conv, cause
                )
            else:
                if body.quote_id is None or body.expected_version is None:
                    raise ValueError("quote_id and expected_version are required")
                quote = await uow.quotes.get_for_update(body.quote_id)
                if quote is None or quote.customer_id != review.customer_id:
                    raise DomainError(f"quote {body.quote_id} not found")
                if quote.version != body.expected_version:
                    raise StaleVersion(quote)
                quote.apply(ops, cause)
            await uow.quotes.save(quote)
        resolution = body.model_dump(mode="json")
        status = "resolved" if body.action == "apply" else "dismissed"
        await uow.reviews.close(review_id, status, resolution)
        await uow.commit()
    except BaseException:
        await uow.rollback()
        raise
    return {
        "id": review_id,
        "status": status,
        "reason": review.reason,
        "resolution": resolution,
    }, quote
