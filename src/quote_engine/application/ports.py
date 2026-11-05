from dataclasses import dataclass
from typing import Protocol

from quote_engine.domain.interpretation import ConversationExtraction, MessageInterpretation


@dataclass
class MessageCtx:
    message_id: str
    conversation_id: str
    customer_id: str
    direction: str
    text: str
    history: list[tuple[str, str]]  # (direction, text)


@dataclass
class ConversationCtx:
    conversation_id: str
    customer_id: str
    messages: list[tuple[str, str]]  # (direction, text)


class Extractor(Protocol):
    async def interpret(self, ctx: MessageCtx) -> MessageInterpretation | None: ...

    async def extract_conversation(self, ctx: ConversationCtx) -> ConversationExtraction | None: ...
