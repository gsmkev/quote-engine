from enum import StrEnum
from types import GenericAlias
from typing import Any, Literal

from pydantic import BaseModel, PositiveInt, create_model, model_validator
from pydantic.json_schema import SkipJsonSchema

from quote_engine.domain.catalog import Catalog


class Intent(StrEnum):
    CREATE_QUOTE = "create_quote"
    ADD_ITEMS = "add_items"
    UPDATE_QTY = "update_qty"
    REMOVE_ITEM = "remove_item"
    QUERY = "query"
    CANCEL = "cancel"
    NONE = "none"


class ItemMention(BaseModel):
    mention: str
    sku_candidates: list[str]
    in_catalog: bool = True
    qty: PositiveInt | None = None
    previous_qty: PositiveInt | None = None
    # Relative change ("quitale 2" -> -2). Set only by deterministic code, never by the LLM:
    # hidden from the JSON schema the model is constrained by.
    qty_delta: SkipJsonSchema[int | None] = None

    @model_validator(mode="after")
    def _candidates_match_in_catalog(self) -> "ItemMention":
        if self.in_catalog != bool(self.sku_candidates):
            raise ValueError("sku_candidates must be non-empty iff in_catalog")
        return self


class MessageInterpretation(BaseModel):
    intent: Intent
    separate: bool = False
    items: list[ItemMention] = []
    explicit_quote_ids: list[str] = []
    source: Literal["rules", "llm", "replay"]


class ExtractedLine(BaseModel):
    sku: str | None
    qty: PositiveInt
    evidence: str
    in_catalog: bool = True

    @model_validator(mode="after")
    def _sku_matches_in_catalog(self) -> "ExtractedLine":
        if self.in_catalog != (self.sku is not None):
            raise ValueError("sku must be set iff in_catalog")
        return self


class ConversationExtraction(BaseModel):
    items: list[ExtractedLine]


def make_llm_models(
    catalog: Catalog,
) -> tuple[type[MessageInterpretation], type[ConversationExtraction]]:
    """LLM-facing variants whose SKU fields are a Literal over the catalog (JSON-schema enum)."""
    literal: Any = Literal  # subscripted with runtime values: opaque to type checkers
    sku: Any = literal[catalog.skus]
    opt_sku: Any = sku | None
    cand: Any = (GenericAlias(list, (sku,)), ...)
    mention = create_model("LLMItemMention", __base__=ItemMention, sku_candidates=cand)
    line = create_model("LLMExtractedLine", __base__=ExtractedLine, sku=(opt_sku, ...))
    items: Any = (GenericAlias(list, (mention,)), [])
    lines: Any = (GenericAlias(list, (line,)), ...)
    interp = create_model("LLMMessageInterpretation", __base__=MessageInterpretation, items=items)
    extraction = create_model(
        "LLMConversationExtraction", __base__=ConversationExtraction, items=lines
    )
    return interp, extraction


def validate_skus(interp: MessageInterpretation, catalog: Catalog) -> None:
    for item in interp.items:
        foreign = set(item.sku_candidates) - catalog.items.keys()
        if foreign:
            raise ValueError(f"SKU not in catalog: {sorted(foreign)}")
