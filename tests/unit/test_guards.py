import pytest

from quote_engine.adapters.extractors.guards import Guard
from quote_engine.domain.catalog import Catalog
from quote_engine.domain.interpretation import Intent, ItemMention, MessageInterpretation

CATALOG = Catalog.from_json("fixtures/catalog.json")
guard = Guard(CATALOG)
FBT = "ALFBTC-013-320100"
FRONTLITS = sorted(CATALOG.with_attr("type", "frontlit"))


def interp(intent, *items, ids=()):
    return MessageInterpretation(
        intent=intent, items=list(items), explicit_quote_ids=list(ids), source="llm"
    )


def item(cands, qty=None, prev=None, mention="x"):
    return ItemMention(mention=mention, sku_candidates=cands, qty=qty, previous_qty=prev)


def test_passes_through_none_and_non_mutating():
    assert guard("cuanto sale?", None) is None
    q = interp(Intent.QUERY, item([FBT]))
    assert guard("cuanto sale la lona?", q) is q


@pytest.mark.parametrize(
    "text",
    [
        "cuanto me sale si llevo 10 lonas frontlit en vez de 20?",
        "y cuanto cuestan 5 frontlit",
        "pasame precio de 10 frontlit",
    ],
)
def test_price_question_never_mutates(text):
    got = guard(text, interp(Intent.UPDATE_QTY, item(FRONTLITS, 10, 20)))
    assert got is not None
    assert got.intent == Intent.QUERY


async def test_rules_output_is_guarded():
    from quote_engine.adapters.extractors.rules import RuleExtractor
    from quote_engine.application.ports import MessageCtx

    ctx = MessageCtx("m1", "c1", "cust", "inbound", "cotizame 5 lonas frontlit, cuanto me sale", [])
    r = await RuleExtractor(CATALOG).interpret(ctx)
    assert r is not None
    assert r.intent == Intent.QUERY


MESH = "ALMCLC-0909-320100"


@pytest.mark.parametrize(
    "text",
    ["la de ayer cambiala a 10 rollos", "lo mismo que la vez pasada porfa", "la anterior, 5 mas"],
)
def test_temporal_reference_goes_to_review(text):
    assert guard(text, interp(Intent.UPDATE_QTY, item([MESH], 10))) is None


def test_temporal_question_is_untouched():
    q = interp(Intent.QUERY)
    assert guard("hacen envios? la otra vez tardaron", q) is q


ACR_TR = "ARACTR-03-122244"


@pytest.mark.parametrize(
    "text",
    [
        "me equivoque, era el blanco no el transparente 🙈",
        "ay perdon el vinil mate era de 1.37 no de 1.52",
        "me equivoque de producto",
    ],
)
def test_variant_swap_goes_to_review(text):
    # the contract cannot say "replace line X by Y"; set_qty on the old line would be wrong
    assert guard(text, interp(Intent.UPDATE_QTY, item([ACR_TR], 4))) is None


@pytest.mark.parametrize("text", ["perdon, eran 15 no 12", "no eran 3 eran 5 los acrilicos negros"])
def test_quantity_correction_passes(text):
    i = interp(Intent.UPDATE_QTY, item([ACR_TR], 5))
    assert guard(text, i) is i


MAG = "ATEMGN-1L-001000"


@pytest.mark.parametrize(
    "text",
    [
        "mandame 2 galones de tinta magenta",
        "cotizame 20 metros de lona frontlit",
        "2 cajas de tinta magenta",
        "5 kg de tinta",
    ],
)
def test_unsupported_unit_goes_to_review(text):
    assert guard(text, interp(Intent.CREATE_QUOTE, item([MAG], 2))) is None


@pytest.mark.parametrize(
    "text",
    [
        "tinta magenta 4 litros porfa",  # the SKU is 1L: 4 litros = 4 units
        "cotizame 20 rollos de lona 3.20 x 100 metros",
        "cotizame 2 lonas 3.20x100m",
        "nesesito 4 planchas de trovicel de 5mm",
    ],
)
def test_supported_units_pass(text):
    i = interp(Intent.CREATE_QUOTE, item([MAG], 2))
    assert guard(text, i) is i


ACR = "ARACBL-03-122244"


def test_mixed_add_and_set_goes_to_review():
    # one intent per message: "add 2 X and set Y to 10" cannot be expressed safely
    i = interp(Intent.ADD_ITEMS, item([ACR], 2), item(FRONTLITS, 10))
    assert guard("agrega 2 acrilicos blancos de 3mm y que las lonas frontlit sean 10", i) is None


@pytest.mark.parametrize(
    "text",
    ["sumale 2 rollos mas de microperforado y agrega 3 tintas negras", "agregale 2 frontlit"],
)
def test_plain_add_passes(text):
    i = interp(Intent.ADD_ITEMS, item([ACR], 2))
    assert guard(text, i) is i


MICS_152 = "AVMICS-1A-152050"
MATE_152 = "AVBLMT-1A-152050"


def test_candidates_outside_the_named_alias_go_to_review():
    # "one way" is only ever microperforado: a vinil mate pick is a wrong SKU
    i = interp(Intent.CREATE_QUOTE, item([MATE_152], 2, mention="one way 1.52"))
    assert guard("one way 1.52, 2 rollos", i) is None


@pytest.mark.parametrize(
    ("mention", "cands"),
    [
        ("one way 1.52", [MICS_152]),
        ("vinil one way", [MICS_152]),
        ("lonsa frontlit", [FBT]),  # typo: no alias to check against
        ("esas", [MAG]),
    ],
)
def test_candidates_within_the_named_alias_pass(mention, cands):
    i = interp(Intent.CREATE_QUOTE, item(cands, 2, mention=mention))
    assert guard("x", i) is i


CYAN = "ATECYN-1L-001000"


@pytest.mark.parametrize(
    "intent", [Intent.REMOVE_ITEM, Intent.UPDATE_QTY, Intent.ADD_ITEMS, Intent.CANCEL]
)
def test_decrease_becomes_relative_update(intent):
    got = guard("quitale 2 a las frontlit", interp(intent, item(FRONTLITS, 2)))
    assert got is not None
    assert got.intent == Intent.UPDATE_QTY
    [it] = got.items
    assert (it.qty, it.previous_qty, it.qty_delta) == (None, None, -2)
    assert it.sku_candidates == FRONTLITS


@pytest.mark.parametrize("intent", [Intent.UPDATE_QTY, Intent.CREATE_QUOTE])
def test_increase_becomes_add(intent):
    # "ponle 2 mas de esas": +2 on the existing line, never set it to 2
    got = guard("si, ponle 2 mas de esas", interp(intent, item([CYAN], 2, 10, mention="esas")))
    assert got is not None
    assert got.intent == Intent.ADD_ITEMS
    [it] = got.items
    assert (it.qty, it.previous_qty) == (2, None)


@pytest.mark.parametrize(
    "text", ["quitale 2 a las frontlit y al mesh", "ponle 2 mas de esas y de las otras"]
)
def test_relative_change_on_several_items_goes_to_review(text):
    i = interp(Intent.UPDATE_QTY, item(FRONTLITS, 2), item([MESH], 2))
    assert guard(text, i) is None


def test_relative_increase_on_plain_add_passes():
    i = interp(Intent.ADD_ITEMS, item([CYAN], 2), item([MAG], 3))
    assert guard("sumale 2 rollos mas de cyan y agrega 3 magenta", i) is i
