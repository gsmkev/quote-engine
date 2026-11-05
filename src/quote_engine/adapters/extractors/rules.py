import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

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
_UNITS = r"(?:milimetros?|mm|centimetros?|cm|metros?|m)\b"
_DIM = re.compile(
    rf"\d+(?:\.\d+)?\s*x\s*\d+(?:\.\d+)?(?:\s*x\s*\d+(?:\.\d+)?)*(?:\s*{_UNITS})?"
    rf"|\d+(?:\.\d+)?\s*{_UNITS}|\d+\.\d+"
)
_DECIMAL = re.compile(r"\d+(?:\.\d+)?")
_COLOURS = {
    "blanco": r"blanc[oa]s?|white",
    "negro": r"negr[oa]s?|black",
    "transparente": r"transparentes?|cristal(?:es)?",
    "amarillo": r"amarill[oa]s?|yellow",
    "cyan": r"cyan|cian",
    "magenta": r"magentas?",
    "rojo": r"roj[oa]s?",
    "azul": r"azul(?:es)?",
    "verde": r"verdes?",
    "gris": r"gris(?:es)?",
    "naranja": r"naranjas?",
    "morado": r"morad[oa]s?",
    "dorado": r"dorad[oa]s?",
    "plateado": r"platead[oa]s?",
}
_COLOUR = re.compile(r"\b(?:" + "|".join(f"(?P<{k}>{v})" for k, v in _COLOURS.items()) + r")\b")
_NEGATOR = re.compile(r"\b(?:no|sin|excepto|menos|salvo)\b")
_NUM = re.compile(r"\d+")
_QTY = re.compile(r"\b(?:sean|seria|serian|a)\s+(\d+)(?!\.?\d)(?:\s*,?\s*no\s+(\d+)(?!\.?\d))?")
_UNIT = re.compile(r"\s+(?:rollos?|piezas?|unidades?)\b")
_CANCEL = re.compile(r"\bcancela\w*|\banula\w*|\bya no (?:lo )?quiero\b")
_UPDATE = re.compile(r"\bmejor (?:que )?sean\b|\bcambia\w*|\ben vez de\b")
_ADD = re.compile(r"\bcotiza(?:me|s|r|nos)?\b|\bagrega\w*|\bsuma\b|\btambien\b|\bnecesito\b")
_QUERY = re.compile(r"\bque lleva\b|\bconfirmas\b|\bcuanto\b|\?$")
_NO_N = re.compile(r"\bno\s+(\d+)")
_NEGATED = re.compile(r"\bno (?:me |lo |la )?(?:cancel|anul)\w*")
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


_MODELLED = {"size": "width_m", "thickness": "thickness_mm", "color": "color"}


def _parse_dim(token: str) -> tuple[str, Any]:
    """Classify a dimension token as ("size", (w, l|None)) or ("thickness", mm)."""
    nums = tuple(float(n) for n in _DECIMAL.findall(token))
    unit_match = re.search(r"[a-wyz]+$", token)
    unit = unit_match.group() if unit_match else "m"
    if unit.startswith(("mm", "mili")) and len(nums) == 1:
        return "thickness", nums[0]
    if unit in ("m", "metro", "metros") and len(nums) == 2:
        if not unit_match and "." not in token.split("x")[0] and nums[0] >= 10:
            raise _GiveUp  # "320x100" is probably cm
        return "size", nums
    if unit in ("m", "metro", "metros") and len(nums) == 1 and "." in token:
        return "size", (nums[0], None)
    raise _GiveUp


def _close(a: Any, b: float) -> bool:
    return isinstance(a, float | int) and math.isclose(a, b, abs_tol=1e-6)


def _satisfies(attrs: dict[str, str | float], kind: str, value: Any) -> bool:
    if kind == "color":
        return attrs.get("color") == value
    if kind == "thickness":
        return _close(attrs.get("thickness_mm"), value)
    width, length = value
    if length is None:
        return _close(attrs.get("width_m"), width) or _close(attrs.get("length_m"), width)
    weave = str(attrs.get("weave", ""))
    return (
        _close(attrs.get("width_m"), width) and _close(attrs.get("length_m"), length)
    ) or weave == f"{width:g}x{length:g}"


def _owner(hits: list[_Hit], start: int, end: int) -> _Hit:
    """The hit an attribute belongs to: nearest one before it, else nearest one after it."""
    before = [h for h in hits if h.end <= start and start - h.end <= _DIM_REACH]
    if before:
        return max(before, key=lambda h: h.end)
    after = [h for h in hits if h.start >= end and h.start - end <= _DIM_REACH]
    if after:
        return min(after, key=lambda h: h.start)
    raise _GiveUp


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
        if _NEGATED.search(t):
            raise _GiveUp
        prev_pos = {m.start(2) for m in _QTY.finditer(t) if m.group(2)}
        if any(m.start(1) not in prev_pos for m in _NO_N.finditer(t)):
            raise _GiveUp
        ids = [f"Q-{m.group(1)}" for m in _QUOTE_ID.finditer(t)]
        t = _blank(t, [m.span() for m in _QUOTE_ID.finditer(t)])
        dims = list(_DIM.finditer(t))
        hits = [
            _Hit(m.start(), m.end(), m.group(), list(self._aliases[m.group()]))
            for m in self._alias_re.finditer(t)
        ]
        self._filter_attrs(t, hits, dims)
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
        if intent == Intent.QUERY and any(h.qty is not None for h in hits):
            raise _GiveUp
        if intent in (Intent.UPDATE_QTY, Intent.ADD_ITEMS) and any(h.qty is None for h in hits):
            raise _GiveUp
        items = [
            ItemMention(
                mention=h.mention,
                sku_candidates=h.skus,
                in_catalog=bool(h.skus),
                qty=h.qty,
                previous_qty=h.prev,
            )
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

    def _filter_attrs(self, t: str, hits: list[_Hit], dims: list[re.Match[str]]) -> None:
        """Narrow each hit by the explicit attributes next to it; empty means not in catalog."""
        free = _blank(t, [(h.start, h.end) for h in hits])
        tokens = [(d.start(), d.end(), *_parse_dim(d.group())) for d in dims] + [
            (m.start(), m.end(), "color", m.lastgroup) for m in _COLOUR.finditer(free)
        ]
        if tokens and any(m.start() not in self._prev_qty(t) for m in _NEGATOR.finditer(t)):
            raise _GiveUp  # "no de 5mm", "que no sean negros": never apply a negated attribute
        attr_free = _blank(free, [(s, e) for s, e, _, _ in tokens])
        wanted: dict[int, dict[str, Any]] = {}
        for start, end, kind, value in tokens:
            owner = _owner(hits, start, end)
            gap = (
                attr_free[owner.end : start] if owner.end <= start else attr_free[end : owner.start]
            )
            if kind == "color" and gap.strip() not in ("", "de"):
                raise _GiveUp  # a colour not attached to the product may describe something else
            per_hit = wanted.setdefault(owner.start, {})
            if kind in per_hit:
                raise _GiveUp
            per_hit[kind] = value
        for h in hits:
            want = wanted.get(h.start, {})
            attrs = [self._catalog.items[s].attrs for s in h.skus]
            if any(not any(_MODELLED[k] in a for a in attrs) for k in want):
                raise _GiveUp  # the family has no such attribute: not ours to decide
            h.skus = [
                s
                for s, a in zip(h.skus, attrs, strict=True)
                if all(_satisfies(a, k, v) for k, v in want.items())
            ]

    @staticmethod
    def _prev_qty(t: str) -> set[int]:
        """Positions of the "no" in "sean 15, no 20" (a previous quantity, not a negation)."""
        return {t.rindex("no", 0, m.start(2)) for m in _QTY.finditer(t) if m.group(2)}

    @staticmethod
    def _bind(t: str, hits: list[_Hit], nums: dict[int, re.Match[str]]) -> list[int]:
        """Bind numbers to hits; return the starts of numbers left unbound."""
        bound: set[int] = set()

        after_hit = re.compile(r"\s+(\d+)")

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
            m = after_hit.match(t, h.end)
            if m and m.start(1) in nums:
                set_qty(h, m.start(1))
        return [p for p in nums if p not in bound]
