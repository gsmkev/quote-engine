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
        "y acrilico dorado manejan? para ver si lo sumo a la Q-001",
        "tienen lona de 5 metros de ancho?",
    ],
)
def test_questions_never_mutate(text):
    got = guard(text, interp(Intent.UPDATE_QTY, item(FRONTLITS, 10, 20)))
    assert got is None or got.intent == Intent.QUERY  # review when an order verb is present


async def test_rules_output_is_guarded():
    from quote_engine.adapters.extractors.rules import RuleExtractor
    from quote_engine.application.ports import MessageCtx

    text = "cotizame 5 lonas frontlit como la vez pasada"
    ctx = MessageCtx("m1", "c1", "cust", "inbound", text, [])
    assert await RuleExtractor(CATALOG).interpret(ctx) is None


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


def test_increase_on_update_becomes_relative_update():
    # "ponle 2 mas de esas": +2 on the existing line, never set it to 2, never a new line
    i = interp(Intent.UPDATE_QTY, item([CYAN], 2, 10, mention="esas"))
    got = guard("si, ponle 2 mas de esas", i)
    assert got is not None
    assert got.intent == Intent.UPDATE_QTY
    [it] = got.items
    assert (it.qty, it.previous_qty, it.qty_delta) == (None, None, 2)


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("ya no quiero 2 rollos mas de frontlit", Intent.REMOVE_ITEM),
        ("ya no quiero 2 rollos mas de frontlit", Intent.ADD_ITEMS),
        ("no necesito 2 rollos mas de frontlit, quitalos", Intent.UPDATE_QTY),
        ("si, ponle 2 mas de esas", Intent.CREATE_QUOTE),  # no line to add on top of
        ("si, ponle 2 mas de esas", Intent.CANCEL),
        ("no le quites 2 a las frontlit", Intent.UPDATE_QTY),
    ],
)
def test_negated_or_mismatched_relative_change_goes_to_review(text, intent):
    assert guard(text, interp(intent, item(FRONTLITS, 2, 18))) is None


def test_relative_increase_never_reaches_a_new_line():
    from quote_engine.domain.router import Review, route

    got = guard("si, ponle 2 mas de esas", interp(Intent.UPDATE_QTY, item([CYAN], 2)))
    assert got is not None
    assert isinstance(route(got, "c1", []), Review)


def test_extractor_supplied_qty_delta_is_dropped():
    leaked = ItemMention(mention="x", sku_candidates=[FBT], qty=5, qty_delta=-3)
    got = guard("mejor que sean 5 las frontlit", interp(Intent.UPDATE_QTY, leaked))
    assert got is not None
    assert got.items[0].qty_delta is None
    q = guard("hola", interp(Intent.QUERY, leaked.model_copy(update={"qty": None})))
    assert q is not None
    assert q.items[0].qty_delta is None


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("cotizame 10 rollos de lona frontlit 3.20x100 con precio", Intent.CREATE_QUOTE),
        ("necesito 5 rollos de mesh 3.20x100, me das precio", Intent.ADD_ITEMS),
    ],
)
def test_order_asking_for_price_still_orders(text, intent):
    i = interp(intent, item([FBT], 10))
    assert guard(text, i) is i


def test_order_asking_for_price_read_as_query_goes_to_review():
    assert guard("cotizame 10 rollos de lona frontlit con precio", interp(Intent.QUERY)) is None


@pytest.mark.parametrize(
    "text", ["quitale 2 a las frontlit y al mesh", "ponle 2 mas de esas y de las otras"]
)
def test_relative_change_on_several_items_goes_to_review(text):
    i = interp(Intent.UPDATE_QTY, item(FRONTLITS, 2), item([MESH], 2))
    assert guard(text, i) is None


def test_relative_increase_on_plain_add_passes():
    i = interp(Intent.ADD_ITEMS, item([CYAN], 2), item([MAG], 3))
    assert guard("sumale 2 rollos mas de cyan y agrega 3 magenta", i) is i


@pytest.mark.parametrize(
    "text",
    [
        "nesesito 4 planchas de trovicel de 5mm xfa",
        "cotizame 100 hojas de papel fotografico",
        "las sintras q sean 12 plis",
    ],
)
@pytest.mark.parametrize("intent", [Intent.NONE, Intent.QUERY])
def test_order_read_as_no_action_goes_to_review(text, intent):
    # a clear order with a quantity must never end as a silent noop
    assert guard(text, interp(intent)) is None


@pytest.mark.parametrize(
    "text",
    ["gracias!", "cuanto sale cotizar 3 lonas", "tienen sintra de 10mm?"],
)
def test_questions_and_chatter_stay_non_actions(text):
    i = interp(Intent.QUERY)
    assert guard(text, i) is i


@pytest.mark.parametrize(
    "text", ["cancela lo del papel fotografico", "cancela el microperforado nomas, lo demas sigue"]
)
def test_itemless_cancel_naming_something_goes_to_review(text):
    # the extractor dropped what was named: a whole-quote cancel would be a guess
    assert guard(text, interp(Intent.CANCEL)) is None


@pytest.mark.parametrize(
    "text",
    [
        "mejor cancelalo",
        "cancela Q-002 por favor",
        "cancela todo porfa",
        "mira al final el cliente se echo para atras asi que cancela todo lo que teniamos "
        "cotizado perdon por las molestias eh",
    ],
)
def test_bare_or_whole_cancel_passes(text):
    i = interp(Intent.CANCEL)
    assert guard(text, i) is i


def test_cancel_all_of_something_goes_to_review():
    assert guard("cancela todo lo del papel fotografico", interp(Intent.CANCEL)) is None


@pytest.mark.parametrize(
    ("text", "intent", "it"),
    [
        ("cuanto me sale si quiero 10 en vez de 20?", Intent.UPDATE_QTY, item([FBT], 10, 20)),
        ("cuanto me cobran si quiero 2 mas?", Intent.UPDATE_QTY, item([FBT], 2)),
        ("necesito saber cuanto cuestan 10 frontlit?", Intent.UPDATE_QTY, item([FBT], 10)),
        ("necesito saber cuanto cuestan 10 frontlit?", Intent.ADD_ITEMS, item([FBT], 10)),
        ("necesito saber cuanto cuestan 10 frontlit?", Intent.CREATE_QUOTE, item([FBT], 10)),
        ("y si tambien llevo 5 mesh, cuanto me sale?", Intent.ADD_ITEMS, item([MESH], 5)),
        ("ponle 2 mas? cuanto sale", Intent.UPDATE_QTY, item([FBT], 2)),
        ("tambien manejan acrilico dorado?", Intent.ADD_ITEMS, item([ACR], 1)),
        ("cotizame 2 frontlit, cuanto me sale", Intent.CREATE_QUOTE, item([FBT], 2)),
    ],
)
def test_price_or_availability_question_never_mutates_even_with_order_verbs(text, intent, it):
    got = guard(text, interp(intent, it))
    assert got is None or got.intent == Intent.QUERY


def test_unknown_product_question_with_order_is_not_a_silent_noop():
    i = interp(Intent.ADD_ITEMS, ItemMention(mention="tela", sku_candidates=[], in_catalog=False))
    assert guard("tienen tela canvas? necesito 5 rollos", i) is None


def test_question_shaped_request_goes_to_review():
    # ruling round 3: a "?" never mutates; with an order verb it goes to a human
    assert guard("me cotizas 3 lonas?", interp(Intent.ADD_ITEMS, item([FBT], 3))) is None


def test_relative_change_with_a_later_negator_goes_to_review():
    assert guard("ponle 2 mas, no 5", interp(Intent.UPDATE_QTY, item([FBT], 2))) is None


MUTATING_READINGS = [
    (Intent.UPDATE_QTY, item([FBT], 10, 20)),
    (Intent.ADD_ITEMS, item([MESH], 5)),
    (Intent.CREATE_QUOTE, item([FBT], 10)),
]
NON_ASSERTIVE = [
    "me cotizas 3 lonas? hay que entregarlas el lunes",
    "cuanto me saldrian 10 frontlit?",
    "cuanto costarian 10 en vez de 20?",
    "cuanto es si quiero 10 en vez de 20?",
    "y si quiero 10 en vez de 20, cuanto?",
    "cuanto quedaria si le pongo 2 mas?",
    "a como sale si quiero 10?",
    "que costo tendria si son 10?",
    "y si agrego 5 mesh, en cuanto queda?",
    "y si sumo 5 mesh?",
    "cuanto me sale si llevo 10 frontlit",
]
NEGATED = [
    "no me cambies a 10",
    "no quiero 10, deja los 20",
    "todavia no agregues los 5 mesh",
    "ni se te ocurra agregar 5 mesh",
    "aun no cotices 10 frontlit",
    "cotizame 10 frontlit sin ojillos",
]


@pytest.mark.parametrize(("intent", "it"), MUTATING_READINGS)
@pytest.mark.parametrize("text", NON_ASSERTIVE + NEGATED)
def test_questions_hypotheticals_and_negations_never_mutate(text, intent, it):
    from quote_engine.domain.router import Apply, NewQuote, QuoteView, route

    got = guard(text, interp(intent, it))
    assert got is None or got.intent in (Intent.QUERY, Intent.NONE)
    for quotes in ([], [QuoteView("Q-001", {FBT: 20, MESH: 5}, frozenset({"c1"}))]):
        if got is not None:
            d = route(got, "c1", quotes)
            assert not isinstance(d, NewQuote)
            assert not (isinstance(d, Apply) and len(d.ops) > 1)  # link-only at most


@pytest.mark.parametrize("text", NON_ASSERTIVE[1:3])
def test_question_read_as_a_mutation_goes_to_review(text):
    # a mutation reading is never silently downgraded: a human decides
    assert guard(text, interp(Intent.UPDATE_QTY, item([FBT], 10, 20))) is None


@pytest.mark.parametrize(
    "text",
    NON_ASSERTIVE[:1] + [t for t in NEGATED if "cambies" not in t],  # no verb there
)
@pytest.mark.parametrize("intent", [Intent.QUERY, Intent.NONE])
def test_order_verb_read_as_no_action_goes_to_review(text, intent):
    assert guard(text, interp(intent)) is None


@pytest.mark.parametrize(
    ("text", "intent", "it"),
    [
        ("Oye de las lonas mejor que sean 15, no 20", Intent.UPDATE_QTY, item(FRONTLITS, 15, 20)),
        ("mejor que sean quince las frontlit, no veinte", Intent.UPDATE_QTY, item([FBT], 15)),
        ("corrijo: son 8 rollos de blackout, no 6", Intent.UPDATE_QTY, item([FBT], 8, 6)),
        ("no eran 3 eran 5 los acrilicos negros", Intent.UPDATE_QTY, item([ACR], 5, 3)),
        ("ya no quiero el microperforado", Intent.REMOVE_ITEM, item([MICS_152])),
        ("ya no lo quiero", Intent.CANCEL, item([FBT])),
        (
            "y aparte cotizame 2 acrilicos blancos de 3mm porfa",
            Intent.ADD_ITEMS,
            item([ACR], 2),
        ),
        (
            "perfecto. y de los acrilicos que cotizó Alice, mejor que sean 4",
            Intent.UPDATE_QTY,
            item([ACR], 4),
        ),
        (
            "cotizame 10 rollos de lona frontlit 3.20x100 con precio",
            Intent.CREATE_QUOTE,
            item([FBT], 10),
        ),
    ],
)
def test_assertive_orders_and_corrections_still_pass(text, intent, it):
    i = interp(intent, it)
    assert guard(text, i) is i


@pytest.mark.parametrize("text", ["mejor cancelalo"])
def test_bare_cancel_still_passes(text):
    i = interp(Intent.CANCEL)
    assert guard(text, i) is i


def test_challenge_question_stays_a_query():
    text = (
        "Buen dia, soy Mario de compras de ACME. Alice me pasó con ustedes, "
        "me confirmas qué lleva la cotización de las lonas?"
    )
    i = interp(Intent.QUERY, item(FRONTLITS))
    assert guard(text, i) is i


ROUND4 = [
    # negated instructions that look like removals/cancels
    "ya no quiero cancelar",
    "ya no quiero cancelar la Q-001",
    "no quiero cancelar",
    "no quiero quitar el mesh",
    "ya no quiero quitar el mesh",
    "no lo quiero cancelar todavia",
    "no necesito quitar nada",
    "ya no quiero cambiar nada",
    "ya no quiero que la canceles",
    "no quiero 10, deja los 20",
    "no quiero 10 mesh, deja los 5",
    # opening "¿" without closing "?", conditional "si"
    "¿me agregas 5 mesh",
    "¿me cambias a 10 las frontlit",
    "que tal si agregamos 5 mesh",
    "si agregamos 5 mesh me hacen descuento",
    "despues te confirmo si agregamos 5 mesh",
    "quiero saber si me agregas 5 mesh",
    "si compro 10 frontlit me hacen descuento",
    "si pido 10 frontlit me hacen descuento",
    # hedges and deferrals
    "quizas agrega 5 mesh",
    "quiza 10 frontlit",
    "tal vez agrega 5 mesh",
    "a lo mejor agrega 5 mesh",
    "igual y agrega 5 mesh",
    "puede que agregue 5 mesh",
    "estoy pensando agregar 5 mesh",
    "seria bueno agregar 5 mesh",
    "agrega 5 mesh, luego te confirmo",
    "agrega 5 mesh cuando te confirme",
    "espera, agrega 5 mesh",
    "cuantos mesh me agregas, 5",
    # lexical negation
    "tampoco agregues 5 mesh",
    "nunca agregues 5 mesh",
    "jamas agregues 5 mesh",
    "olvida lo de agregar 5 mesh",
    "olvidate de los 5 mesh",
    # bare "no N" is not a previous quantity
    "no 5 mesh, gracias",
    "agrega 5 frontlit, no 5 mesh",
]


def _routes_safely(got):
    from quote_engine.domain.router import Apply, NewQuote, QuoteView, route

    for quotes in ([], [QuoteView("Q-001", {FBT: 20, MESH: 5}, frozenset({"c1"}))]):
        if got is None:
            continue
        d = route(got, "c1", quotes)
        assert not isinstance(d, NewQuote), (got, d)
        assert not (isinstance(d, Apply) and len(d.ops) > 1), (got, d)


@pytest.mark.parametrize("text", ROUND4)
@pytest.mark.parametrize(
    ("intent", "it"),
    [
        (Intent.UPDATE_QTY, item([FBT], 10, 20)),
        (Intent.ADD_ITEMS, item([MESH], 5)),
        (Intent.CREATE_QUOTE, item([MESH], 5)),
        (Intent.REMOVE_ITEM, item([MESH])),
        (Intent.CANCEL, None),
    ],
)
def test_round4_llm_readings_never_mutate(text, intent, it):
    got = guard(text, interp(intent, *([it] if it else [])))
    assert got is None or got.intent in (Intent.QUERY, Intent.NONE)
    _routes_safely(got)


@pytest.mark.parametrize("text", ROUND4)
async def test_round4_rules_never_mutate(text):
    from quote_engine.adapters.extractors.rules import RuleExtractor
    from quote_engine.application.ports import MessageCtx

    r = await RuleExtractor(CATALOG).interpret(MessageCtx("m", "c1", "cu", "inbound", text, []))
    assert r is None or r.intent in (Intent.QUERY, Intent.NONE)
    _routes_safely(r)


@pytest.mark.parametrize(
    ("text", "intent", "it"),
    [
        ("si, ponle 2 mas de esas", Intent.ADD_ITEMS, item([CYAN], 2)),
        ("me pasas 3 lonas frontlit", Intent.ADD_ITEMS, item([FBT], 3)),
        (
            "ah y otra cosa que se me olvido agregale tambien dos tintas amarillas",
            Intent.ADD_ITEMS,
            item([CYAN], 2),
        ),
    ],
)
def test_round4_assertive_messages_pass(text, intent, it):
    i = interp(intent, it)
    assert guard(text, i) is i


def test_me_pasas_with_number_is_an_order_and_without_is_a_query():
    assert guard("me pasas 3 lonas frontlit", interp(Intent.QUERY)) is None
    q = interp(Intent.QUERY)
    assert guard("me pasas el total de la Q-001 xfa", q) is q


TASK8B_REVIEW = [
    "cuando me autoricen agrega 5 mesh",
    "apenas me confirmen agrega 5 mesh",
    "agrega 5 mesh cuando puedas",
    "no quiero el mesh de 3.20 sino el de 2.50",
    "no quiero las frontlit sino mesh",
    "en vez de frontlit mejor 5 mesh",
    "estamos viendo agregar 5 mesh",
    "me interesa agregar 5 mesh",
    "habria chance de agregar 5 mesh",
    "en una de esas agrega 5 mesh",
    "serian 5 mesh",
    "agrega 5 mesh, te confirmo",
    "agrega 5 mesh y te aviso",
    "agrega 5 mesh, lo checo",
    "dejame checarlo, agrega 5 mesh",
    "agrega 5 mesh, lo pienso",
    "agrega 5 mesh, lo voy a pensar",
    "agrega 5 mesh y ahi lo vemos",
    "probablemente agrega 5 mesh",
    "posiblemente 5 mesh",
    "agrega 5 o 6 mesh",
    "agrega entre 5 y 6 mesh",
]


@pytest.mark.parametrize("text", TASK8B_REVIEW)
@pytest.mark.parametrize(
    ("intent", "it"),
    [
        (Intent.UPDATE_QTY, item([MESH], 5, 20)),
        (Intent.ADD_ITEMS, item([MESH], 5)),
        (Intent.CREATE_QUOTE, item([MESH], 5)),
        (Intent.REMOVE_ITEM, item([MESH])),
    ],
)
def test_task8b_llm_readings_never_mutate(text, intent, it):
    got = guard(text, interp(intent, it))
    assert got is None or got.intent in (Intent.QUERY, Intent.NONE)
    _routes_safely(got)


@pytest.mark.parametrize("text", TASK8B_REVIEW)
async def test_task8b_rules_never_mutate(text):
    from quote_engine.adapters.extractors.rules import RuleExtractor
    from quote_engine.application.ports import MessageCtx

    r = await RuleExtractor(CATALOG).interpret(MessageCtx("m", "c1", "cu", "inbound", text, []))
    assert r is None or r.intent in (Intent.QUERY, Intent.NONE)
    _routes_safely(r)


@pytest.mark.parametrize(
    "text",
    [
        "cotizame 5 mesh, quedo en espera",
        "si agrega 2 acrilicos blancos de 3mm",
        "sí mándame 5 mesh",
        "si, agrega 2 acrilicos blancos de 3mm",
        "agregame 5 mesh 3.20x100",
        "que sean 12 las sintras de 3mm",
        "quita el microperforado",
        "hola que tal mira necesitamos 15 lonas frontlit eh y nada mas eso seria todo gracias",
    ],
)
def test_task8b_assertive_orders_pass(text):
    i = interp(Intent.ADD_ITEMS, item([MESH], 5))
    assert guard(text, i) is i


async def test_task8b_assertive_rules_orders_still_extract():
    from quote_engine.adapters.extractors.rules import RuleExtractor
    from quote_engine.application.ports import MessageCtx

    for text in [
        "cotizame 5 mesh 3.20x100, quedo en espera",
        "si agrega 2 acrilicos blancos de 3mm",
    ]:
        r = await RuleExtractor(CATALOG).interpret(MessageCtx("m", "c1", "cu", "inbound", text, []))
        assert r is not None and r.intent == Intent.ADD_ITEMS, text


HEDGED_ORDERS = [
    "dame 5 mesh, cuando lo tengas me avisas",
    "ocupo 5 mesh para cuando puedas",
    "5 mesh 3.20x100 porfa, cuando puedas me avisas",
    "va, 5 mesh, cuando lo tengas me avisas",
    "listo, 5 mesh apenas puedas",
    "5 mesh, te aviso cualquier cosa",
    "serian 5 mesh",
    "5 mesh, serian todos",
    "5 mesh de 3.20 o 1.60",
]


@pytest.mark.parametrize("text", HEDGED_ORDERS)
@pytest.mark.parametrize("intent", [Intent.ADD_ITEMS, Intent.CREATE_QUOTE])
def test_hedged_orders_go_to_review_not_query(text, intent):
    assert guard(text, interp(intent, item([MESH], 5))) is None


@pytest.mark.parametrize("text", HEDGED_ORDERS)
@pytest.mark.parametrize("intent", [Intent.QUERY, Intent.NONE])
def test_hedged_order_read_as_no_action_with_qty_goes_to_review(text, intent):
    assert guard(text, interp(intent, item([MESH], 5))) is None


@pytest.mark.parametrize("text", HEDGED_ORDERS)
async def test_hedged_orders_rules_never_mutate(text):
    from quote_engine.adapters.extractors.rules import RuleExtractor
    from quote_engine.application.ports import MessageCtx

    r = await RuleExtractor(CATALOG).interpret(MessageCtx("m", "c1", "cu", "inbound", text, []))
    assert r is None or r.intent in (Intent.QUERY, Intent.NONE)
    _routes_safely(r)


def test_question_without_quantity_read_as_query_stays_a_query():
    q = interp(Intent.QUERY, item([MESH]))
    assert guard("cuando tienen mesh?", q) is q


@pytest.mark.parametrize(
    "text",
    [
        "mandame 5 mesh 3.20x100",
        "dame 5 mesh 3.20x100",
        "ocupo 5 mesh 3.20x100",
        "pasame 5 mesh 3.20x100",
    ],
)
async def test_more_order_verbs_are_rules_adds(text):
    from quote_engine.adapters.extractors.rules import RuleExtractor
    from quote_engine.application.ports import MessageCtx

    r = await RuleExtractor(CATALOG).interpret(MessageCtx("m", "c1", "cu", "inbound", text, []))
    assert r is not None and r.intent == Intent.ADD_ITEMS, text


@pytest.mark.parametrize(
    ("text", "delta"),
    [
        ("quitale dos a las lonas", -2),
        ("5 lonas menos", -5),
        ("ponle 5 lonas mas", 5),
        ("otras 5 lonas", 5),
        ("sumale otros cinco", 5),
        ("borrale 3 a las lonas", -3),
        ("sacale 2 a las frontlit", -2),
    ],
)
def test_relative_phrasings_become_deltas_not_absolute_qty(text, delta):
    # the LLM reads these as set_qty(N); the number is a change, never the new total
    got = guard(text, interp(Intent.UPDATE_QTY, item([FBT], abs(delta))))
    assert got is not None and got.intent == Intent.UPDATE_QTY
    [it] = got.items
    assert (it.qty, it.qty_delta) == (None, delta)


@pytest.mark.parametrize(
    "text",
    [
        "quitale veintitres a las lonas",  # a number word we do not map
        "ponle 10 rollos de mesh mas",
        "quitale unas 3 a las lonas",
        "quitale un rollo a las lonas",
        "dejale 4 lonas frontlit 3.20x100 menos",
    ],
)
@pytest.mark.parametrize("intent", [Intent.UPDATE_QTY, Intent.ADD_ITEMS, Intent.REMOVE_ITEM])
def test_unparsed_relative_change_goes_to_review(text, intent):
    assert guard(text, interp(intent, item([FBT], 3))) is None


@pytest.mark.parametrize(
    ("text", "intent", "it"),
    [
        ("quitale el mesh", Intent.REMOVE_ITEM, item([MESH])),
        ("bajale a 10 las frontlit", Intent.UPDATE_QTY, item([FBT], 10)),
        ("sumale 2 rollos de cyan", Intent.ADD_ITEMS, item([CYAN], 2)),
    ],
)
def test_absolute_changes_and_removals_still_pass(text, intent, it):
    i = interp(intent, it)
    assert guard(text, i) is i


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("te encargo 10 lonas", Intent.QUERY),
        ("van 10 lonas", Intent.NONE),
        ("van 10 lonas", Intent.QUERY),
    ],
)
def test_non_mutating_reading_with_a_quantity_goes_to_review(text, intent):
    assert guard(text, interp(intent, item([FBT], 10))) is None


@pytest.mark.parametrize(
    "text",
    [
        "mandenme 10 lonas",
        "mandenme lonas",
        "te encargo lonas frontlit",
        "les pido lonas frontlit",
        "les compro lonas frontlit",
        "requiero lonas frontlit",
        "requerimos lonas frontlit",
        "enviame lonas frontlit",
    ],
)
@pytest.mark.parametrize("intent", [Intent.NONE, Intent.QUERY])
def test_new_order_verbs_read_as_no_action_go_to_review(text, intent):
    assert guard(text, interp(intent)) is None


@pytest.mark.parametrize(
    "text",
    [
        "mandenme 10 lonas frontlit 3.20x100",
        "te encargo 10 rollos de mesh 3.20x100",
        "enviame 10 rollos de mesh 3.20x100",
        "requerimos 10 rollos de mesh 3.20x100",
    ],
)
async def test_new_order_verbs_are_rules_adds(text):
    from quote_engine.adapters.extractors.rules import RuleExtractor
    from quote_engine.application.ports import MessageCtx

    r = await RuleExtractor(CATALOG).interpret(MessageCtx("m", "c1", "cu", "inbound", text, []))
    assert r is not None and r.intent == Intent.ADD_ITEMS, text


@pytest.mark.parametrize(
    ("text", "intent", "it", "rule"),
    [
        ("cuanto me saldrian 10 frontlit?", Intent.UPDATE_QTY, item([FBT], 10), "hedged"),
        ("cotizame 10 frontlit", Intent.QUERY, item([FBT]), "ordered"),
        ("van 10 lonas", Intent.NONE, item([FBT], 10), "counted"),
        ("no me cambies a 10", Intent.UPDATE_QTY, item([FBT], 10), "negated"),
        ("lo mismo que ayer", Intent.UPDATE_QTY, item([FBT], 10), "temporal"),
        ("cancela lo del papel", Intent.CANCEL, None, "cancel_unnamed"),
        ("one way 1.52, 2 rollos", Intent.CREATE_QUOTE, item([MATE_152], 2, mention="one way 1.52"),
         "off_alias"),
        ("mandame 2 galones de tinta", Intent.CREATE_QUOTE, item([MAG], 2), "unit"),
        ("agrega 2 y que sean 10", Intent.ADD_ITEMS, item([FBT], 2), "add_and_set"),
        ("en vez de el blanco mejor el transparente", Intent.UPDATE_QTY, item([ACR], 1), "swap"),
        ("me equivoque de producto", Intent.UPDATE_QTY, item([ACR], 1), "mistake"),
        ("ponle 10 rollos de mesh mas", Intent.UPDATE_QTY, item([MESH], 10), "relative"),
        ("quitale 2 y ponle 3 mas", Intent.UPDATE_QTY, item([FBT], 2), "relative"),
    ],
)  # fmt: skip
def test_guard_rejections_are_logged_with_a_rule_name(text, intent, it, rule):
    from structlog.testing import capture_logs

    with capture_logs() as logs:
        assert guard(text, interp(intent, *([it] if it else []))) is None
    assert [(e["event"], e["rule"]) for e in logs] == [("guard_rejected", rule)]


@pytest.mark.parametrize(
    "text",
    [
        "cotizame lo del antepasado",
        "mandame lo de siempre",
        "quiero el mismo de la otra vez",
        "dame 5 como la otra vez",
    ],
)
def test_more_temporal_references_go_to_review(text):
    assert guard(text, interp(Intent.CREATE_QUOTE, item([MESH], 5))) is None


@pytest.mark.parametrize(
    "text",
    [
        "unas 15 lonas frontlit de 3.20 por 100 y 4 rollos de microperforado de 1.37 eh y nada mas",
        "4 rollos de microperforado 1.37 y ya nada mas",
    ],
)
def test_dimensions_and_nada_mas_are_not_relative_cues(text):
    i = interp(Intent.CREATE_QUOTE, item([FBT], 15), item([MICS_152], 4))
    assert guard(text, i) is i
