# Golden-set failures (baseline)

Every case whose routing decision differs from the human expectation, per mode. Classification: **wrong mutation** (applied/created something other than expected), **out-of-catalog misassigned** (a product we don't sell was mapped to a catalog SKU or mutated), **safe miss** (went to review instead of the expected action), **silent miss** (noop where an action or review was expected).

## Golden rulings (controller, round 2)

Six legacy cases changed `expected.decision` to `review`: the expanded catalog made each mention genuinely ambiguous (several SKUs, no single family default, no line in the quote to intersect), so picking one SKU would be a guess.

| case | why `review` |
|---|---|
| typo-lonsa | "lonsa frontlit" with no size: 6 Frontlit widths/lengths, all family defaults, so no single default; new quote has nothing to intersect. |
| para-new-mesh | "mesh 9x9" matches both mesh widths (3.20x100 and 2.50x100); mesh has no default. |
| words-diez-mesh | "lona mesh" with no size: 2 mesh SKUs, no default. |
| typo-acrilcos | "acrilicos blancos" with no thickness: 2/3/5mm, no default. |
| para-agrega-acrilicos | "acrilicos blancos" with no thickness: 2/3/5mm; Q-001 has no acrylic line to intersect. |
| words-dos-acrilicos | same as above ("dos acrilicos blancos", no thickness, no acrylic line in Q-001). |

## Mode `rules` — 67 / 123 failing

wrong mutation: 1, out-of-catalog misassigned: 1, safe miss: 65, silent miss (noop instead of action): 0

| case | category | text | expected | got | source | class |
|---|---|---|---|---|---|---|
| mi-two-intents | multi_item | agrega 2 acrilicos blancos de 3mm y que las lonas frontlit sean 10 | `apply:Q-001[add:ARACBL-03-122244=2,set_qty:ALFBTC-013-320100=10]` | `apply:Q-001[add:ARACBL-03-122244=2,set_qty:ALFBTC-013-320100=30]` | rules | wrong mutation |
| ca-unknown-product | cancel | cancela lo del papel fotografico | `review` | `apply:Q-001[cancel]` | rules | out-of-catalog misassigned |
| para-frontlit | legacy | que sean 15 las frontlit | `apply:Q-001[set_qty:ALFBTC-013-320100=15]` | `review` | None | safe miss |
| para-suma-mesh | legacy | súmale 1 rollo de mesh | `apply:Q-001[set_qty:ALMCLC-0909-320100=6]` | `review` | None | safe miss |
| para-ya-no-micro | legacy | ya no quiero el microperforado | `apply:Q-001[remove:AVMICS-1A-137050]` | `review` | None | safe miss |
| para-agrega-acrilicos | legacy | me puedes agregar 3 acrilicos blancos | `apply:Q-001[add:ARACBL-03-122244=3]` | `review` | rules | safe miss |
| para-new-mesh | legacy | necesito 10 rollos de mesh 9x9 | `new[ALMCLC-0909-320100=10]` | `review` | rules | safe miss |
| typo-acrilcos | legacy | cotizame 3 acrilcos blancos | `new[ARACBL-03-122244=3]` | `review` | None | safe miss |
| typo-lonsa | legacy | necesito 6 lonsa frontlit | `new[ALFBTC-013-320100=6]` | `review` | None | safe miss |
| typo-microperforadso | legacy | mejor que sean 12 los microperforadso | `apply:Q-001[set_qty:AVMICS-1A-137050=12]` | `review` | None | safe miss |
| words-diez-mesh | legacy | cotizame diez rollos de lona mesh | `new[ALMCLC-0909-320100=10]` | `review` | None | safe miss |
| words-quince-frontlit | legacy | mejor que sean quince las frontlit, no veinte | `apply:Q-001[set_qty:ALFBTC-013-320100=15]` | `review` | None | safe miss |
| words-dos-acrilicos | legacy | agrega dos acrilicos blancos | `apply:Q-001[add:ARACBL-03-122244=2]` | `review` | None | safe miss |
| trap-gracias | legacy | gracias! | `noop` | `review` | None | safe miss |
| trap-ok-atento | legacy | ok quedo atento | `noop` | `review` | None | safe miss |
| id-q1-mesh | legacy | en Q-001 pon 8 de las lonas mesh | `apply:Q-001[set_qty:ALMCLC-0909-320100=8]` | `review` | None | safe miss |
| cn-laminado-brillante | catalog_new | quiero 2 rollos de laminado brillante | `new[ALAMBR-01-137050=2]` | `review` | None | safe miss |
| ts-trovicel | typos_slang | nesesito 4 planchas de trovicel de 5mm xfa | `new[APPVEB-05-122244=4]` | `review` | None | safe miss |
| ts-malla | typos_slang | cotisame 2 rollos de malla 2.50 x100 | `new[ALMCLC-0909-250100=2]` | `review` | None | safe miss |
| ts-black-out | typos_slang | sumale 3 rollos de black out 3.20x100 porfa 🙏 | `apply:Q-001[add:ALBKOC-013-320100=3]` | `review` | None | safe miss |
| ts-vinilo | typos_slang | kiero 5 vinilos transparentes de 1.06 | `new[AVTRAN-1A-106050=5]` | `review` | None | safe miss |
| ts-acrilco-negro | typos_slang | 10 acrilcos negros d 3mm x fa | `new[ARACNG-03-122244=10]` | `review` | None | safe miss |
| ts-one-way | typos_slang | one way 1.52, 2 rollos | `new[AVMICS-1A-152050=2]` | `review` | None | safe miss |
| ts-lonsas-frontlit | typos_slang | q sean 18 las lonsas frontlit | `apply:Q-001[set_qty:ALFBTC-013-320100=18]` | `review` | None | safe miss |
| ts-sintras-plis | typos_slang | las sintras q sean 12 plis | `apply:Q-001[set_qty:APPVEB-03-122244=12]` | `review` | None | safe miss |
| uq-un-par | units_quantities | un par de rollos de laminado mate | `new[ALAMMT-01-137050=2]` | `review` | None | safe miss |
| uq-media-docena | units_quantities | cotizame media docena de tintas negras | `new[ATEBKN-1L-001000=6]` | `review` | None | safe miss |
| uq-docena | units_quantities | necesito una docena de sintras de 3mm | `new[APPVEB-03-122244=12]` | `review` | None | safe miss |
| uq-x2 | units_quantities | acrilico transparente 5mm x2 | `new[ARACTR-05-122244=2]` | `review` | None | safe miss |
| uq-2u | units_quantities | agregame 2u de lona blackout 2.50 | `apply:Q-001[add:ALBKOC-013-250100=2]` | `review` | None | safe miss |
| uq-veinticinco | units_quantities | cotizame veinticinco rollos de frontlit 1.60 | `new[ALFBTC-013-160100=25]` | `review` | None | safe miss |
| uq-litros | units_quantities | tinta cian 4 litros porfa | `new[ATECYN-1L-001000=4]` | `review` | None | safe miss |
| mi-add-two-new | multi_item | agregale 2 laminados brillantes y 1 tinta amarilla | `apply:Q-001[add:ALAMBR-01-137050=2,add:ATEYLN-1L-001000=1]` | `review` | rules | safe miss |
| mi-add-existing | multi_item | sumale 5 frontlit y 2 mesh | `apply:Q-001[set_qty:ALFBTC-013-320100=25,set_qty:ALMCLC-0909-320100=7]` | `review` | None | safe miss |
| mi-bullet-list | multi_item | Cotización porfa: / - 3 lonas frontlit 3.20x100 / - 2 mallas 3.20x100 / - 1 laminado mate | `new[ALAMMT-01-137050=1,ALFBTC-013-320100=3,ALMCLC-0909-320100=2]` | `review` | None | safe miss |
| co-eran-15 | corrections | perdon, eran 15 no 12 | `apply:Q-001[set_qty:APPVEB-05-122244=15]` | `review` | None | safe miss |
| co-swap-colour | corrections | me equivoque, era el blanco no el transparente 🙈 | `apply:Q-001[add:ARACBL-03-122244=4,remove:ARACTR-03-122244]` | `review` | None | safe miss |
| co-no-eran-3 | corrections | no eran 3 eran 5 los acrilicos negros | `apply:Q-001[set_qty:ARACNG-03-122244=5]` | `review` | None | safe miss |
| co-corrijo-blackout | corrections | corrijo: son 8 rollos de blackout, no 6 | `apply:Q-001[set_qty:ALBKOC-013-320100=8]` | `review` | None | safe miss |
| co-swap-width | corrections | ay perdon el vinil mate era de 1.37 no de 1.52 | `apply:Q-001[add:AVBLMT-1A-137050=3,remove:AVBLMT-1A-152050]` | `review` | None | safe miss |
| pr-quita-vinil | partial_remove | quita el vinil porfa | `apply:Q-001[remove:AVMICS-1A-137050]` | `review` | None | safe miss |
| pr-ya-no-sintra | partial_remove | ya no quiero el sintra | `apply:Q-001[remove:APPVEB-05-122244]` | `review` | None | safe miss |
| pr-sacame-tintas | partial_remove | sacame las tintas, ya tenemos | `apply:Q-001[remove:ATECYN-1L-001000,remove:ATEMGN-1L-001000]` | `review` | None | safe miss |
| pr-quitale-2 | partial_remove | quitale 2 a las frontlit | `apply:Q-001[set_qty:ALFBTC-013-320100=18]` | `review` | None | safe miss |
| oc-question-noop | out_of_catalog | tienen lona de 5 metros de ancho? | `noop` | `review` | None | safe miss |
| oc-question-link | out_of_catalog | y acrilico dorado manejan? para ver si lo sumo a la Q-001 | `apply:Q-001[]` | `review` | None | safe miss |
| qn-hola | questions_noop | hola buenas tardes 👋 | `noop` | `review` | None | safe miss |
| qn-precio | questions_noop | cuanto sale el rollo de lona frontlit 3.20? | `noop` | `review` | rules | safe miss |
| qn-stock | questions_noop | tienen stock de sintra 10mm? 🙏 | `noop` | `review` | None | safe miss |
| qn-entrega | questions_noop | para cuando estaria la entrega? | `noop` | `review` | None | safe miss |
| qn-total-q001 | questions_noop | me pasas el total de la Q-001 xfa | `apply:Q-001[]` | `review` | None | safe miss |
| qn-factura | questions_noop | me pueden facturar? necesito factura con mis datos fiscales | `noop` | `review` | None | safe miss |
| qn-gracias-jefe | questions_noop | ok gracias, lo reviso con mi jefe y te aviso 👍 | `noop` | `review` | None | safe miss |
| qn-price-en-vez-de | questions_noop | cuanto me sale si llevo 10 lonas frontlit en vez de 20? | `apply:Q-001[]` | `review` | None | safe miss |
| rf-history-esas | references | si, ponle 2 mas de esas | `apply:Q-001[set_qty:ATECYN-1L-001000=12]` | `review` | None | safe miss |
| rf-history-answer | references | 5 | `apply:Q-001[add:ALMCLC-0909-320100=5]` | `review` | None | safe miss |
| mq-prev-qty | multi_quote | las frontlit que sean 30, no 20 | `apply:Q-001[set_qty:ALFBTC-013-320100=30]` | `review` | None | safe miss |
| mq-explicit-add | multi_quote | en la Q-002 agregale 1 tinta negra | `apply:Q-002[add:ATEBKN-1L-001000=1]` | `review` | rules | safe miss |
| mq-three-tintas | multi_quote | las tintas que sean 6 | `apply:Q-003[set_qty:ATEMGN-1L-001000=6]` | `review` | None | safe miss |
| mq-add-by-content | multi_quote | sumale 2 sintras de 5mm | `apply:Q-002[set_qty:APPVEB-05-122244=12]` | `review` | None | safe miss |
| vn-new-order | voice_note | hola que tal buenas tardes mira te comento que necesitamos para el evento del sabado unas 15 lonas frontlit de 3.20 por 100 y tambien unos 4 rollos de vinil microperforado de 1.37 eh y nada mas eso seria todo muchas gracias | `new[ALFBTC-013-320100=15,AVMICS-1A-137050=4]` | `review` | None | safe miss |
| vn-update | voice_note | oye si mira lo de las lonas que te habia dicho veinte mejor dejalo en quince porque el cliente recorto el presupuesto y lo demas dejalo igual porfa | `apply:Q-001[set_qty:ALFBTC-013-320100=15]` | `review` | None | safe miss |
| vn-question | voice_note | eh hola si te queria preguntar si ustedes hacen envios a monterrey o hay que pasar a recoger porque la otra vez tardaron bastante y el cliente se enojo un poco | `noop` | `review` | None | safe miss |
| vn-add | voice_note | ah y otra cosa que se me olvido agregale tambien dos tintas amarillas y dos negras para completar el juego porfa | `apply:Q-001[add:ATEBKN-1L-001000=2,add:ATEYLN-1L-001000=2]` | `review` | None | safe miss |
| ca-by-content | cancel | cancela la cotizacion de las tintas | `apply:Q-002[cancel]` | `review` | None | safe miss |
| ca-partial | cancel | cancela el microperforado nomas, lo demas sigue | `apply:Q-001[remove:AVMICS-1A-137050]` | `review` | None | safe miss |
| ca-negated | cancel | no no, no cancelen nada, seguimos con la cotizacion | `noop` | `review` | None | safe miss |

## Mode `cascade` — 38 / 123 failing

wrong mutation: 9, out-of-catalog misassigned: 1, safe miss: 25, silent miss (noop instead of action): 3

| case | category | text | expected | got | source | class |
|---|---|---|---|---|---|---|
| ts-one-way | typos_slang | one way 1.52, 2 rollos | `new[AVMICS-1A-152050=2]` | `new[AVBLMT-1A-152050=2]` | llm | wrong mutation |
| uq-galones | units_quantities | mandame 2 galones de tinta magenta | `review` | `new[ATEMGN-1L-001000=2]` | llm | wrong mutation |
| mi-two-intents | multi_item | agrega 2 acrilicos blancos de 3mm y que las lonas frontlit sean 10 | `apply:Q-001[add:ARACBL-03-122244=2,set_qty:ALFBTC-013-320100=10]` | `apply:Q-001[add:ARACBL-03-122244=2,set_qty:ALFBTC-013-320100=30]` | rules | wrong mutation |
| co-swap-colour | corrections | me equivoque, era el blanco no el transparente 🙈 | `apply:Q-001[add:ARACBL-03-122244=4,remove:ARACTR-03-122244]` | `apply:Q-001[set_qty:ARACTR-03-122244=4]` | llm | wrong mutation |
| pr-quitale-2 | partial_remove | quitale 2 a las frontlit | `apply:Q-001[set_qty:ALFBTC-013-320100=18]` | `apply:Q-001[remove:ALFBTC-013-320100]` | llm | wrong mutation |
| qn-price-en-vez-de | questions_noop | cuanto me sale si llevo 10 lonas frontlit en vez de 20? | `apply:Q-001[]` | `apply:Q-001[set_qty:ALFBTC-013-320100=10]` | llm | wrong mutation |
| rf-la-de-ayer | references | la de ayer cambiala a 10 rollos | `review` | `apply:Q-001[set_qty:ALMCLC-0909-320100=10]` | llm | wrong mutation |
| rf-history-esas | references | si, ponle 2 mas de esas | `apply:Q-001[set_qty:ATECYN-1L-001000=12]` | `apply:Q-001[set_qty:ATECYN-1L-001000=2]` | llm | wrong mutation |
| ca-partial | cancel | cancela el microperforado nomas, lo demas sigue | `apply:Q-001[remove:AVMICS-1A-137050]` | `apply:Q-001[cancel]` | llm | wrong mutation |
| ca-unknown-product | cancel | cancela lo del papel fotografico | `review` | `apply:Q-001[cancel]` | rules | out-of-catalog misassigned |
| para-agrega-acrilicos | legacy | me puedes agregar 3 acrilicos blancos | `apply:Q-001[add:ARACBL-03-122244=3]` | `review` | rules | safe miss |
| para-new-mesh | legacy | necesito 10 rollos de mesh 9x9 | `new[ALMCLC-0909-320100=10]` | `review` | rules | safe miss |
| typo-acrilcos | legacy | cotizame 3 acrilcos blancos | `new[ARACBL-03-122244=3]` | `review` | llm | safe miss |
| typo-lonsa | legacy | necesito 6 lonsa frontlit | `new[ALFBTC-013-320100=6]` | `review` | llm | safe miss |
| words-diez-mesh | legacy | cotizame diez rollos de lona mesh | `new[ALMCLC-0909-320100=10]` | `review` | llm | safe miss |
| words-dos-acrilicos | legacy | agrega dos acrilicos blancos | `apply:Q-001[add:ARACBL-03-122244=2]` | `review` | llm | safe miss |
| uq-docena | units_quantities | necesito una docena de sintras de 3mm | `new[APPVEB-03-122244=12]` | `review` | llm | safe miss |
| uq-litros | units_quantities | tinta cian 4 litros porfa | `new[ATECYN-1L-001000=4]` | `review` | llm | safe miss |
| mi-add-two-new | multi_item | agregale 2 laminados brillantes y 1 tinta amarilla | `apply:Q-001[add:ALAMBR-01-137050=2,add:ATEYLN-1L-001000=1]` | `review` | rules | safe miss |
| co-eran-15 | corrections | perdon, eran 15 no 12 | `apply:Q-001[set_qty:APPVEB-05-122244=15]` | `review` | llm | safe miss |
| co-swap-width | corrections | ay perdon el vinil mate era de 1.37 no de 1.52 | `apply:Q-001[add:AVBLMT-1A-137050=3,remove:AVBLMT-1A-152050]` | `review` | llm | safe miss |
| pr-quita-vinil | partial_remove | quita el vinil porfa | `apply:Q-001[remove:AVMICS-1A-137050]` | `review` | llm | safe miss |
| pr-ya-no-sintra | partial_remove | ya no quiero el sintra | `apply:Q-001[remove:APPVEB-05-122244]` | `review` | llm | safe miss |
| pr-sacame-tintas | partial_remove | sacame las tintas, ya tenemos | `apply:Q-001[remove:ATECYN-1L-001000,remove:ATEMGN-1L-001000]` | `review` | llm | safe miss |
| oc-question-noop | out_of_catalog | tienen lona de 5 metros de ancho? | `noop` | `review` | llm | safe miss |
| qn-precio | questions_noop | cuanto sale el rollo de lona frontlit 3.20? | `noop` | `review` | rules | safe miss |
| qn-stock | questions_noop | tienen stock de sintra 10mm? 🙏 | `noop` | `review` | llm | safe miss |
| qn-entrega | questions_noop | para cuando estaria la entrega? | `noop` | `review` | llm | safe miss |
| qn-factura | questions_noop | me pueden facturar? necesito factura con mis datos fiscales | `noop` | `review` | llm | safe miss |
| rf-history-answer | references | 5 | `apply:Q-001[add:ALMCLC-0909-320100=5]` | `review` | llm | safe miss |
| mq-explicit-add | multi_quote | en la Q-002 agregale 1 tinta negra | `apply:Q-002[add:ATEBKN-1L-001000=1]` | `review` | rules | safe miss |
| mq-three-tintas | multi_quote | las tintas que sean 6 | `apply:Q-003[set_qty:ATEMGN-1L-001000=6]` | `review` | llm | safe miss |
| mq-add-by-content | multi_quote | sumale 2 sintras de 5mm | `apply:Q-002[set_qty:APPVEB-05-122244=12]` | `review` | llm | safe miss |
| vn-question | voice_note | eh hola si te queria preguntar si ustedes hacen envios a monterrey o hay que pasar a recoger porque la otra vez tardaron bastante y el cliente se enojo un poco | `noop` | `review` | llm | safe miss |
| ca-by-content | cancel | cancela la cotizacion de las tintas | `apply:Q-002[cancel]` | `review` | llm | safe miss |
| ts-trovicel | typos_slang | nesesito 4 planchas de trovicel de 5mm xfa | `new[APPVEB-05-122244=4]` | `noop` | llm | silent miss (noop instead of action) |
| ts-sintras-plis | typos_slang | las sintras q sean 12 plis | `apply:Q-001[set_qty:APPVEB-03-122244=12]` | `noop` | llm | silent miss (noop instead of action) |
| oc-papel-foto | out_of_catalog | cotizame 100 hojas de papel fotografico | `review` | `noop` | llm | silent miss (noop instead of action) |

Out-of-catalog cases routed correctly but with a catalog SKU assigned to the unknown product (routing saved by another rule):

- vn-mixed-unknown: got skus ['ALBKOC-013-220100', 'ALBKOC-013-250100', 'ALBKOC-013-320050', 'ALBKOC-013-320100', 'ALFBTC-013-160100', 'ALFBTC-013-220100', 'ALFBTC-013-250050', 'ALFBTC-013-250100', 'ALFBTC-013-320050', 'ALFBTC-013-320100', 'ALMCLC-0909-250100', 'ALMCLC-0909-320100']

## Status after Task 8 (bounded adjustment loop)

Rules mode re-run in full; cascade re-run only on the affected cases (5 `--only` batches, 63 cases total, never the full set). "—" = the case was not failing in that mode at baseline. After Task 8: **rules 0 wrong mutations, 0 silent misses (47 failing, all safe reviews; baseline 61 after the golden rulings)**; **cascade on the re-run cases: 0 wrong mutations, 0 silent misses, 0 out-of-catalog misassignments**.

| case | category | rules now | cascade now | status |
|---|---|---|---|---|
| para-frontlit | legacy | fixed | — | fixed |
| para-suma-mesh | legacy | fixed | — | fixed |
| para-ya-no-micro | legacy | review (safe) | — | known — needs rules REMOVE_ITEM support (rules have no remove intent) |
| typo-microperforadso | legacy | review (safe) | — | known — needs fuzzy alias matching in rules (typo) |
| words-quince-frontlit | legacy | review (safe) | — | known — needs number words in rules |
| trap-gracias | legacy | review (safe) | — | known — needs rules NONE intent for chatter |
| trap-ok-atento | legacy | review (safe) | — | known — needs rules NONE intent for chatter |
| id-q1-mesh | legacy | review (safe) | — | known — needs 'pon N de' set-quantity verb in rules |
| cn-laminado-brillante | catalog_new | fixed | — | fixed |
| ts-trovicel | typos_slang | fixed | fixed | fixed |
| ts-malla | typos_slang | fixed | — | fixed |
| ts-black-out | typos_slang | fixed | — | fixed |
| ts-vinilo | typos_slang | fixed | — | fixed |
| ts-acrilco-negro | typos_slang | review (safe) | — | known — needs fuzzy alias matching in rules (typo) + 'd'/'x fa' slang |
| ts-one-way | typos_slang | review (safe) | fixed | known — needs rules intent for messages without a verb (cascade fixed) |
| ts-lonsas-frontlit | typos_slang | fixed | — | fixed |
| ts-sintras-plis | typos_slang | fixed | fixed | fixed |
| uq-un-par | units_quantities | review (safe) | — | known — needs quantity words (par/docena) in rules |
| uq-media-docena | units_quantities | review (safe) | — | known — needs quantity words in rules |
| uq-docena | units_quantities | review (safe) | not re-run (unchanged path; review) | known — needs quantity words in rules; cascade LLM output not accepted |
| uq-x2 | units_quantities | review (safe) | — | known — needs 'x2' quantity syntax in rules |
| uq-2u | units_quantities | review (safe) | — | known — needs '2u' unit syntax in rules |
| uq-veinticinco | units_quantities | review (safe) | — | known — needs number words in rules |
| uq-litros | units_quantities | review (safe) | not re-run (unchanged path; review) | known — needs 'litros' as unit for 1L ink in rules; cascade LLM output not accepted |
| uq-galones | units_quantities | — | fixed | fixed |
| mi-add-two-new | multi_item | fixed | fixed | fixed (plural laminado aliases) |
| mi-add-existing | multi_item | fixed | — | fixed |
| mi-two-intents | multi_item | review (safe) | review (safe) | known — needs per-item intents in the contract (one intent per message) — now review by design |
| mi-bullet-list | multi_item | review (safe) | — | known — needs rules: multi-line bullet lists |
| co-eran-15 | corrections | review (safe) | not re-run (unchanged path; review) | known — needs elliptic correction without product ('eran 15 no 12'): history resolution |
| co-swap-colour | corrections | review (safe) | review (safe) | known — needs a swap op (remove X + add Y) in the contract — now review by design |
| co-no-eran-3 | corrections | review (safe) | — | known — needs rules parsing of 'no eran N eran M' |
| co-corrijo-blackout | corrections | review (safe) | — | known — needs rules parsing of 'son N, no M' |
| co-swap-width | corrections | review (safe) | not re-run (unchanged path; review) | known — needs a swap op in the contract — review by design |
| pr-quita-vinil | partial_remove | review (safe) | not re-run (unchanged path; review) | known — needs rules REMOVE_ITEM support; cascade LLM picks no single line |
| pr-ya-no-sintra | partial_remove | review (safe) | fixed | known — needs rules REMOVE_ITEM support |
| pr-sacame-tintas | partial_remove | review (safe) | not re-run (unchanged path; review) | known — needs REMOVE of a family covering several lines (router removes one line per mention) |
| pr-quitale-2 | partial_remove | review (safe) | fixed | known — needs rules parsing of 'quitale N a X' (cascade fixed via guard + qty_delta) |
| oc-papel-foto | out_of_catalog | — | fixed | fixed |
| oc-question-noop | out_of_catalog | review (safe) | fixed | known — needs rules question parsing (cascade fixed) |
| oc-question-link | out_of_catalog | review (safe) | — | known — needs rules question parsing (cascade fixed) |
| qn-hola | questions_noop | review (safe) | — | known — needs rules NONE intent for chatter |
| qn-precio | questions_noop | fixed | fixed | fixed |
| qn-stock | questions_noop | review (safe) | fixed | known — needs rules question parsing (cascade fixed) |
| qn-entrega | questions_noop | review (safe) | not re-run (unchanged path; review) | known — LLM extraction for logistics/billing questions (not re-run; review) |
| qn-total-q001 | questions_noop | review (safe) | — | known — needs rules question parsing |
| qn-factura | questions_noop | review (safe) | not re-run (unchanged path; review) | known — needs same as qn-entrega |
| qn-gracias-jefe | questions_noop | review (safe) | — | known — needs rules NONE intent for chatter |
| qn-price-en-vez-de | questions_noop | review (safe) | fixed | known — needs rules question parsing (cascade fixed) |
| rf-la-de-ayer | references | — | fixed | fixed |
| rf-history-esas | references | review (safe) | fixed | known — needs rules history resolution (cascade fixed via guard) |
| rf-history-answer | references | review (safe) | not re-run (unchanged path; review) | known — needs history resolution of a bare number answering the rep |
| mq-prev-qty | multi_quote | fixed | — | fixed |
| mq-explicit-add | multi_quote | review (safe) | not re-run (unchanged path; review) | known — needs router: ADD with explicit quote id ignores the id (uses linked quote) |
| mq-three-tintas | multi_quote | fixed | fixed | fixed |
| mq-add-by-content | multi_quote | review (safe) | review (safe) | known — needs router: ADD picks the linked quote, not the one matching by content |
| vn-new-order | voice_note | review (safe) | — | known — needs rules: long voice-note phrasing |
| vn-update | voice_note | review (safe) | — | known — needs rules: number words / long phrasing |
| vn-question | voice_note | review (safe) | not re-run (unchanged path; review) | known — needs same as qn-entrega |
| vn-add | voice_note | review (safe) | — | known — needs rules: number words |
| ca-by-content | cancel | review (safe) | review (safe) | known — needs cancel resolved by content: LLM output not accepted / rules give up |
| ca-partial | cancel | review (safe) | review (safe) | known — needs cancel+product as line removal: cascade now review by design; needs remove_item mapping |
| ca-negated | cancel | review (safe) | — | known — needs rules NONE intent for negated cancels |
| vn-cancel | voice_note | review (safe) — new | — (still passes via LLM) | known — long cancel is no longer a bare cancel in rules (deliberate: safer); needs nothing in cascade |
| ca-unknown-product | cancel | fixed | fixed | fixed |

Baseline wrong mutations (cascade 9 + 1 out-of-catalog, rules 1 + 1) — how each was closed:

| case | fix |
|---|---|
| ca-unknown-product | rules: only a short filler-only message is a bare cancel; guard: an itemless cancel that names something (not "todo"/"la cotizacion") -> review |
| ca-partial | router: cancel naming only part of a quote -> review; guard as above for the LLM's itemless cancel |
| qn-price-en-vez-de | guard: price/availability questions are downgraded to `query` -> `apply:Q-001[]` |
| rf-la-de-ayer | guard: temporal references ("ayer", "vez pasada", ...) on a mutation -> review |
| pr-quitale-2 | additive `ItemMention.qty_delta` (hidden from the LLM schema); guard parses "quitale N"/"N menos" -> `SetQty(current - N)` |
| rf-history-esas | guard: "N mas" on a single item -> add N on top of the existing line |
| mi-two-intents | rules give up and guard reviews when add and set-quantity markers co-occur |
| co-swap-colour | guard: "era X no Y" / "me equivoque" without numbers -> review |
| ts-one-way | prompt states "one way" = microperforado; guard rejects candidates outside the aliases named in the mention |
| uq-galones | guard: units we do not sell by (galones, cajas, kg, metros, ...) -> review |
