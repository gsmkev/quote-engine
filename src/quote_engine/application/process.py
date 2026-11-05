"""Worker use case: claim one inbox row, interpret it, route it, mutate quotes — one transaction."""

import hashlib
import time
from dataclasses import asdict
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from quote_engine.adapters.db.uow import UnitOfWork
from quote_engine.application.ingest import ConversationIn, MessageIn
from quote_engine.application.ports import ConversationCtx, Extractor, MessageCtx
from quote_engine.domain.catalog import Catalog
from quote_engine.domain.interpretation import validate_skus
from quote_engine.domain.quote import Cause, DomainError, Quote
from quote_engine.domain.router import (
    Apply,
    Decision,
    NewQuote,
    NoOp,
    Review,
    merge_lines,
    route,
    route_scores,
)

log = structlog.get_logger()


def synthetic_message_id(conversation_id: str, ts: str, direction: str, text: str) -> str:
    """Stable id for Phase 1 history messages, which arrive without one."""
    digest = hashlib.sha256(f"{ts}|{direction}|{text}".encode()).hexdigest()[:12]
    return f"{conversation_id}:{digest}"


def dump_decision(d: Decision) -> dict[str, Any]:
    match d:
        case Apply(quote_id, ops):
            return {
                "type": "Apply",
                "quote_id": quote_id,
                "ops": [{"op": type(op).__name__, **asdict(op)} for op in ops],
            }
        case NewQuote(lines):
            return {"type": "NewQuote", "lines": [{"sku": s, "qty": q} for s, q in lines]}
        case Review(reason, candidates, proposed):
            return {
                "type": "Review",
                "reason": reason,
                "candidates": candidates,
                "proposed": dump_decision(proposed) if proposed else None,
            }
        case NoOp():
            return {"type": "NoOp"}


async def process_next(
    session_factory: async_sessionmaker[AsyncSession],
    extractor: Extractor,
    catalog: Catalog,
    *,
    max_attempts: int = 3,
    context_window: int = 10,
) -> bool:
    """Handle the next claimable inbox row. Returns False when there is nothing to do.

    Work runs in a savepoint inside the claiming transaction: on error only the work is rolled
    back, and the failure is recorded while the row lock is still held, so no other worker can
    claim the row in between.
    """
    async with UnitOfWork(session_factory) as uow:
        row = await uow.inbox.claim()
        if row is None:
            return False
        seq, customer_id = row["seq"], row["customer_id"]
        structlog.contextvars.bind_contextvars(inbox_seq=seq, customer_id=customer_id)
        try:
            await uow.session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:c))"), {"c": customer_id}
            )
            log.info("claimed", kind=row["kind"])
            try:
                async with uow.session.begin_nested():
                    if row["kind"] == "conversation":
                        status, trace = await _conversation(uow, row, extractor, catalog)
                    else:
                        status, trace = await _message(uow, row, extractor, catalog, context_window)
                    await uow.inbox.finish(seq, status, trace)
            except Exception as e:
                status = await uow.inbox.record_failure(
                    seq, f"{type(e).__name__}: {e}", max_attempts
                )
                log.exception("attempt_failed", status=status)
            await uow.commit()
            return True
        finally:
            structlog.contextvars.clear_contextvars()


async def _message(
    uow: UnitOfWork, row: Any, extractor: Extractor, catalog: Catalog, context_window: int
) -> tuple[str, dict[str, Any]]:
    p = MessageIn.model_validate(row["payload"])
    structlog.contextvars.bind_contextvars(message_id=p.message_id)
    await uow.messages.upsert_customer_conversation(p.customer_id, p.conversation_id)
    history = await uow.messages.recent(p.conversation_id, context_window)
    await uow.messages.add(
        p.message_id, p.conversation_id, p.customer_id, p.direction, p.timestamp, p.text
    )
    if p.direction == "outbound":
        log.info("skipped", reason="outbound")
        return "processed", {"skipped": "outbound"}

    ctx = MessageCtx(p.message_id, p.conversation_id, p.customer_id, p.direction, p.text, history)
    t0 = time.perf_counter()
    interp = await extractor.interpret(ctx)
    latency_ms = round((time.perf_counter() - t0) * 1000, 1)
    if interp is not None:
        try:
            validate_skus(interp, catalog)
        except ValueError:
            log.warning("foreign_sku_rejected", interpretation=interp.model_dump(mode="json"))
            interp = None
    source = interp.source if interp else None
    log.info("interpreted", source=source, latency_ms=latency_ms)

    views = await uow.quotes.open_views(p.customer_id)
    if interp is None:
        decision: Decision = Review("extraction_failed", [v.id for v in views], None)
        scores: dict[str, int] = {}
    else:
        decision = route(interp, p.conversation_id, views)
        scores = route_scores(interp, views)
    interp_json = interp.model_dump(mode="json") if interp else None
    status, decision = await _execute(
        uow, row, decision, p.conversation_id, p.message_id, interp_json
    )
    trace = {
        "extractor_source": source,
        "interpretation": interp_json,
        "scores": scores,
        "decision": dump_decision(decision),
        "latency_ms": latency_ms,
    }
    log.info("routed", decision=trace["decision"], scores=scores)
    return status, trace


async def _conversation(
    uow: UnitOfWork, row: Any, extractor: Extractor, catalog: Catalog
) -> tuple[str, dict[str, Any]]:
    p = ConversationIn.model_validate(row["payload"])
    raw = row["payload"]["conversation_history"]
    await uow.messages.upsert_customer_conversation(p.customer_id, p.conversation_id)
    ids = [
        synthetic_message_id(p.conversation_id, m["timestamp"], m["direction"], m["text"])
        for m in raw
    ]
    for mid, h in zip(ids, p.conversation_history, strict=True):
        await uow.messages.add(
            mid, p.conversation_id, p.customer_id, h.direction, h.timestamp, h.text
        )
    message_id = ids[-1] if ids else None
    structlog.contextvars.bind_contextvars(message_id=message_id)

    views = await uow.quotes.open_views(p.customer_id)
    linked = [v.id for v in views if p.conversation_id in v.conversations]
    extraction = None
    latency_ms = 0.0
    if linked:
        # The thread already feeds a quote: a re-post must not silently spawn a duplicate.
        decision: Decision = Review("ambiguous_quote", linked, None)
    else:
        ctx = ConversationCtx(
            p.conversation_id,
            p.customer_id,
            [(h.direction, h.text) for h in p.conversation_history],
        )
        t0 = time.perf_counter()
        extraction = await extractor.extract_conversation(ctx)
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        if extraction and any(i.sku not in catalog.items for i in extraction.items):
            log.warning("foreign_sku_rejected", extraction=extraction.model_dump(mode="json"))
            extraction = None
        log.info("interpreted", latency_ms=latency_ms)
        if extraction and extraction.items:
            decision = NewQuote(merge_lines([(i.sku, i.qty) for i in extraction.items]))
        else:
            decision = Review("extraction_failed", [v.id for v in views], None)
    extraction_json = extraction.model_dump(mode="json") if extraction else None
    status, decision = await _execute(
        uow, row, decision, p.conversation_id, message_id, extraction_json
    )
    trace = {
        "extractor_source": None,
        "interpretation": extraction_json,
        "scores": {},
        "decision": dump_decision(decision),
        "latency_ms": latency_ms,
    }
    log.info("routed", decision=trace["decision"])
    return status, trace


async def _execute(
    uow: UnitOfWork,
    row: Any,
    decision: Decision,
    conversation_id: str,
    message_id: str | None,
    interpretation: dict[str, Any] | None,
) -> tuple[str, Decision]:
    """Carry out a routing decision; return the inbox status and the decision taken.

    A decision the quote aggregate rejects becomes an `invalid_ops` review: every
    non-success outcome lands in review_items, never in a silent `failed`.
    """
    cause = Cause(message_id)
    quote: Quote | None = None
    try:
        match decision:
            case NewQuote(lines):
                quote = Quote.create(
                    await uow.quotes.next_id(), row["customer_id"], lines, conversation_id, cause
                )
            case Apply(quote_id, ops):
                quote = await uow.quotes.get_for_update(quote_id)
                if quote is None:
                    raise DomainError(f"quote {quote_id} not found")
                quote.apply(ops, cause)
    except DomainError as e:
        log.warning("invalid_ops", error=str(e), decision=dump_decision(decision))
        proposed = decision if isinstance(decision, Apply) else None
        decision = Review("invalid_ops", [proposed.quote_id] if proposed else [], proposed)
        quote = None
    if quote is not None:
        events = [e.type for e in quote.pending_events]
        await uow.quotes.save(quote)
        log.info("applied", quote_id=quote.id, events=events)
        return "processed", decision
    if isinstance(decision, Review):
        review_id = await uow.reviews.add(
            row["seq"],
            row["customer_id"],
            decision.reason,
            decision.candidates,
            interpretation,
            dump_decision(decision.proposed) if decision.proposed else None,
        )
        log.info("review_created", review_id=review_id, reason=decision.reason)
        return "needs_review", decision
    return "processed", decision
