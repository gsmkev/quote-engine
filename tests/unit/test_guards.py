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
