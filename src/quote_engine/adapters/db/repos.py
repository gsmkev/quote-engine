from datetime import datetime
from typing import Any, cast

from sqlalchemy import RowMapping, case, delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from quote_engine.adapters.db.models import (
    ConversationRow,
    CustomerRow,
    InboxRow,
    MessageRow,
    QuoteConversationRow,
    QuoteEventRow,
    QuoteLineRow,
    QuoteRow,
    ReviewItemRow,
)
from quote_engine.domain.quote import Line, Quote, QuoteStatus
from quote_engine.domain.router import QuoteView


class QuoteRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def next_id(self) -> str:
        n = (await self.session.execute(text("SELECT nextval('quote_seq')"))).scalar_one()
        return f"Q-{n:03d}"

    async def get_for_update(self, id: str) -> Quote | None:
        row = (
            await self.session.execute(select(QuoteRow).where(QuoteRow.id == id).with_for_update())
        ).scalar_one_or_none()
        return None if row is None else (await self._load([row]))[0]

    async def open_views(self, customer_id: str) -> list[QuoteView]:
        rows = (
            await self.session.execute(
                select(QuoteRow)
                .where(QuoteRow.customer_id == customer_id, QuoteRow.status == "draft")
                .order_by(QuoteRow.id)
            )
        ).scalars()
        return [
            QuoteView(
                q.id, {sku: ln.qty for sku, ln in q.lines.items()}, frozenset(q.conversations)
            )
            for q in await self._load(list(rows))
        ]

    async def get(self, id: str) -> Quote | None:
        row = (
            await self.session.execute(select(QuoteRow).where(QuoteRow.id == id))
        ).scalar_one_or_none()
        return None if row is None else (await self._load([row]))[0]

    async def list_by_customer(self, customer_id: str) -> list[Quote]:
        rows = (
            await self.session.execute(
                select(QuoteRow).where(QuoteRow.customer_id == customer_id).order_by(QuoteRow.id)
            )
        ).scalars()
        return await self._load(list(rows))

    async def history(self, id: str) -> list[dict[str, Any]]:
        rows = (
            await self.session.execute(
                select(QuoteEventRow, MessageRow.text)
                .outerjoin(MessageRow, MessageRow.message_id == QuoteEventRow.message_id)
                .where(QuoteEventRow.quote_id == id)
                .order_by(QuoteEventRow.id)
            )
        ).all()
        return [
            {
                "id": e.id,
                "type": e.type,
                "message_text": text_,
                "payload": e.payload,
                "message_id": e.message_id,
                "review_id": e.review_id,
                "created_at": e.created_at,
            }
            for e, text_ in rows
        ]

    async def save(self, quote: Quote) -> None:
        s = self.session
        stmt = insert(QuoteRow).values(
            id=quote.id, customer_id=quote.customer_id, status=quote.status, version=quote.version
        )
        await s.execute(
            stmt.on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "status": stmt.excluded.status,
                    "version": stmt.excluded.version,
                    "updated_at": func.now(),
                },
            )
        )
        # Sync lines: drop removed SKUs, upsert the rest.
        await s.execute(
            delete(QuoteLineRow).where(
                QuoteLineRow.quote_id == quote.id, QuoteLineRow.sku.not_in(list(quote.lines))
            )
        )
        if quote.lines:
            ls = insert(QuoteLineRow).values(
                [
                    {"quote_id": quote.id, "sku": sku, "qty": ln.qty, "position": ln.position}
                    for sku, ln in quote.lines.items()
                ]
            )
            await s.execute(
                ls.on_conflict_do_update(
                    index_elements=["quote_id", "sku"],
                    set_={"qty": ls.excluded.qty, "position": ls.excluded.position},
                )
            )
        linked_by = {
            e.payload["conversation_id"]: e.cause.message_id
            for e in quote.pending_events
            if e.type == "ConversationLinked"
        }
        if linked_by:
            await s.execute(
                insert(QuoteConversationRow)
                .values(
                    [
                        {
                            "quote_id": quote.id,
                            "conversation_id": conv,
                            "linked_by_message_id": msg or "",
                        }
                        for conv, msg in linked_by.items()
                    ]
                )
                .on_conflict_do_nothing()
            )
        if quote.pending_events:
            await s.execute(
                insert(QuoteEventRow).values(
                    [
                        {
                            "quote_id": quote.id,
                            "message_id": e.cause.message_id,
                            "review_id": e.cause.review_id,
                            "type": e.type,
                            "payload": e.payload,
                        }
                        for e in quote.pending_events
                    ]
                )
            )
        quote.pending_events.clear()

    async def _load(self, rows: list[QuoteRow]) -> list[Quote]:
        ids = [r.id for r in rows]
        lines = (
            await self.session.execute(select(QuoteLineRow).where(QuoteLineRow.quote_id.in_(ids)))
        ).scalars()
        convs = (
            await self.session.execute(
                select(QuoteConversationRow).where(QuoteConversationRow.quote_id.in_(ids))
            )
        ).scalars()
        quotes = {
            r.id: Quote(r.id, r.customer_id, cast(QuoteStatus, r.status), r.version) for r in rows
        }
        for ln in lines:
            quotes[ln.quote_id].lines[ln.sku] = Line(ln.qty, ln.position)
        for c in convs:
            quotes[c.quote_id].conversations.add(c.conversation_id)
        return [quotes[i] for i in ids]


class MessageRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert_customer_conversation(self, customer_id: str, conversation_id: str) -> None:
        await self.session.execute(
            insert(CustomerRow).values(id=customer_id).on_conflict_do_nothing()
        )
        await self.session.execute(
            insert(ConversationRow)
            .values(id=conversation_id, customer_id=customer_id)
            .on_conflict_do_nothing()
        )

    async def add(
        self,
        message_id: str,
        conversation_id: str,
        customer_id: str,
        direction: str,
        ts: datetime,
        text: str,
    ) -> None:
        await self.session.execute(
            insert(MessageRow)
            .values(
                message_id=message_id,
                conversation_id=conversation_id,
                customer_id=customer_id,
                direction=direction,
                ts=ts,
                text=text,
            )
            .on_conflict_do_nothing()
        )

    async def recent(self, conversation_id: str, n: int) -> list[tuple[str, str]]:
        rows = (
            await self.session.execute(
                select(MessageRow.direction, MessageRow.text)
                .where(MessageRow.conversation_id == conversation_id)
                .order_by(MessageRow.ts.desc(), MessageRow.message_id.desc())
                .limit(n)
            )
        ).all()
        return [(d, t) for d, t in reversed(rows)]


class InboxRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def insert(
        self, dedupe_key: str, kind: str, customer_id: str, payload: dict[str, Any], h: str
    ) -> int | None:
        """Insert a pending row; None if dedupe_key already exists."""
        return (
            await self.session.execute(
                insert(InboxRow)
                .values(
                    dedupe_key=dedupe_key,
                    kind=kind,
                    customer_id=customer_id,
                    payload=payload,
                    payload_hash=h,
                )
                .on_conflict_do_nothing(index_elements=["dedupe_key"])
                .returning(InboxRow.seq)
            )
        ).scalar_one_or_none()

    async def existing(self, dedupe_key: str) -> tuple[int, str]:
        row = (
            await self.session.execute(
                select(InboxRow.seq, InboxRow.payload_hash).where(InboxRow.dedupe_key == dedupe_key)
            )
        ).one()
        return row.seq, row.payload_hash

    async def claim(self) -> RowMapping | None:
        """Lock the oldest pending row whose customer has no earlier pending row."""
        return (
            (
                await self.session.execute(
                    text(
                        "SELECT seq, kind, customer_id, payload FROM inbox i"
                        " WHERE i.status = 'pending' AND NOT EXISTS ("
                        "   SELECT 1 FROM inbox e WHERE e.customer_id = i.customer_id"
                        "   AND e.status = 'pending' AND e.seq < i.seq)"
                        " ORDER BY i.seq FOR UPDATE SKIP LOCKED LIMIT 1"
                    )
                )
            )
            .mappings()
            .one_or_none()
        )

    async def finish(self, seq: int, status: str, decision: dict[str, Any]) -> None:
        await self.session.execute(
            update(InboxRow)
            .where(InboxRow.seq == seq)
            .values(status=status, decision=decision, processed_at=func.clock_timestamp())
        )

    async def record_failure(self, seq: int, error: str, fatal: bool, max_attempts: int) -> str:
        """Count a failed attempt; give up when fatal or out of attempts. Returns the new status."""
        attempts = InboxRow.attempts + 1
        status = "failed" if fatal else case((attempts >= max_attempts, "failed"), else_="pending")
        return (
            await self.session.execute(
                update(InboxRow)
                .where(InboxRow.seq == seq)
                .values(attempts=attempts, error=error, status=status)
                .returning(InboxRow.status)
            )
        ).scalar_one()


class ReviewRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(
        self,
        inbox_seq: int,
        customer_id: str,
        reason: str,
        candidate_quote_ids: list[str],
        interpretation: dict[str, Any] | None,
        proposed: dict[str, Any] | None,
    ) -> int:
        return (
            await self.session.execute(
                insert(ReviewItemRow)
                .values(
                    inbox_seq=inbox_seq,
                    customer_id=customer_id,
                    reason=reason,
                    candidate_quote_ids=candidate_quote_ids,
                    interpretation=interpretation,
                    proposed=proposed,
                )
                .returning(ReviewItemRow.id)
            )
        ).scalar_one()

    async def list(self, status: str, customer_id: str | None) -> list[dict[str, Any]]:
        stmt = (
            select(ReviewItemRow, InboxRow.payload)
            .join(InboxRow, InboxRow.seq == ReviewItemRow.inbox_seq)
            .where(ReviewItemRow.status == status)
            .order_by(ReviewItemRow.id)
        )
        if customer_id:
            stmt = stmt.where(ReviewItemRow.customer_id == customer_id)
        return [
            {
                "id": r.id,
                "reason": r.reason,
                "message": {
                    "id": p.get("message_id"),
                    "text": p.get("text"),
                    "conversation_id": p["conversation_id"],
                },
                "candidate_quote_ids": r.candidate_quote_ids,
                "proposed": r.proposed,
            }
            for r, p in (await self.session.execute(stmt)).all()
        ]

    async def get_for_update(self, review_id: int) -> tuple[ReviewItemRow, dict[str, Any]] | None:
        """Lock a review row; also return the payload of its source inbox message."""
        row = (
            await self.session.execute(
                select(ReviewItemRow).where(ReviewItemRow.id == review_id).with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        payload = (
            await self.session.execute(
                select(InboxRow.payload).where(InboxRow.seq == row.inbox_seq)
            )
        ).scalar_one()
        return row, payload

    async def close(self, review_id: int, status: str, resolution: dict[str, Any]) -> None:
        await self.session.execute(
            update(ReviewItemRow)
            .where(ReviewItemRow.id == review_id)
            .values(status=status, resolution=resolution, resolved_at=func.now())
        )
