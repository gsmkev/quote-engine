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
# "la de ayer", "lo mismo que la vez pasada": a quote we cannot see; never guess it
_TEMPORAL = re.compile(
    r"\b(?:ayer|antier|anteayer|vez pasada|otra vez|otro dia|semana pasada|mes pasado"
    r"|la anterior|el anterior)\b"
)
# "era el blanco no el transparente": a variant swap, not a quantity change
_SWAP = re.compile(r"\beran? (?:el|la|los|las|de|del)\b.*\bno (?:el|la|los|las|de|del)\b")
_MISTAKE = re.compile(r"\bme equivoque\b")
_DIGIT = re.compile(r"\d")
# Units we do not sell by (we sell rolls, sheets and 1L bottles); a dimension ("x 100 m") is
# not a quantity.
_UNIT = re.compile(
    r"(?<![x.\d])(?<!x )\d+\s*(?:galon(?:es)?|gal|cubetas?|garrafas?|kilos?|kgs?|cajas?"
    r"|paquetes?|metros?|mts?)\b"
)
_ADDS = re.compile(r"\bagrega\w*|\bsuma\w*|\btambien\b")
_SETS = re.compile(r"\bsean\b|\bcambia\w*|\ben vez de\b|\bdeja\w* en\b")
# Relative changes: "quitale 2", "2 menos" / "ponle 2 mas". The number is read here, never
# trusted from the extractor's qty.
_COUNT_UNIT = r"(?:rollos? |piezas? |unidades? |planchas? )?"
_LESS = re.compile(
    rf"\b(?:quita|resta|baja|descuenta|reduce)(?:le|les)? (\d+)\b|\b(\d+) {_COUNT_UNIT}menos\b"
)
_MORE = re.compile(rf"\b(\d+) {_COUNT_UNIT}mas\b")
_MUTATING = {
    Intent.CREATE_QUOTE,
    Intent.ADD_ITEMS,
    Intent.UPDATE_QTY,
    Intent.REMOVE_ITEM,
    Intent.CANCEL,
}


class Guard:
    def __init__(self, catalog: Catalog) -> None:
        aliases: dict[str, set[str]] = {}
        for it in catalog.items.values():
            for a in it.aliases:
                aliases.setdefault(norm(a), set()).add(it.sku)
        self._aliases = aliases
        longest = sorted(aliases, key=len, reverse=True)
        self._alias_re = re.compile(r"\b(?:" + "|".join(map(re.escape, longest)) + r")\b")

    def _off_alias(self, interp: MessageInterpretation) -> bool:
        """An item whose candidates fall outside what its own mention's aliases allow."""
        for it in interp.items:
            hits = [self._aliases[m.group()] for m in self._alias_re.finditer(norm(it.mention))]
            if hits and not set(it.sku_candidates) <= set.intersection(*hits):
                return True
        return False

    def __call__(
        self, text: str, interp: MessageInterpretation | None
    ) -> MessageInterpretation | None:
        if interp is None or interp.intent not in _MUTATING:
            return interp
        t = norm(text)
        if _PRICE_Q.search(t):
            # "cuanto me sale si llevo 10 en vez de 20?" asks, it does not order
            return interp.model_copy(update={"intent": Intent.QUERY})
        if _TEMPORAL.search(t):
            return None
        if self._off_alias(interp) or _UNIT.search(t) or (_ADDS.search(t) and _SETS.search(t)):
            return None
        if _SWAP.search(t) or (_MISTAKE.search(t) and not _DIGIT.search(t)):
            return None
        return self._relative(t, interp)

    @staticmethod
    def _relative(t: str, interp: MessageInterpretation) -> MessageInterpretation | None:
        less, more = _LESS.search(t), _MORE.search(t)
        if less is None and (more is None or interp.intent is Intent.ADD_ITEMS):
            return interp  # an add already means "on top of what is there"
        if len(interp.items) != 1 or not interp.items[0].in_catalog:
            return None  # which line moves by how much is not ours to guess
        if less is not None:
            n = int(less.group(1) or less.group(2))
            change = {"qty": None, "previous_qty": None, "qty_delta": -n}
            intent = Intent.UPDATE_QTY
        else:
            assert more is not None
            change = {"qty": int(more.group(1)), "previous_qty": None}
            intent = Intent.ADD_ITEMS
        item = interp.items[0].model_copy(update=change)
        return interp.model_copy(update={"intent": intent, "items": [item]})
