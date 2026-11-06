"""Deterministic checks on any extractor's output, from the raw text.

Extractors (rules or LLM) may misread phrasing the contract cannot express. These guards never
add a mutation: they downgrade it to a question or give up (None -> human review).
"""

import re

from quote_engine.adapters.extractors.text import norm
from quote_engine.domain.catalog import Catalog
from quote_engine.domain.interpretation import Intent, MessageInterpretation

CANCEL = re.compile(r"\bcancela\w*|\banula\w*|\bya no (?:lo )?quiero\b")
# Words a bare cancel ("mejor cancelalo", "cancela todo porfa") may carry; anything else may
# name what to cancel.
_CANCEL_FILLER = frozenset(
    {
        *("mejor", "todo", "toda", "la", "el", "lo", "mi", "esa", "esta", "eso"),
        *("cotizacion", "pedido", "orden", "por", "favor", "porfa", "plis", "xfa", "pls"),
        *("entonces", "ya", "y", "pues", "ok", "si", "bueno", "oye", "gracias"),
    }
)
# "cancela todo lo que teniamos": the whole quote, unless "todo lo de <something>"
_WHOLE_CANCEL = re.compile(
    r"\b(?:cancel|anul)\w*\s+(?:todo|toda|la cotizacion|el pedido|la orden)\b"
    r"(?!\s+(?:lo\s+)?(?:de|del)\b)"
)
_QUOTE_ID = re.compile(r"\bq-?\d{3}\b")


def is_bare_cancel(t: str) -> bool:
    """A normalised cancel message that names nothing but the cancel itself."""
    rest = re.findall(r"[a-z]+", CANCEL.sub(" ", _QUOTE_ID.sub(" ", t)))
    return all(w in _CANCEL_FILLER for w in rest)


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
_LESS = re.compile(rf"\b(?:quit|rest|baj|descuent|reduc)\w* (\d+)\b|\b(\d+) {_COUNT_UNIT}menos\b")
_MORE = re.compile(rf"\b(\d+) {_COUNT_UNIT}mas\b")
_NEGATOR = re.compile(r"\b(?:no|ni|sin)\b")
_TAKE_AWAY = re.compile(r"\b(?:quit|sac|rest)\w*")
# Order verbs (typos included): with a quantity and no question, a "nothing to do" reading is
# a silent miss.
_ORDER = re.compile(
    r"\bcoti[zs]a(?:me|nos)\b|\bne[cs]e[cs]i(?:to|tamos)\b|\bmanda(?:me|nos)\b|\bk?quiero\b"
    r"|\bkiero\b|\bpon(?:le|me)\b"
)
# "acrilico dorado manejan?": asking whether we carry something is not an order
_ASK = re.compile(r"\b(?:manejan|tienen|venden|hay|trabajan)\b[^?]*\?")
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
        if interp is None:
            return None
        t = norm(text)
        orders = _ORDER.search(t) or _ADDS.search(t)
        if interp.intent not in _MUTATING:
            if (orders or _SETS.search(t)) and _DIGIT.search(t) and "?" not in t:
                return None
            return interp
        if (_PRICE_Q.search(t) or _ASK.search(t)) and not orders:
            # "cuanto me sale si llevo 10 en vez de 20?" asks, it does not order
            return interp.model_copy(update={"intent": Intent.QUERY})
        if _TEMPORAL.search(t):
            return None
        whole = is_bare_cancel(t) or _WHOLE_CANCEL.search(t)
        if interp.intent is Intent.CANCEL and not interp.items and not whole:
            return None  # the extractor dropped what was named; a whole cancel is a guess
        if self._off_alias(interp) or _UNIT.search(t) or (_ADDS.search(t) and _SETS.search(t)):
            return None
        if _SWAP.search(t) or (_MISTAKE.search(t) and not _DIGIT.search(t)):
            return None
        return self._relative(t, interp)

    @staticmethod
    def _relative(t: str, interp: MessageInterpretation) -> MessageInterpretation | None:
        """Relative changes only move one existing line; anything less clear goes to review."""
        less, more = _LESS.search(t), _MORE.search(t)
        if less is None and more is None:
            return interp
        rel = less or more
        assert rel is not None
        if _NEGATOR.search(t, 0, rel.start()) or (less and more):
            return None  # "ya no quiero 2 mas", "no le quites 2": not ours to guess
        if more is not None and interp.intent is Intent.ADD_ITEMS and not _TAKE_AWAY.search(t):
            return interp  # an add already means "on top of what is there"
        if len(interp.items) != 1 or not interp.items[0].in_catalog:
            return None  # which line moves by how much is not ours to guess
        if less is not None:
            if interp.intent is Intent.CREATE_QUOTE:
                return None
            delta = -int(less.group(1) or less.group(2))
        else:
            assert more is not None
            if interp.intent is not Intent.UPDATE_QTY or _TAKE_AWAY.search(t):
                return None  # remove/cancel/create with "N mas" contradicts itself
            delta = int(more.group(1))
        # as a delta on UPDATE_QTY the router only touches a unique existing line, never adds one
        change = {"qty": None, "previous_qty": None, "qty_delta": delta}
        item = interp.items[0].model_copy(update=change)
        return interp.model_copy(update={"intent": Intent.UPDATE_QTY, "items": [item]})
