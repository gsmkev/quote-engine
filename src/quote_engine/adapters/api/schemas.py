from typing import Any

from pydantic import BaseModel

from quote_engine.domain.quote import Quote


class LineOut(BaseModel):
    sku: str
    qty: int


class QuoteOut(BaseModel):
    quote_id: str
    status: str
    conversations: list[str]
    line_items: list[LineOut]

    @classmethod
    def of(cls, q: Quote) -> "QuoteOut":
        return cls(
            quote_id=q.id,
            status=q.status,
            conversations=sorted(q.conversations),
            line_items=[LineOut(sku=s, qty=n) for s, n in q.line_items()],
        )


class QuoteDetail(QuoteOut):
    document_type: str = "Oferta_de_Venta"


class QuoteVersion(QuoteOut):
    version: int


def quote_version(q: Quote) -> dict[str, Any]:
    return QuoteVersion(**QuoteOut.of(q).model_dump(), version=q.version).model_dump()
