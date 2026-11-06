import time
from typing import Any, Literal

import instructor
import structlog
from openai import AsyncOpenAI
from pydantic import BaseModel, create_model

from quote_engine.application.ports import ConversationCtx, MessageCtx
from quote_engine.config import Settings
from quote_engine.domain.catalog import Catalog
from quote_engine.domain.interpretation import (
    ConversationExtraction,
    MessageInterpretation,
    make_llm_models,
)

log = structlog.get_logger()

MESSAGE_SYSTEM = """\
You extract structured quote intent from one WhatsApp message (Spanish) sent in a sales chat \
for a printing-materials distributor. Earlier messages are context only.

Catalog (the ONLY valid SKUs):
{catalog}

Rules:
- intent: create_quote | add_items | update_qty | remove_item | query | cancel | none.
- Only use SKUs from the catalog. For each product mention, set sku_candidates to every \
plausible SKU when the mention is ambiguous (e.g. "lonas" with no type or size matches several).
- Check every stated size, thickness and colour against the catalog. If the requested product, \
size, thickness or colour is NOT in the catalog, return the item with in_catalog=false and \
sku_candidates=[]; never pick the closest SKU.
- A new request for "lona" with no type means Frontlit; for references to lines already \
discussed, list every plausible candidate instead.
- Never invent quantities: qty is null unless the message states it.
- For update_qty ("mejor que sean 15, no 20"): qty is the new quantity, previous_qty the old one.
- explicit_quote_ids: quote ids like Q-001 mentioned in the message.
- separate is true only if the customer asks for a separate/new quote.
- For add_items, update_qty and remove_item, items MUST list every product the message refers \
to, resolving vague mentions ("las lonas", "esas") with the earlier messages; never leave items \
empty for them. items is empty only for cancel, none, or a query without products.

Example: MESSAGE "cotizame 2 acrilicos negros de 10mm" (no such thickness) -> intent \
create_quote, items [{{mention: "acrilicos negros de 10mm", sku_candidates: [], in_catalog: \
false, qty: 2}}].

Example: earlier "Necesito 10 rollos de mesh 3.20x100", MESSAGE "mejor que sean 8 \
de los mesh, no 10" -> intent update_qty, items [{{mention: "los mesh", sku_candidates: \
[the mesh SKU], qty: 8, previous_qty: 10}}].
"""

CONVERSATION_SYSTEM = """\
You read a complete WhatsApp sales conversation (Spanish) between a customer (inbound) and a \
sales rep (outbound), and list the products the customer finally wants to be quoted.

Catalog (the ONLY valid SKUs):
{catalog}

Rules:
- The rep's outbound replies can confirm or narrow a variant (e.g. the rep proposes a size \
and the customer agrees).
- Only emit items with BOTH a confirmed variant (exactly one SKU) and a quantity stated by \
the customer. Never invent quantities.
- If the customer wants a product, size, thickness or colour that is NOT in the catalog, emit \
the item with in_catalog=false and sku=null; never pick the closest SKU.
- "lona" with no type means Frontlit.
- Skip variants the rep said are unavailable and anything not confirmed.
- evidence: a short quote from the conversation supporting the item.
"""


def _catalog_table(catalog: Catalog) -> str:
    return "\n".join(f"{i.sku} | {i.description}" for i in catalog.items.values())


def _transcript(messages: list[tuple[str, str]]) -> str:
    return "\n".join(f"[{d}] {t}" for d, t in messages)


class LLMExtractor:
    """Local-model extractor (Instructor + Docker Model Runner); returns None on any failure."""

    def __init__(self, settings: Settings, catalog: Catalog) -> None:
        self._settings = settings
        self._client = instructor.from_openai(
            AsyncOpenAI(base_url=settings.llm_base_url, api_key="dmr"),
            mode=instructor.Mode.JSON_SCHEMA,
        )
        interp, self._extraction = make_llm_models(catalog)
        # the model never fills `source`; it defaults to "llm"
        self._interp: type[MessageInterpretation] = create_model(
            "LLMInterpretation", __base__=interp, source=(Literal["llm"], "llm")
        )
        table = _catalog_table(catalog)
        self._msg_system = MESSAGE_SYSTEM.format(catalog=table)
        self._conv_system = CONVERSATION_SYSTEM.format(catalog=table)

    async def _call[T: BaseModel](
        self, model: type[T], system: str, user: str, what: str
    ) -> T | None:
        start = time.monotonic()
        try:
            kwargs: dict[str, Any] = {
                "model": self._settings.llm_model,
                "response_model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0,
                "max_retries": self._settings.llm_max_retries,
                "timeout": self._settings.llm_timeout_s,
            }
            result = await self._client.chat.completions.create(**kwargs)
        except Exception as e:
            log.warning(
                "llm_failed",
                what=what,
                error=repr(e),
                latency_ms=int((time.monotonic() - start) * 1000),
            )
            return None
        log.info("llm_ok", what=what, latency_ms=int((time.monotonic() - start) * 1000))
        return result

    async def interpret(self, ctx: MessageCtx) -> MessageInterpretation | None:
        n = self._settings.context_window_messages
        user = f"{_transcript(ctx.history[-n:])}\n\nMESSAGE: {ctx.text}"
        result = await self._call(self._interp, self._msg_system, user, "interpret")
        if result is None:
            return None
        return result.model_copy(update={"source": "llm"})

    async def extract_conversation(self, ctx: ConversationCtx) -> ConversationExtraction | None:
        return await self._call(
            self._extraction, self._conv_system, _transcript(ctx.messages), "extract_conversation"
        )
