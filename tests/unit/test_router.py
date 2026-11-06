import pytest

from quote_engine.domain.interpretation import Intent, ItemMention, MessageInterpretation
from quote_engine.domain.quote import AddLine, Cancel, LinkConversation, RemoveLine, SetQty
from quote_engine.domain.router import (
    Apply,
    NewQuote,
    NoOp,
    QuoteView,
    Review,
    route,
    route_scores,
)

FBT = "ALFBTC-013-320100"
MCL = "ALMCLC-0909-320100"
MIC = "AVMICS-1A-137050"
ACR = "ARACBL-03-122244"
BKO = "ALBKOC-013-320100"
FBT250 = "ALFBTC-013-250100"
LONAS = [FBT, MCL]
DEFAULTS = frozenset({FBT, FBT250})


def mention(cands, qty=None, prev=None):
    return ItemMention(mention="x", sku_candidates=cands, qty=qty, previous_qty=prev)


def unknown_item(qty=None):
    return ItemMention(mention="lona neon", sku_candidates=[], in_catalog=False, qty=qty)


def interp(intent, items=(), separate=False, ids=()):
    return MessageInterpretation(
        intent=intent,
        items=list(items),
        separate=separate,
        explicit_quote_ids=list(ids),
        source="rules",
    )


def qv(qid, lines=None, convs=()):
    return QuoteView(qid, lines or {}, frozenset(convs))


Q1_FULL = qv("Q-001", {FBT: 20, MCL: 5, MIC: 5}, ["411"])
U = Intent.UPDATE_QTY

CASES = [
    (
        "1-update-prev",
        interp(U, [mention(LONAS, 15, 20)]),
        "411",
        [Q1_FULL],
        Apply("Q-001", [LinkConversation("411"), SetQty(FBT, 15)]),
    ),
    (
        "2-ambiguous-line",
        interp(U, [mention(LONAS, 15)]),
        "411",
        [Q1_FULL],
        Review("ambiguous_line", ["Q-001"], None),
    ),
    (
        "3-query",
        interp(Intent.QUERY, [mention(LONAS)]),
        "662",
        [Q1_FULL],
        Apply("Q-001", [LinkConversation("662")]),
    ),
    (
        "4-separate",
        interp(Intent.ADD_ITEMS, [mention([ACR], 2)], separate=True),
        "411",
        [Q1_FULL],
        NewQuote([(ACR, 2)]),
    ),
    (
        "5-other-quote",
        interp(U, [mention([ACR], 4)]),
        "662",
        [qv("Q-001", {FBT: 1}, ["662"]), qv("Q-002", {ACR: 2})],
        Apply("Q-002", [LinkConversation("662"), SetQty(ACR, 4)]),
    ),
    (
        "6-cancel-two",
        interp(Intent.CANCEL),
        "411",
        [qv("Q-001"), qv("Q-002")],
        Review("ambiguous_quote", ["Q-001", "Q-002"], None),
    ),
    (
        "7-cancel-one",
        interp(Intent.CANCEL),
        "411",
        [qv("Q-001")],
        Apply("Q-001", [LinkConversation("411"), Cancel()]),
    ),
    (
        "8-tie",
        interp(U, [mention([FBT], 3)]),
        "411",
        [qv("Q-001", {FBT: 1}), qv("Q-002", {FBT: 1})],
        Review("ambiguous_quote", ["Q-001", "Q-002"], None),
    ),
    (
        "9-explicit-id",
        interp(U, [mention([ACR], 4)], ids=["Q-002"]),
        "411",
        [qv("Q-001", {ACR: 1}), qv("Q-002", {ACR: 1})],
        Apply("Q-002", [LinkConversation("411"), SetQty(ACR, 4)]),
    ),
    (
        "10-linked-to-both",
        interp(Intent.ADD_ITEMS, [mention([ACR], 1)]),
        "411",
        [qv("Q-001", convs=["411"]), qv("Q-002", convs=["411"])],
        Review("ambiguous_quote", ["Q-001", "Q-002"], None),
    ),
    (
        "11-none-open",
        interp(U, [mention([ACR], 4)]),
        "411",
        [],
        Review("ambiguous_quote", [], None),
    ),
    (
        "12-cancelled-not-passed",
        interp(U, [mention(LONAS, 10)]),
        "411",
        [qv("Q-002", {ACR: 2})],
        Review("ambiguous_quote", ["Q-002"], None),
    ),
    (
        "13-create-ambiguous-sku",
        interp(Intent.CREATE_QUOTE, [mention(LONAS, 2)]),
        "411",
        [],
        Review("unknown_product", [], None),
    ),
    (
        "update-no-items",
        interp(U, [], ids=["Q-001"]),
        "411",
        [Q1_FULL, qv("Q-002", {ACR: 2})],
        Review("unknown_product", ["Q-001"], None),
    ),
    (
        "remove-no-items",
        interp(Intent.REMOVE_ITEM, []),
        "411",
        [Q1_FULL],
        Review("unknown_product", ["Q-001"], None),
    ),
    (
        "update-item-without-qty",
        interp(U, [mention([ACR])], ids=["Q-002"]),
        "411",
        [Q1_FULL, qv("Q-002", {ACR: 2})],
        Review("unknown_product", ["Q-002"], None),
    ),
    (
        "14-add-existing-sku",
        interp(Intent.ADD_ITEMS, [mention([ACR], 2)]),
        "411",
        [qv("Q-001", {ACR: 3}, ["411"])],
        Apply("Q-001", [LinkConversation("411"), SetQty(ACR, 5)]),
    ),
    (
        "15-add-new-sku",
        interp(Intent.ADD_ITEMS, [mention([MIC], 2)]),
        "411",
        [qv("Q-001", {ACR: 3}, ["411"])],
        Apply("Q-001", [LinkConversation("411"), AddLine(MIC, 2)]),
    ),
    (
        "16-add-no-open",
        interp(Intent.ADD_ITEMS, [mention([ACR], 2)]),
        "411",
        [],
        NewQuote([(ACR, 2)]),
    ),
    (
        "17-remove",
        interp(Intent.REMOVE_ITEM, [mention([MIC])]),
        "411",
        [Q1_FULL],
        Apply("Q-001", [LinkConversation("411"), RemoveLine(MIC)]),
    ),
    ("18-none", interp(Intent.NONE), "411", [Q1_FULL], NoOp()),
    (
        "19-new-missing-qty",
        interp(Intent.CREATE_QUOTE, [mention([ACR])]),
        "411",
        [],
        Review("unknown_product", [], None),
    ),
    (
        "20-create-duplicate-sku-merged",
        interp(Intent.CREATE_QUOTE, [mention([ACR], 2), mention([MIC], 1), mention([ACR], 3)]),
        "411",
        [],
        NewQuote([(ACR, 5), (MIC, 1)]),
    ),
    (
        "21-add-duplicate-existing-sku-merged",
        interp(Intent.ADD_ITEMS, [mention([ACR], 2), mention([ACR], 1)]),
        "411",
        [qv("Q-001", {ACR: 3}, ["411"])],
        Apply("Q-001", [LinkConversation("411"), SetQty(ACR, 6)]),
    ),
    (
        "22-add-duplicate-new-sku-merged",
        interp(Intent.ADD_ITEMS, [mention([MIC], 2), mention([MIC], 2)]),
        "411",
        [qv("Q-001", {ACR: 3}, ["411"])],
        Apply("Q-001", [LinkConversation("411"), AddLine(MIC, 4)]),
    ),
    (
        "23-update-conflicting-duplicates",
        interp(U, [mention([ACR], 4), mention([ACR], 6)]),
        "411",
        [qv("Q-001", {ACR: 2})],
        Review("ambiguous_line", ["Q-001"], None),
    ),
    (
        "24-update-same-duplicates",
        interp(U, [mention([ACR], 4), mention([ACR], 4)]),
        "411",
        [qv("Q-001", {ACR: 2})],
        Apply("Q-001", [LinkConversation("411"), SetQty(ACR, 4)]),
    ),
    (
        "25-remove-duplicates",
        interp(Intent.REMOVE_ITEM, [mention([MIC]), mention([MIC])]),
        "411",
        [Q1_FULL],
        Apply("Q-001", [LinkConversation("411"), RemoveLine(MIC)]),
    ),
    (
        "26-remove-duplicates-with-qty",
        interp(Intent.REMOVE_ITEM, [mention([MIC], 5), mention([MIC], 2)]),
        "411",
        [Q1_FULL],
        Apply("Q-001", [LinkConversation("411"), RemoveLine(MIC)]),
    ),
]


@pytest.mark.parametrize(
    ("i", "conv", "quotes", "expected"), [c[1:] for c in CASES], ids=[c[0] for c in CASES]
)
def test_route(i, conv, quotes, expected):
    assert route(i, conv, quotes) == expected


def test_route_scores():
    i = interp(U, [mention(LONAS, 15, 20)], ids=["Q-002"])
    assert route_scores(i, [Q1_FULL, qv("Q-002")]) == {"Q-001": 5, "Q-002": 10}


DEFAULT_CASES = [
    (
        "new-quote-picks-default",
        interp(Intent.CREATE_QUOTE, [mention([FBT, BKO], 2)]),
        "411",
        [],
        NewQuote([(FBT, 2)]),
    ),
    (
        "new-quote-two-defaults",
        interp(Intent.CREATE_QUOTE, [mention([FBT, FBT250], 2)]),
        "411",
        [],
        Review("unknown_product", [], None),
    ),
    (
        "add-new-line-picks-default",
        interp(Intent.ADD_ITEMS, [mention([FBT, BKO], 2)]),
        "411",
        [qv("Q-001", {ACR: 3}, ["411"])],
        Apply("Q-001", [LinkConversation("411"), AddLine(FBT, 2)]),
    ),
    (
        "add-intersects-one-line",
        interp(Intent.ADD_ITEMS, [mention(LONAS, 5)]),
        "411",
        [qv("Q-001", {FBT: 20}, ["411"])],
        Apply("Q-001", [LinkConversation("411"), SetQty(FBT, 25)]),
    ),
    (
        "add-intersect-ignores-default",
        interp(Intent.ADD_ITEMS, [mention([FBT, BKO], 5)]),
        "411",
        [qv("Q-001", {BKO: 1}, ["411"])],
        Apply("Q-001", [LinkConversation("411"), SetQty(BKO, 6)]),
    ),
    (
        "add-intersects-two-lines",
        interp(Intent.ADD_ITEMS, [mention(LONAS, 5)]),
        "411",
        [qv("Q-001", {FBT: 20, MCL: 5}, ["411"])],
        Review("ambiguous_line", ["Q-001"], None),
    ),
    (
        "update-without-prev-ignores-default",
        interp(U, [mention([FBT, BKO, MCL], 15)]),
        "411",
        [Q1_FULL],
        Review("ambiguous_line", ["Q-001"], None),
    ),
    (
        "event1-without-prev-still-review",
        interp(U, [mention(LONAS, 15)]),
        "411",
        [Q1_FULL],
        Review("ambiguous_line", ["Q-001"], None),
    ),
    (
        "create-unknown",
        interp(Intent.CREATE_QUOTE, [unknown_item(2)]),
        "411",
        [],
        Review("unknown_product", [], None),
    ),
    (
        "add-mixed-unknown",
        interp(Intent.ADD_ITEMS, [mention([ACR], 2), unknown_item(3)]),
        "411",
        [Q1_FULL, qv("Q-002", {ACR: 3}, ["411"])],
        Review("unknown_product", ["Q-001", "Q-002"], None),
    ),
    (
        "add-mixed-unknown-linked",
        interp(Intent.ADD_ITEMS, [mention([ACR], 2), unknown_item(3)]),
        "411",
        [Q1_FULL, qv("Q-002", {ACR: 3}, ["662"])],
        Review("unknown_product", ["Q-001"], None),
    ),
    (
        "update-unknown",
        interp(U, [unknown_item(4)]),
        "411",
        [Q1_FULL, qv("Q-002", {ACR: 2})],
        Review("unknown_product", ["Q-001", "Q-002"], None),
    ),
    (
        "update-mixed-unknown-targeted",
        interp(U, [mention([ACR], 4), unknown_item(4)]),
        "411",
        [Q1_FULL, qv("Q-002", {ACR: 2})],
        Review("unknown_product", ["Q-002"], None),
    ),
    (
        "remove-unknown",
        interp(Intent.REMOVE_ITEM, [unknown_item()]),
        "411",
        [Q1_FULL],
        Review("unknown_product", ["Q-001"], None),
    ),
    (
        "query-mixed-unknown-links",
        interp(Intent.QUERY, [mention(LONAS), unknown_item()]),
        "662",
        [Q1_FULL],
        Apply("Q-001", [LinkConversation("662")]),
    ),
    (
        "query-only-unknown-noop",
        interp(Intent.QUERY, [unknown_item()]),
        "662",
        [Q1_FULL],
        NoOp(),
    ),
    (
        "query-only-unknown-explicit-id",
        interp(Intent.QUERY, [unknown_item()], ids=["Q-001"]),
        "662",
        [Q1_FULL],
        Apply("Q-001", [LinkConversation("662")]),
    ),
    ("none-unknown", interp(Intent.NONE, [unknown_item()]), "411", [Q1_FULL], NoOp()),
    (
        "cancel-explicit-id-unknown",
        interp(Intent.CANCEL, [unknown_item()], ids=["Q-001"]),
        "411",
        [Q1_FULL, qv("Q-002", {ACR: 2})],
        Review("unknown_product", ["Q-001"], None),
    ),
    (
        "cancel-mixed-unknown",
        interp(Intent.CANCEL, [mention([ACR]), unknown_item()]),
        "411",
        [Q1_FULL, qv("Q-002", {ACR: 2})],
        Review("unknown_product", ["Q-002"], None),
    ),
    (
        "cancel-known-unchanged",
        interp(Intent.CANCEL, [mention([ACR])]),
        "411",
        [Q1_FULL, qv("Q-002", {ACR: 2})],
        Apply("Q-002", [LinkConversation("411"), Cancel()]),
    ),
    (
        # "cancela el microperforado nomas": naming one line of several is not a whole cancel
        "cancel-names-part-of-quote",
        interp(Intent.CANCEL, [mention([MIC])]),
        "411",
        [Q1_FULL],
        Review("ambiguous_line", ["Q-001"], None),
    ),
]


@pytest.mark.parametrize(
    ("i", "conv", "quotes", "expected"),
    [c[1:] for c in DEFAULT_CASES],
    ids=[c[0] for c in DEFAULT_CASES],
)
def test_route_with_defaults(i, conv, quotes, expected):
    assert route(i, conv, quotes, defaults=DEFAULTS) == expected
