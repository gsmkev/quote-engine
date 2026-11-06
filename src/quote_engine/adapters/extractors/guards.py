"""Deterministic checks on any extractor's output, from the raw text.

Extractors (rules or LLM) may misread phrasing the contract cannot express. These guards never
add a mutation: they downgrade it to a question or give up (None -> human review).
"""

import re

from quote_engine.adapters.extractors.text import norm
from quote_engine.domain.catalog import Catalog
from quote_engine.domain.interpretation import Intent, MessageInterpretation

# What may follow "no quiero" for it to be a removal ("ya no quiero el mesh"): an object, never an
# infinitive ("no quiero cancelar"), "que", or a quantity ("no quiero 10, deja los 20").
_NOT_AN_OBJECT = r"(?!\s+(?:que\b|\w+(?:ar|er|ir)\b|\d))"
CANCEL = re.compile(rf"\bcancela\w*|\banula\w*|\bya no (?:lo )?quiero\b{_NOT_AN_OBJECT}")
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


# Non-assertive messages (questions, hypotheticals) never mutate. Broad on purpose: a miss here
# costs a review, a false "assertive" costs a wrong quote.
# "si agrega 2…", "si mandame 5…": a yes followed by an imperative order, not a conditional
_IMPERATIVE = (
    r"agrega(?:le|me|les)?\b|manda(?:me|le|nos)?\b|cotiza(?:me|nos)?\b|pon(?:le|me)?\b"
    r"|suma(?:le|me)?\b|dame\b|quita(?:le|me)?\b|saca(?:le|me)?\b"
)
_NON_ASSERTIVE = re.compile(
    r"[?¿]|\bcuant[oa]s?\b|\ba como\b|\bque costo\b|\bprecios?\b|\bsaldr\w*|\bcostar\w*"
    r"|\bquedar(?:ia|ian)\b"
    # conditional "si <word>" (not the "si," / "si mira" of a yes)
    r"|\bsi\b(?!\s*(?:[,.!]|$|mira\b|claro\b|por favor\b|porfa\b|gracias\b|perfecto\b|va\b"
    r"|ok\b|dale\b|bueno\b|exacto\b|eso\b|" + _IMPERATIVE + r"))"
    # hedges and deferrals
    r"|\bquizas?\b|\btal vez\b|\ba lo mejor\b|\bigual y\b|\bpuede que\b|\bpensando\b"
    r"|\bseria bueno\b|\bluego te confirmo\b|(?<!\ben )\bespera\w*"
    # deferrals ("cuando me autoricen", "apenas me confirmen") and exploratory phrasing
    r"|\bcuando\b|\bapenas\b|\bestamos viendo\b|\bme interesa\b|\bhabria chance\b"
    r"|\ben una de esas\b|\bserian\b|\bte confirmo\b|\bte aviso\b|\bchec\w*"
    r"|\blo pienso\b|\bpensarlo\b|\bvoy a pensar\b|\bahi lo vemos\b|\bprobablemente\b"
    r"|\bposiblemente\b|\b\d+ o \d+\b|\bentre \d+ y \d+\b"
)
# "cotizame 10 rollos con precio": asking for the price alongside an order keeps it an order
_PRICE_ASIDE = re.compile(r"\b(?:con|me das|me pasas|dame|y)\s+(?:el\s+|su\s+)?precios?\b")
# Order/add verbs: with one present, a non-assertive or no-action reading goes to a human.
_VERBS = re.compile(
    r"\bcoti[zsc](?!acion|ar\b)\w*|\bne[cs]e[cs]i(?:to|tamos)\b"
    r"|\bmanda(?:me|nos)?\b|\bk?quiero\b|\bkiero\b|\bpon(?:e|le|les|me)?\b|\bagreg\w*"
    r"|\bsuma(?:le|les|me)?\b|\bllevo\b|\btambien\b|\bme pasas \d|\bpasame \d|\bdame\b"
    r"|\bocup(?:o|amos)\b"
)
_NUMBER_WORD = (
    r"uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|trece|catorce|quince"
    r"|dieci\w+|veinte|veinti\w+|treinta|cuarenta|cincuenta|cien"
)
_N = rf"(?:\d+|(?:{_NUMBER_WORD})\b)"
# "sean 15, no 20", "son 8 rollos, no 6", "no eran 3 eran 5": a previous quantity, not a negation
_PREV_QTY = re.compile(
    rf"\b(?:sean|son|eran?)\s+{_N}[^,.;]{{0,40}}?,?\s*no\s+(?:de\s+)?{_N}"
    rf"|\bno\s+eran?\s+{_N}\s*,?\s*eran?\s+{_N}"
)
# "ya no quiero el X" is how a removal/cancel is said, not a negated order
_REMOVAL = re.compile(
    rf"\b(?:ya )?no (?:lo |la |los |las |me )?(?:quiero|necesito)\b{_NOT_AN_OBJECT}"
)
# "olvida/olvidate" (forget it) negate; "se me olvido" (I forgot) does not
_NEGATED = re.compile(r"\b(?:no|ni|sin|tampoco|nunca|jamas|olvid(?:a|ate|alo|ala|alos|alas|en))\b")
# "la de ayer", "lo mismo que la vez pasada": a quote we cannot see; never guess it
_TEMPORAL = re.compile(
    r"\b(?:ayer|antier|anteayer|vez pasada|otra vez|otro dia|semana pasada|mes pasado"
    r"|la anterior|el anterior)\b"
)
# "era el blanco no el transparente": a variant swap, not a quantity change
_SWAP = re.compile(
    r"\beran? (?:el|la|los|las|de|del)\b.*\bno (?:el|la|los|las|de|del)\b"
    r"|\bno\b.*\bsino\b|\ben vez de\b.*\bmejor\b"  # "no quiero X sino Y", "en vez de X mejor Y"
)
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
_MUTATING = {
    Intent.CREATE_QUOTE,
    Intent.ADD_ITEMS,
    Intent.UPDATE_QTY,
    Intent.REMOVE_ITEM,
    Intent.CANCEL,
}


def _non_assertive(t: str, verbs: bool) -> bool:
    if verbs and "?" not in t:
        t = _PRICE_ASIDE.sub(" ", t)
    return bool(_NON_ASSERTIVE.search(t))


def _negated(t: str, intent: Intent) -> bool:
    t = _PREV_QTY.sub(" ", t)
    if intent in (Intent.REMOVE_ITEM, Intent.CANCEL) and "deja" not in t:
        t = _REMOVAL.sub(" ", t)
    return bool(_NEGATED.search(t))


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
        if any(it.qty_delta is not None for it in interp.items):
            # only _relative may set a delta, from the text; never trust one from an extractor
            items = [it.model_copy(update={"qty_delta": None}) for it in interp.items]
            interp = interp.model_copy(update={"items": items})
        t = norm(text)
        verbs = bool(_VERBS.search(t))
        hedged = _non_assertive(t, verbs)
        if interp.intent not in _MUTATING:
            ordered = verbs or (_SETS.search(t) and _DIGIT.search(t))
            counted = hedged and any(it.qty is not None for it in interp.items)
            return None if ordered or counted else interp  # an order is never a silent no-op
        if hedged:
            return None  # a question/hedge read as a mutation: never apply, never downgrade
        if _negated(t, interp.intent):
            return None
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
        if _NEGATOR.search(t) or (less and more):
            return None  # "ya no quiero 2 mas", "ponle 2 mas, no 5": not ours to guess
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
