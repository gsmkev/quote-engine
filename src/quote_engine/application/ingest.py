import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from quote_engine.adapters.db.uow import UnitOfWork


class MessageIn(BaseModel):
    message_id: str
    conversation_id: str
    customer_id: str
    direction: Literal["inbound", "outbound"]
    timestamp: datetime
    text: str


class HistoryItem(BaseModel):
    direction: Literal["inbound", "outbound"]
    timestamp: datetime
    text: str


class ConversationIn(BaseModel):
    customer_id: str
    conversation_id: str
    customer_name: str
    conversation_history: list[HistoryItem]


@dataclass(frozen=True)
class Accepted:
    seq: int


@dataclass(frozen=True)
class Duplicate:
    seq: int


@dataclass(frozen=True)
class Conflict:
    seq: int


IngestResult = Accepted | Duplicate | Conflict


def canonical_hash(obj: Any) -> str:
    s = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(s.encode()).hexdigest()


async def _ingest(
    uow: UnitOfWork, key: str, kind: str, p: MessageIn | ConversationIn, h: str
) -> IngestResult:
    seq = await uow.inbox.insert(key, kind, p.customer_id, p.model_dump(mode="json"), h)
    if seq is not None:
        await uow.commit()
        return Accepted(seq)
    seq, existing_hash = await uow.inbox.existing(key)
    return Duplicate(seq) if existing_hash == h else Conflict(seq)


async def ingest_message(uow: UnitOfWork, p: MessageIn) -> IngestResult:
    return await _ingest(uow, p.message_id, "message", p, canonical_hash(p.model_dump(mode="json")))


async def ingest_conversation(uow: UnitOfWork, p: ConversationIn) -> IngestResult:
    h = canonical_hash(p.model_dump(mode="json"))
    return await _ingest(uow, f"conv:{p.conversation_id}:{h[:16]}", "conversation", p, h)
