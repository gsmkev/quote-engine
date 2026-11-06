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
        "no quiero 2 lonas frontlit",
        "cotizame 3 lonas no 5 vinil",
        "mejor que sean 12 lonas no 2 acrilicos",
        "cuanto cuestan 3 lonas",
        "no cancelen la cotizacion",
        "no cancela la cotizacion de las lonas",
        "cancela lo del papel fotografico",  # cancel + unrecognised content is not a bare cancel
        "cancela las playeras porfa",
        # an add and a set-quantity in one message: the contract has one intent per message
        "agrega 2 acrilicos blancos de 3mm y que las lonas frontlit sean 10",
    ],
)
async def test_gives_up(text):
    assert await extractor.interpret(ctx(text)) is None


@pytest.mark.parametrize(
    "text", ["mejor cancelalo", "cancela todo porfa", "cancela Q-002 por favor", "cancela todo"]
)
async def test_bare_cancel(text):
    r = await extractor.interpret(ctx(text))
    assert r is not None
    assert (r.intent, r.items) == (Intent.CANCEL, [])


@pytest.mark.parametrize(
    ("text", "qty"), [("las sintras q sean 12 plis", 12), ("que sean 15 las frontlit", 15)]
)
async def test_que_sean_is_update(text, qty):
    r, item = await item_of(text)
    assert r.intent == Intent.UPDATE_QTY
    assert item.qty == qty


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


FRONTLITS = CATALOG.with_attr("type", "frontlit")
PVC = CATALOG.with_attr("family", "pvc")
TINTAS = CATALOG.with_attr("family", "tinta")
PVC_5 = "APPVEB-05-122244"
ACR_NEGRO_3 = "ARACNG-03-122244"
TINTA_CYAN = "ATECYN-1L-001000"


async def item_of(text: str):
    r = await extractor.interpret(ctx(text))
    assert r is not None
    assert len(r.items) == 1
    return r, r.items[0]


@pytest.mark.parametrize(
    "text",
    [
        "cotizame 3 lonas de 5x100",
        "cotizame 2 sintra 20mm",
        "cotizame 2 acrilicos rojos 3mm",
        "cotizame 2 viniles de 11.37",
        "cotizame 2 vinil negro",
        "cotizame 1 tinta roja",
        "cotizame 2 acrilicos 3 milimetros verdes",
    ],
)
async def test_explicit_attribute_without_match_is_not_in_catalog(text):
    r, item = await item_of(text)
    assert r.intent == Intent.ADD_ITEMS
    assert item.in_catalog is False
    assert item.sku_candidates == []
    assert item.qty is not None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("cotizame 2 sintra 5mm", {PVC_5}),
        ("cotizame 2 sintra 5 mm", {PVC_5}),
        ("cotizame 2 sintra 5 milimetros", {PVC_5}),
        ("cotizame 2 acrilicos negros 3mm", {ACR_NEGRO_3}),
        ("cotizame 2 acrilicos negro 3mm", {ACR_NEGRO_3}),
        ("cotizame 2 acrilicos 3mm blancos", {ACR}),
        ("cotizame 2 acrilicos de 3mm blancos", {ACR}),
        ("cotizame 1 tinta cyan", {TINTA_CYAN}),
        ("cotizame 1 tintas cian", {TINTA_CYAN}),
        ("cotizame 2 vinil de 1.37", VINILES & CATALOG.with_attr("width_m", 1.37)),
        ("cotizame 2 viniles 1,37x50", VINILES & CATALOG.with_attr("width_m", 1.37)),
        ("cotizame 2 viniles transparentes", CATALOG.with_attr("color", "transparente") & VINILES),
        ("cotizame 2 acrilicos 1.22x2.44", ACRILICOS),
    ],
)
async def test_attribute_filter_is_exact(text, expected):
    _, item = await item_of(text)
    assert item.in_catalog is True
    assert set(item.sku_candidates) == expected


@pytest.mark.parametrize("text", ["20 rollos lona 3.20 x 100", "20 rollos lona 3,20x100 m."])
async def test_width_length_filter(text):
    _, item = await item_of("cotizame " + text)
    assert FBT in item.sku_candidates
    for s in item.sku_candidates:
        attrs = CATALOG.items[s].attrs
        assert attrs["width_m"] == pytest.approx(3.2)
        assert attrs["length_m"] == pytest.approx(100)


async def test_ink_colour_is_not_a_bare_alias():
    _, item = await item_of("cotizame 2 acrilicos negros 3mm")
    assert item.mention == "acrilicos negros"
    r = await extractor.interpret(ctx("cotizame 2 negros"))
    assert r is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("cotizame 2 viniles", VINILES),
        ("cotizame 3 sintras", PVC),
        ("cotizame 2 banners", FRONTLITS),
        ("cotizame 2 banner", FRONTLITS),
        ("cotizame 2 tintas", TINTAS),
        ("cotizame 2 lonas blackout", CATALOG.with_attr("type", "blackout")),
        ("cotizame 2 lona mesh", MESHES),
        ("cotizame 2 lonas frontlit 3.20x100", {FBT}),
    ],
)
async def test_family_aliases(text, expected):
    _, item = await item_of(text)
    assert set(item.sku_candidates) == expected


@pytest.mark.parametrize(
    "text",
    [
        "cotizame 2 lonas 3mm",  # lonas have no thickness: not ours to decide
        "cotizame 2 lonas blancas",  # lonas have no colour attribute
        "cotizame 2 viniles de 1.37 y 1.52",  # two sizes for one mention
        "cotizame 2 acrilicos 3mm 5mm",
        "cotizame 2 lonas 3.20x100 cm",
        "cotizame 2 lonas, las que me mandaste la otra vez de 3.20x100",  # too far
        "cotizame 2 sintra pero no de 5mm",  # negated attributes
        "cotizame 2 sintra, no de 5mm",
        "cotizame 2 acrilicos que no sean negros",
        "cotizame 2 acrilicos 3mm que no sean negros",
        "cotizame 2 acrilicos sin negro",
        "cotizame 2 lonas 320x100",  # unitless integer width: likely cm
        "cotizame 2 viniles para la tienda roja",  # colour not attached to the product
    ],
)
async def test_attribute_gives_up(text):
    assert await extractor.interpret(ctx(text)) is None


async def test_mixed_message_decides_per_item():
    r = await extractor.interpret(ctx("cotizame 3 lonas de 3.20x100 y 2 vinil rojo"))
    assert r is not None
    lona, vinil = r.items
    assert lona.in_catalog and set(lona.sku_candidates) == LONAS_320100
    assert not vinil.in_catalog and vinil.qty == 2


async def test_typo_order_verb_and_sheet_unit():
    r, item = await item_of("nesesito 4 planchas de trovicel de 5mm xfa")
    assert r.intent == Intent.ADD_ITEMS
    assert (item.sku_candidates, item.qty) == ([PVC_5], 4)


@pytest.mark.parametrize(
    ("text", "qty"),
    [
        ("súmale 1 rollo de mesh", 1),
        ("quiero 2 rollos de laminado brillante", 2),
        ("kiero 5 vinilos transparentes de 1.06", 5),
        ("cotisame 2 rollos de malla 2.50 x100", 2),
    ],
)
async def test_add_verb_variants(text, qty):
    r, item = await item_of(text)
    assert r.intent == Intent.ADD_ITEMS
    assert item.qty == qty


async def test_negated_want_is_not_an_add():
    assert await extractor.interpret(ctx("no quiero 2 lonas")) is None
