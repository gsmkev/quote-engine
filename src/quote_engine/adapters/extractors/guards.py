"""Deterministic checks on any extractor's output, from the raw text.

Extractors (rules or LLM) may misread phrasing the contract cannot express. These guards never
add a mutation: they downgrade it to a question or give up (None -> human review).
"""

import re

from quote_engine.adapters.extractors.text import norm
from quote_engine.domain.catalog import Catalog
from quote_engine.domain.interpretation import Intent, MessageInterpretation

_PRICE_Q = re.compile(
    r"\bcuanto (?:me |nos )?(?:sale|salen|saldria|cuesta|cuestan|costaria|seria|serian|cobran)\b"
    r"|\bprecios?\b|\bme sale\b"
)
_MUTATING = {
    Intent.CREATE_QUOTE,
    Intent.ADD_ITEMS,
    Intent.UPDATE_QTY,
    Intent.REMOVE_ITEM,
    Intent.CANCEL,
}


class Guard:
    def __init__(self, catalog: Catalog) -> None:
        self._catalog = catalog

    def __call__(
        self, text: str, interp: MessageInterpretation | None
    ) -> MessageInterpretation | None:
        if interp is None or interp.intent not in _MUTATING:
            return interp
        t = norm(text)
        if _PRICE_Q.search(t):
            # "cuanto me sale si llevo 10 en vez de 20?" asks, it does not order
            return interp.model_copy(update={"intent": Intent.QUERY})
        return interp
