"""Typed table mappings. The schema itself is owned by the Alembic migration."""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class CustomerRow(Base):
    __tablename__ = "customers"
    id: Mapped[str] = mapped_column(primary_key=True)


class ConversationRow(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))


class CatalogRow(Base):
    __tablename__ = "catalog"
    sku: Mapped[str] = mapped_column(primary_key=True)
    description: Mapped[str]
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text))


class QuoteRow(Base):
    __tablename__ = "quotes"
    id: Mapped[str] = mapped_column(primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))
    status: Mapped[str]
    version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuoteLineRow(Base):
    __tablename__ = "quote_lines"
    quote_id: Mapped[str] = mapped_column(ForeignKey("quotes.id"), primary_key=True)
    sku: Mapped[str] = mapped_column(ForeignKey("catalog.sku"), primary_key=True)
    qty: Mapped[int]
    position: Mapped[int]


class QuoteConversationRow(Base):
    __tablename__ = "quote_conversations"
    quote_id: Mapped[str] = mapped_column(ForeignKey("quotes.id"), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), primary_key=True)
    linked_by_message_id: Mapped[str]


class MessageRow(Base):
    __tablename__ = "messages"
    message_id: Mapped[str] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"))
    customer_id: Mapped[str]
    direction: Mapped[str]
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    text: Mapped[str]


class InboxRow(Base):
    __tablename__ = "inbox"
    seq: Mapped[int] = mapped_column(primary_key=True)
    dedupe_key: Mapped[str] = mapped_column(unique=True)
    kind: Mapped[str]
    customer_id: Mapped[str]
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    payload_hash: Mapped[str]
    status: Mapped[str] = mapped_column(server_default="pending")
    attempts: Mapped[int] = mapped_column(server_default="0")
    decision: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None]
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QuoteEventRow(Base):
    __tablename__ = "quote_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    quote_id: Mapped[str] = mapped_column(ForeignKey("quotes.id"))
    message_id: Mapped[str | None]
    review_id: Mapped[int | None]
    type: Mapped[str]
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReviewItemRow(Base):
    __tablename__ = "review_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    inbox_seq: Mapped[int] = mapped_column(ForeignKey("inbox.seq"))
    customer_id: Mapped[str]
    reason: Mapped[str]
    candidate_quote_ids: Mapped[list[str]] = mapped_column(ARRAY(Text))
    interpretation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    proposed: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(server_default="open")
    resolution: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
