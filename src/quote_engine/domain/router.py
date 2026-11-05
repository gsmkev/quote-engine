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
    reason: Literal[
        "ambiguous_quote", "ambiguous_line", "unknown_product", "extraction_failed", "invalid_ops"
    ]
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


def merge_lines(lines: list[tuple[str, int]]) -> list[tuple[str, int]]:
    """Sum quantities of repeated SKUs, keeping first-mention order."""
    merged: dict[str, int] = {}
    for sku, qty in lines:
        merged[sku] = merged.get(sku, 0) + qty
    return list(merged.items())


def _new_sku(it: ItemMention, defaults: frozenset[str]) -> str | None:
    """SKU for a brand-new line: the only candidate, else the only family default among many."""
    cands = it.sku_candidates
    if len(cands) == 1:
        return cands[0]
    picks = [k for k in cands if k in defaults]
    return picks[0] if len(cands) > 1 and len(picks) == 1 else None


def _new_lines(items: list[ItemMention], defaults: frozenset[str]) -> list[tuple[str, int]] | None:
    lines: list[tuple[str, int]] = []
    for it in items:
        sku = _new_sku(it, defaults)
        if sku is None or it.qty is None:
            return None
        lines.append((sku, it.qty))
    return merge_lines(lines) or None


def route(
    interp: MessageInterpretation,
    conversation_id: str,
    open_quotes: list[QuoteView],
    defaults: frozenset[str] = frozenset(),
) -> Decision:
    link = LinkConversation(conversation_id)
    ids = [q.id for q in open_quotes]
    ambiguous_quote = Review("ambiguous_quote", ids, None)
    unknown = Review("unknown_product", [], None)
    intent = interp.intent

    if intent is Intent.NONE:
        return NoOp()

    if any(not it.in_catalog for it in interp.items):
        if intent is Intent.QUERY:
            # Questions about products we don't carry: drop them, never review.
            known = [it for it in interp.items if it.in_catalog]
            interp = interp.model_copy(update={"items": known})
            if not known and _pick(interp, open_quotes) is None:
                return NoOp()
        elif intent is not Intent.CANCEL:
            q = _pick(interp, open_quotes)
            if intent is Intent.ADD_ITEMS and not interp.separate:
                linked = [v for v in open_quotes if conversation_id in v.conversations]
                q = linked[0] if len(linked) == 1 else None
            return Review("unknown_product", [q.id] if q else ids, None)

    if intent is Intent.CREATE_QUOTE or (
        intent is Intent.ADD_ITEMS and (interp.separate or not open_quotes)
    ):
        lines = _new_lines(interp.items, defaults)
        return NewQuote(lines) if lines else unknown

    if intent is Intent.ADD_ITEMS:
        linked = [q for q in open_quotes if conversation_id in q.conversations]
        if len(linked) != 1:
            return ambiguous_quote
        q = linked[0]
        added: list[tuple[str, int]] = []
        for it in interp.items:
            hit = [k for k in it.sku_candidates if k in q.lines]
            if len(hit) > 1:
                return Review("ambiguous_line", [q.id], None)
            sku = hit[0] if hit else _new_sku(it, defaults)
            if sku is None or it.qty is None:
                return unknown
            added.append((sku, it.qty))
        if not added:
            return unknown
        ops: list[Op] = [link]
        for sku, qty in merge_lines(added):
            ops.append(SetQty(sku, q.lines[sku] + qty) if sku in q.lines else AddLine(sku, qty))
        return Apply(q.id, ops)

    if intent is Intent.CANCEL and not interp.items and not interp.explicit_quote_ids:
        if len(open_quotes) == 1:
            return Apply(open_quotes[0].id, [link, Cancel()])
        return ambiguous_quote

    q = _pick(interp, open_quotes)
    if intent in (Intent.UPDATE_QTY, Intent.REMOVE_ITEM) and not interp.items:
        return Review("unknown_product", [q.id] if q else ids, None)
    if q is None:
        return ambiguous_quote
    ops = [link]
    if intent in (Intent.UPDATE_QTY, Intent.REMOVE_ITEM):
        targets: dict[str, int | None] = {}
        for it in interp.items:
            sku = _resolve_line(it, q)
            if sku is None:
                return Review("ambiguous_line", [q.id], None)
            qty = it.qty if intent is Intent.UPDATE_QTY else None
            if intent is Intent.UPDATE_QTY and qty is None:
                return Review("unknown_product", [q.id], None)
            if sku in targets and targets[sku] != qty:
                # The same line was given two different quantities: no safe pick.
                return Review("ambiguous_line", [q.id], None)
            targets[sku] = qty
        for sku, qty in targets.items():
            ops.append(RemoveLine(sku) if qty is None else SetQty(sku, qty))
    if intent is Intent.CANCEL:
        ops.append(Cancel())
    return Apply(q.id, ops)
