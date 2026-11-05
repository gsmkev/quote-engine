import re
import unicodedata
from dataclasses import dataclass

from quote_engine.application.ports import ConversationCtx, MessageCtx
from quote_engine.domain.catalog import Catalog
from quote_engine.domain.interpretation import (
    ConversationExtraction,
    Intent,
    ItemMention,
    MessageInterpretation,
    validate_skus,
)

_QUOTE_ID = re.compile(r"\bq-?(\d{3})\b")
_DIM = re.compile(
    r"\d+(?:\.\d+)?\s*x\s*\d+(?:\.\d+)?(?:\s*x\s*\d+(?:\.\d+)?)*(?:\s*(?:mm|cm|m)\b)?"
    r"|\d+(?:\.\d+)?\s*(?:mm|cm|m)\b|\d+\.\d+"
)
_NUM = re.compile(r"\d+")
_QTY = re.compile(r"\b(?:sean|seria|serian|a)\s+(\d+)(?!\.?\d)(?:\s*,?\s*no\s+(\d+)(?!\.?\d))?")
_UNIT = re.compile(r"\s+(?:rollos?|piezas?|unidades?)\b")
_CANCEL = re.compile(r"\bcancela\w*|\banula\w*|\bya no (?:lo )?quiero\b")
_UPDATE = re.compile(r"\bmejor (?:que )?sean\b|\bcambia\w*|\ben vez de\b|\bno \d+")
_ADD = re.compile(r"\bcotiza(?:me|r|nos)?\b|\bagrega\w*|\bsuma\b|\btambien\b|\bnecesito\b")
_QUERY = re.compile(r"\bque lleva\b|\bconfirmas\b|\bcuanto\b|\?$")
_SEPARATE = re.compile(r"\baparte\b|\botra cotizacion\b|\bpor separado\b")
_DIM_REACH = 25


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"(?<=\d),(?=\d)", ".", text)
    return re.sub(r"\s+", " ", text).strip()


def _blank(text: str, spans: list[tuple[int, int]]) -> str:
    for s, e in spans:
        text = text[:s] + " " * (e - s) + text[e:]
    return text


@dataclass
class _Hit:
    start: int
    end: int
    mention: str
    skus: list[str]
    qty: int | None = None
    prev: int | None = None

    def distance(self, pos: int) -> int:
        return max(self.start - pos, pos - self.end, 0)


class _GiveUp(Exception):
    pass


class RuleExtractor:
    """Deterministic first stage: returns None whenever it is not sure."""

    def __init__(self, catalog: Catalog) -> None:
        self._catalog = catalog
        table: dict[str, list[str]] = {}
        for item in catalog.items.values():
            for alias in item.aliases:
                table.setdefault(norm(alias), []).append(item.sku)
        self._aliases = table
        longest_first = sorted(table, key=len, reverse=True)
        self._alias_re = re.compile(r"\b(?:" + "|".join(map(re.escape, longest_first)) + r")\b")
        self._desc = {sku: norm(i.description).replace(" ", "") for sku, i in catalog.items.items()}

    async def interpret(self, ctx: MessageCtx) -> MessageInterpretation | None:
        try:
            result = self._interpret(norm(ctx.text))
        except _GiveUp:
            return None
        if result is not None:
            validate_skus(result, self._catalog)
        return result

    async def extract_conversation(self, ctx: ConversationCtx) -> ConversationExtraction | None:
        return None

    def _interpret(self, t: str) -> MessageInterpretation | None:
        intent = self._intent(t)
        if intent is None:
            return None
        ids = [f"Q-{m.group(1)}" for m in _QUOTE_ID.finditer(t)]
        t = _blank(t, [m.span() for m in _QUOTE_ID.finditer(t)])
        dims = [m for m in _DIM.finditer(t)]
        hits = [
            _Hit(m.start(), m.end(), m.group(), list(self._aliases[m.group()]))
            for m in self._alias_re.finditer(t)
        ]
        for h in hits:
            self._filter_dims(h, dims)
        nums = {m.start(): m for m in _NUM.finditer(_blank(t, [m.span() for m in dims]))}
        unbound = self._bind(t, hits, nums)
        if unbound:
            raise _GiveUp
        sep = bool(_SEPARATE.search(t))
        if intent == Intent.CANCEL:
            if hits:
                raise _GiveUp
            return MessageInterpretation(intent=intent, explicit_quote_ids=ids, source="rules")
        if not hits:
            raise _GiveUp
        if intent in (Intent.UPDATE_QTY, Intent.ADD_ITEMS) and any(h.qty is None for h in hits):
            raise _GiveUp
        items = [
            ItemMention(mention=h.mention, sku_candidates=h.skus, qty=h.qty, previous_qty=h.prev)
            for h in hits
        ]
        return MessageInterpretation(
            intent=intent, separate=sep, items=items, explicit_quote_ids=ids, source="rules"
        )

    @staticmethod
    def _intent(t: str) -> Intent | None:
        for pattern, intent in (
            (_CANCEL, Intent.CANCEL),
            (_UPDATE, Intent.UPDATE_QTY),
            (_ADD, Intent.ADD_ITEMS),
            (_QUERY, Intent.QUERY),
        ):
            if pattern.search(t):
                return intent
        return None

    def _filter_dims(self, hit: _Hit, dims: list[re.Match[str]]) -> None:
        for d in dims:
            if hit.distance(d.start()) > _DIM_REACH and hit.distance(d.end()) > _DIM_REACH:
                continue
            token = d.group().replace(" ", "")
            kept = [s for s in hit.skus if token in self._desc[s]]
            if kept:
                hit.skus = kept

    @staticmethod
    def _bind(t: str, hits: list[_Hit], nums: dict[int, re.Match[str]]) -> list[int]:
        """Bind numbers to hits; return the starts of numbers left unbound."""
        bound: set[int] = set()

        def nearest(pos: int) -> _Hit:
            if not hits:
                raise _GiveUp
            if len(hits) == 1:
                return hits[0]
            ranked = sorted(hits, key=lambda h: h.distance(pos))
            if ranked[0].distance(pos) == ranked[1].distance(pos):
                raise _GiveUp
            return ranked[0]

        def set_qty(hit: _Hit, pos: int, prev: bool = False) -> None:
            value = int(nums[pos].group())
            current = hit.prev if prev else hit.qty
            if current is not None and current != value:
                raise _GiveUp
            if prev:
                hit.prev = value
            else:
                hit.qty = value
            bound.add(pos)

        for m in _QTY.finditer(t):
            pos = m.start(1)
            if pos not in nums:
                continue
            hit = nearest(pos)
            set_qty(hit, pos)
            if m.group(2) and m.start(2) in nums:
                set_qty(hit, m.start(2), prev=True)
        for pos, n in nums.items():
            if _UNIT.match(t, n.end()):
                set_qty(nearest(pos), pos)
                continue
            for h in hits:
                if t[n.end() : h.start].strip() == "" and h.start > n.end():
                    set_qty(h, pos)
        for h in hits:
            m = re.compile(r"\s+(\d+)").match(t, h.end)
            if m and m.start(1) in nums:
                set_qty(h, m.start(1))
        return [p for p in nums if p not in bound]
