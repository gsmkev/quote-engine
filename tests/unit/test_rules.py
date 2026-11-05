import pytest

from quote_engine.adapters.extractors.rules import RuleExtractor
from quote_engine.application.ports import MessageCtx
from quote_engine.domain.catalog import Catalog
from quote_engine.domain.interpretation import Intent

FBT = "ALFBTC-013-320100"
MCL = "ALMCLC-0909-320100"
MIC = "AVMICS-1A-137050"
ACR = "ARACBL-03-122244"

CATALOG = Catalog.from_json("fixtures/catalog.json")
extractor = RuleExtractor(CATALOG)
LONAS = CATALOG.with_attr("family", "lona")
ACRILICOS = CATALOG.with_attr("family", "acrilico")
VINILES = CATALOG.with_attr("family", "vinil")
LONAS_320100 = CATALOG.with_attr("width_m", 3.2) & CATALOG.with_attr("length_m", 100.0) & LONAS
MESHES = CATALOG.with_attr("type", "mesh")


def ctx(text: str) -> MessageCtx:
    return MessageCtx("m1", "c1", "cust", "inbound", text, [])


CASES = [
    (
        "Oye de las lonas mejor que sean 15, no 20",
        Intent.UPDATE_QTY,
        False,
        [("lonas", LONAS, 15, 20)],
        [],
    ),
    (
        "Buen dia, soy Mario de compras de ACME. Alice me pasó con ustedes, "
        "me confirmas qué lleva la cotización de las lonas?",
        Intent.QUERY,
        False,
        [("lonas", LONAS, None, None)],
        [],
    ),
    (
        "y aparte cotizame 2 acrilicos blancos de 3mm porfa",
        Intent.ADD_ITEMS,
        True,
        [("acrilicos blancos", {ACR}, 2, None)],
        [],
    ),
    (
        "perfecto. y de los acrilicos que cotizó Alice, mejor que sean 4",
        Intent.UPDATE_QTY,
        False,
        [("acrilicos", ACRILICOS, 4, None)],
        [],
    ),
    ("mejor cancelalo", Intent.CANCEL, False, [], []),
    (
        "cambia el Q-002, acrilicos 6",
        Intent.UPDATE_QTY,
        False,
        [("acrilicos", ACRILICOS, 6, None)],
        ["Q-002"],
    ),
    (
        "cotizame 3 lonas de 3.20x100 y 2 vinil",
        Intent.ADD_ITEMS,
        False,
        [("lonas", LONAS_320100, 3, None), ("vinil", VINILES, 2, None)],
        [],
    ),
]


@pytest.mark.parametrize(("text", "intent", "separate", "items", "ids"), CASES)
async def test_extracts(text, intent, separate, items, ids):
    r = await extractor.interpret(ctx(text))
    assert r is not None
    assert r.source == "rules"
    assert r.intent == intent
    assert r.separate is separate
    assert r.explicit_quote_ids == ids
    got = [(i.mention, set(i.sku_candidates), i.qty, i.previous_qty) for i in r.items]
    assert got == items


@pytest.mark.parametrize(
    "text",
    [
        "mejor que sean quince",
        "hola que tal",
        "de las lonas mejor",
        "dame 3 de eso",
        "cotizame 2 lonas y 5",
        "cancela las lonas",
        "cotizame 2 lonas y 3 acrilicos 4",
        "cotizame 3 lonas no 5 vinil",
        "mejor que sean 12 lonas no 2 acrilicos",
        "cuanto cuestan 3 lonas",
        "no cancelen la cotizacion",
        "no cancela la cotizacion de las lonas",
    ],
)
async def test_gives_up(text):
    assert await extractor.interpret(ctx(text)) is None


async def test_cotizacion_is_not_add():
    r = await extractor.interpret(ctx("la cotizacion de las lonas, cuanto"))
    assert r is not None
    assert r.intent == Intent.QUERY


async def test_dim_filter_narrows_candidates():
    r = await extractor.interpret(ctx("cotizame 2 lonas 9x9"))
    assert r is not None
    assert {s for i in r.items for s in i.sku_candidates} == MESHES


async def test_extract_conversation_is_none():
    from quote_engine.application.ports import ConversationCtx

    assert await extractor.extract_conversation(ConversationCtx("c1", "cust", [])) is None


async def test_cotizas_question_is_add():
    r = await extractor.interpret(ctx("me cotizas 3 lonas?"))
    assert r is not None
    assert r.intent == Intent.ADD_ITEMS
    assert r.items[0].qty == 3
