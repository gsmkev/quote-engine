from dataclasses import dataclass
from typing import Literal

from quote_engine.domain.interpretation import Intent, ItemMention, MessageInterpretation
from quote_engine.domain.quote import AddLine, Cancel, LinkConversation, RemoveLine, SetQty

type Op = Cancel | SetQty | AddLine | RemoveLine | LinkConversation


@dataclass(frozen=True)
class QuoteView:
    id: str
    lines: dict[str, int]
    conversations: frozenset[str]


@dataclass(frozen=True)
class Apply:
    quote_id: str
    ops: list[Op]


@dataclass(frozen=True)
class NewQuote:
    lines: list[tuple[str, int]]


@dataclass(frozen=True)
class Review:
    reason: Literal["ambiguous_quote", "ambiguous_line", "unknown_product", "extraction_failed"]
    candidates: list[str]
    proposed: Apply | None


@dataclass(frozen=True)
class NoOp:
    pass


Decision = Apply | NewQuote | Review | NoOp


def score(interp: MessageInterpretation, q: QuoteView) -> int:
    s = 10 if q.id in interp.explicit_quote_ids else 0
    for it in interp.items:
        hit = set(it.sku_candidates) & q.lines.keys()
        if hit:
            s += 3
            if it.previous_qty and any(q.lines[k] == it.previous_qty for k in hit):
                s += 2
    return s


def route_scores(interp: MessageInterpretation, open_quotes: list[QuoteView]) -> dict[str, int]:
    return {q.id: score(interp, q) for q in open_quotes}


def _resolve_line(it: ItemMention, q: QuoteView) -> str | None:
    hit = [k for k in it.sku_candidates if k in q.lines]
    if it.previous_qty:
        hit = [k for k in hit if q.lines[k] == it.previous_qty] or hit
    return hit[0] if len(hit) == 1 else None


def _pick(interp: MessageInterpretation, open_quotes: list[QuoteView]) -> QuoteView | None:
    scored = sorted(((score(interp, q), q) for q in open_quotes), key=lambda t: -t[0])
    if not scored or scored[0][0] == 0:
        return None
    if len(scored) > 1 and scored[1][0] == scored[0][0]:
        return None
    return scored[0][1]


def _new_lines(items: list[ItemMention]) -> list[tuple[str, int]] | None:
    if not items or any(len(it.sku_candidates) != 1 or it.qty is None for it in items):
        return None
    return [(it.sku_candidates[0], it.qty) for it in items if it.qty is not None]


def route(
    interp: MessageInterpretation, conversation_id: str, open_quotes: list[QuoteView]
) -> Decision:
    link = LinkConversation(conversation_id)
    ids = [q.id for q in open_quotes]
    ambiguous_quote = Review("ambiguous_quote", ids, None)
    unknown = Review("unknown_product", [], None)
    intent = interp.intent

    if intent is Intent.NONE:
        return NoOp()

    if intent is Intent.CREATE_QUOTE or (
        intent is Intent.ADD_ITEMS and (interp.separate or not open_quotes)
    ):
        lines = _new_lines(interp.items)
        return NewQuote(lines) if lines else unknown

    if intent is Intent.ADD_ITEMS:
        linked = [q for q in open_quotes if conversation_id in q.conversations]
        if len(linked) != 1:
            return ambiguous_quote
        lines = _new_lines(interp.items)
        if lines is None:
            return unknown
        q = linked[0]
        ops: list[Op] = [link]
        for sku, qty in lines:
            ops.append(SetQty(sku, q.lines[sku] + qty) if sku in q.lines else AddLine(sku, qty))
        return Apply(q.id, ops)

    if intent is Intent.CANCEL and not interp.items and not interp.explicit_quote_ids:
        if len(open_quotes) == 1:
            return Apply(open_quotes[0].id, [link, Cancel()])
        return ambiguous_quote

    q = _pick(interp, open_quotes)
    if q is None:
        return ambiguous_quote
    ops = [link]
    if intent in (Intent.UPDATE_QTY, Intent.REMOVE_ITEM):
        for it in interp.items:
            sku = _resolve_line(it, q)
            if sku is None:
                return Review("ambiguous_line", [q.id], None)
            if intent is Intent.UPDATE_QTY:
                if it.qty is None:
                    return unknown
                ops.append(SetQty(sku, it.qty))
            else:
                ops.append(RemoveLine(sku))
    if intent is Intent.CANCEL:
        ops.append(Cancel())
    return Apply(q.id, ops)
