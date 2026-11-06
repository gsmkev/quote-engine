# Golden-set failures (final round-2 runs)

Every case whose routing decision differs from the human expectation, per mode, from the canonical `results-<mode>-koeti-lab.json` (`rules`: 127 cases; `cascade`/`llm`: the first 123 — the 4 cases added after the final review were run with `--only`, see below; 2-core ARM64 CPU VM, Qwen3-4B-Instruct-2507 Q4_K_M). Classes:

* **wrong mutation** — applied/created something that leaves the quote in a different state than expected;
* **extra op, no state change** — the ops differ from the expected ones, but the resulting quote is identical (e.g. a `set_qty` to the quantity the line already has: the aggregate emits no event). Counted as "wrong apply/new" by the harness, which compares ops exactly;
* **out-of-catalog misassigned** — a product we don't sell was mapped to a catalog SKU or mutated a quote;
* **silent miss** — `noop` where an action or a review was expected;
* **safe miss** — review where an action (or a no-op) was expected; a human sees it, nothing changes.

## Summary

| mode | failing | wrong mutation | extra op, no state change | out-of-catalog misassigned | silent miss | safe miss |
|---|---|---|---|---|---|---|
| `rules` | 49 | 0 | 0 | 0 | 0 | 49 |
| `cascade` | 17 | 0 | 1 (co-eran-15) | 0 | 0 | 16 |
| `llm` (ablation) | 24 | **1 (cn-lona-250-length-open)** | 1 (co-eran-15) | 0 | **1 (rf-vez-pasada)** | 21 |

**Open wrong mutation (LLM-only mode):** `cn-lona-250-length-open` — "cotizame 8 lonas de 2.50" (expected review: Frontlit 2.50x100 and 2.50x50 both fit) became `new[ALFBTC-013-250100=8]`. The LLM listed only the 100 m variants and the family default picked Frontlit among them. The production cascade answers this case correctly (the rules see both lengths and give up to review), but nothing stops the same LLM narrowing on a message the rules don't parse. Fix to decide: re-check LLM candidates with the rules' attribute filter before the default is applied.

**Open silent miss (LLM-only mode):** `rf-vez-pasada` — "lo mismo que la vez pasada porfa" read as `none` by the LLM → no-op instead of review (the Guard checks temporal references only on mutating intents).

LLM calls that still failed validation after Instructor's 2 retries (`sku_candidates must be non-empty iff in_catalog`): 2 in the cascade run, 1 in the llm run. Each went to review (`extraction_failed`) — the contract validator doing its job, not a mutation.

## Final-review fixes: targeted `--only` cascade run

After the final review the Guard learned to read relative changes in words and phrasings ("quitale dos", "5 lonas menos", "otras 5"), to review relative cues it cannot read, to review quantities on `query`/`none` readings, and new order verbs (`mandenme`, `te encargo`, `requiero`, `enviame`, …). The 4 new cases plus every golden case touching relative cues or order verbs were run in `cascade` with `--only` (14 cases; full cascade/llm not re-run):

| case | expected | got | source | |
|---|---|---|---|---|
| uq-quitale-dos | `apply:Q-001[set_qty:ALFBTC-013-320100=18]` | same | llm | ok |
| co-5-menos | `apply:Q-001[set_qty:ALFBTC-013-320100=15]` | same | llm | ok |
| uq-te-encargo | `new[ALMCLC-0909-320100=10]` | same | rules | ok |
| uq-mandenme | `new[ALFBTC-013-320100=10]` | same | rules | ok |
| mi-more-micro-plus-ink, pr-not-in-quote, pr-quitale-2, pr-which-vinil, oc-remove-unknown, rf-history-esas, mq-remove-both-have | as expected | same | | ok |
| pr-quita-vinil, pr-sacame-tintas | remove | `review` | llm | safe miss (known, see cascade section) |
| vn-new-order | `new[ALFBTC-013-320100=15,AVMICS-1A-137050=4]` | `review` → after fix `new[…]` | llm | the first version of the relative catch-all read "1.37 eh y nada mas" as a cue (safe miss); fixed (dimension digits and "nada mas" are not cues), re-run alone: ok |

14 cases: 0 wrong mutations, 12/14 exact after the vn-new-order fix, 2 known safe misses.

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

## Mode `rules` — 49 / 127 failing

wrong mutation: 0, extra op, no state change: 0, out-of-catalog misassigned: 0, silent miss: 0, safe miss: 49

| case | category | text | expected | got | source | class | status |
|---|---|---|---|---|---|---|---|
| para-ya-no-micro | legacy | ya no quiero el microperforado | `apply:Q-001[remove:AVMICS-1A-137050]` | `review` | None | safe miss | known — needs rules REMOVE_ITEM support (rules have no remove intent) |
| typo-microperforadso | legacy | mejor que sean 12 los microperforadso | `apply:Q-001[set_qty:AVMICS-1A-137050=12]` | `review` | None | safe miss | known — needs fuzzy alias matching in rules (typo) |
| words-quince-frontlit | legacy | mejor que sean quince las frontlit, no veinte | `apply:Q-001[set_qty:ALFBTC-013-320100=15]` | `review` | None | safe miss | known — needs number words in rules |
| trap-gracias | legacy | gracias! | `noop` | `review` | None | safe miss | known — needs a rules NONE intent for chatter |
| trap-ok-atento | legacy | ok quedo atento | `noop` | `review` | None | safe miss | known — needs a rules NONE intent for chatter |
| id-q1-mesh | legacy | en Q-001 pon 8 de las lonas mesh | `apply:Q-001[set_qty:ALMCLC-0909-320100=8]` | `review` | None | safe miss | known — needs a 'pon N de' set-quantity verb in rules |
| ts-acrilco-negro | typos_slang | 10 acrilcos negros d 3mm x fa | `new[ARACNG-03-122244=10]` | `review` | None | safe miss | known — needs fuzzy alias matching in rules (typo) + 'd'/'x fa' slang |
| ts-one-way | typos_slang | one way 1.52, 2 rollos | `new[AVMICS-1A-152050=2]` | `review` | None | safe miss | known — needs a rules intent for messages without a verb |
| uq-un-par | units_quantities | un par de rollos de laminado mate | `new[ALAMMT-01-137050=2]` | `review` | None | safe miss | known — needs quantity words (par/docena) in rules |
| uq-media-docena | units_quantities | cotizame media docena de tintas negras | `new[ATEBKN-1L-001000=6]` | `review` | None | safe miss | known — needs quantity words in rules |
| uq-docena | units_quantities | necesito una docena de sintras de 3mm | `new[APPVEB-03-122244=12]` | `review` | None | safe miss | known — needs quantity words in rules |
| uq-x2 | units_quantities | acrilico transparente 5mm x2 | `new[ARACTR-05-122244=2]` | `review` | None | safe miss | known — needs 'x2' quantity syntax in rules |
| uq-2u | units_quantities | agregame 2u de lona blackout 2.50 | `apply:Q-001[add:ALBKOC-013-250100=2]` | `review` | None | safe miss | known — needs '2u' unit syntax in rules |
| uq-veinticinco | units_quantities | cotizame veinticinco rollos de frontlit 1.60 | `new[ALFBTC-013-160100=25]` | `review` | None | safe miss | known — needs number words in rules |
| uq-litros | units_quantities | tinta cian 4 litros porfa | `new[ATECYN-1L-001000=4]` | `review` | None | safe miss | known — needs 'litros' as the unit of the 1 L inks in rules |
| mi-two-intents | multi_item | agrega 2 acrilicos blancos de 3mm y que las lonas frontlit sean 10 | `apply:Q-001[add:ARACBL-03-122244=2,set_qty:ALFBTC-013-320100=10]` | `review` | None | safe miss | known — needs per-item intents in the contract (one intent per message); review by design |
| mi-bullet-list | multi_item | Cotización porfa: / - 3 lonas frontlit 3.20x100 / - 2 mallas 3.20x100 / - 1 laminado mate | `new[ALAMMT-01-137050=1,ALFBTC-013-320100=3,ALMCLC-0909-320100=2]` | `review` | None | safe miss | known — needs rules parsing of multi-line bullet lists |
| co-eran-15 | corrections | perdon, eran 15 no 12 | `apply:Q-001[set_qty:APPVEB-05-122244=15]` | `review` | None | safe miss | known — needs an elliptic correction without product ('eran 15 no 12') resolved from history |
| co-swap-colour | corrections | me equivoque, era el blanco no el transparente 🙈 | `apply:Q-001[add:ARACBL-03-122244=4,remove:ARACTR-03-122244]` | `review` | None | safe miss | known — needs a swap op (remove X + add Y) in the contract; review by design |
| co-no-eran-3 | corrections | no eran 3 eran 5 los acrilicos negros | `apply:Q-001[set_qty:ARACNG-03-122244=5]` | `review` | None | safe miss | known — needs rules parsing of 'no eran N eran M' |
| co-corrijo-blackout | corrections | corrijo: son 8 rollos de blackout, no 6 | `apply:Q-001[set_qty:ALBKOC-013-320100=8]` | `review` | None | safe miss | known — needs rules parsing of 'son N, no M' |
| co-swap-width | corrections | ay perdon el vinil mate era de 1.37 no de 1.52 | `apply:Q-001[add:AVBLMT-1A-137050=3,remove:AVBLMT-1A-152050]` | `review` | None | safe miss | known — needs a swap op in the contract; review by design |
| pr-quita-vinil | partial_remove | quita el vinil porfa | `apply:Q-001[remove:AVMICS-1A-137050]` | `review` | None | safe miss | known — needs rules REMOVE_ITEM support |
| pr-ya-no-sintra | partial_remove | ya no quiero el sintra | `apply:Q-001[remove:APPVEB-05-122244]` | `review` | None | safe miss | known — needs rules REMOVE_ITEM support |
| pr-sacame-tintas | partial_remove | sacame las tintas, ya tenemos | `apply:Q-001[remove:ATECYN-1L-001000,remove:ATEMGN-1L-001000]` | `review` | None | safe miss | known — needs rules REMOVE_ITEM support |
| pr-quitale-2 | partial_remove | quitale 2 a las frontlit | `apply:Q-001[set_qty:ALFBTC-013-320100=18]` | `review` | None | safe miss | known — needs rules parsing of 'quitale N a X' (the Guard handles it on the LLM path) |
| oc-question-noop | out_of_catalog | tienen lona de 5 metros de ancho? | `noop` | `review` | None | safe miss | known — needs rules question parsing |
| oc-question-link | out_of_catalog | y acrilico dorado manejan? para ver si lo sumo a la Q-001 | `apply:Q-001[]` | `review` | None | safe miss | known — needs rules question parsing |
| qn-hola | questions_noop | hola buenas tardes 👋 | `noop` | `review` | None | safe miss | known — needs a rules NONE intent for chatter |
| qn-stock | questions_noop | tienen stock de sintra 10mm? 🙏 | `noop` | `review` | None | safe miss | known — needs rules question parsing |
| qn-entrega | questions_noop | para cuando estaria la entrega? | `noop` | `review` | None | safe miss | known — needs rules question parsing (no product) |
| qn-total-q001 | questions_noop | me pasas el total de la Q-001 xfa | `apply:Q-001[]` | `review` | None | safe miss | known — needs rules question parsing |
| qn-factura | questions_noop | me pueden facturar? necesito factura con mis datos fiscales | `noop` | `review` | None | safe miss | known — needs rules question parsing (no product) |
| qn-gracias-jefe | questions_noop | ok gracias, lo reviso con mi jefe y te aviso 👍 | `noop` | `review` | None | safe miss | known — needs a rules NONE intent for chatter |
| qn-price-en-vez-de | questions_noop | cuanto me sale si llevo 10 lonas frontlit en vez de 20? | `apply:Q-001[]` | `review` | None | safe miss | known — needs rules question parsing; the Guard refuses the mutation by design |
| rf-history-esas | references | si, ponle 2 mas de esas | `apply:Q-001[set_qty:ATECYN-1L-001000=12]` | `review` | None | safe miss | known — needs history resolution in rules |
| rf-history-answer | references | 5 | `apply:Q-001[add:ALMCLC-0909-320100=5]` | `review` | None | safe miss | known — needs history resolution of a bare number answering the rep |
| mq-explicit-add | multi_quote | en la Q-002 agregale 1 tinta negra | `apply:Q-002[add:ATEBKN-1L-001000=1]` | `review` | rules | safe miss | known — needs router: ADD with an explicit quote id ignores the id (uses the chat-linked quote) |
| mq-add-by-content | multi_quote | sumale 2 sintras de 5mm | `apply:Q-002[set_qty:APPVEB-05-122244=12]` | `review` | rules | safe miss | known — needs router: ADD picks the chat-linked quote, not the one matching by content |
| vn-new-order | voice_note | hola que tal buenas tardes mira te comento que necesitamos para el evento del sabado unas 15 lonas frontlit de 3.20 por 100 y tambien unos 4 rollos de vinil microperforado de 1.37 eh y nada mas eso seria todo muchas gracias | `new[ALFBTC-013-320100=15,AVMICS-1A-137050=4]` | `review` | None | safe miss | known — needs rules parsing of long voice-note phrasing |
| vn-update | voice_note | oye si mira lo de las lonas que te habia dicho veinte mejor dejalo en quince porque el cliente recorto el presupuesto y lo demas dejalo igual porfa | `apply:Q-001[set_qty:ALFBTC-013-320100=15]` | `review` | None | safe miss | known — needs number words / long phrasing in rules |
| vn-question | voice_note | eh hola si te queria preguntar si ustedes hacen envios a monterrey o hay que pasar a recoger porque la otra vez tardaron bastante y el cliente se enojo un poco | `noop` | `review` | None | safe miss | known — needs rules question parsing |
| vn-cancel | voice_note | mira al final el cliente se echo para atras asi que cancela todo lo que teniamos cotizado perdon por las molestias eh | `apply:Q-001[cancel]` | `review` | None | safe miss | known — a long cancel is not a bare cancel in rules (deliberate: safer) |
| vn-add | voice_note | ah y otra cosa que se me olvido agregale tambien dos tintas amarillas y dos negras para completar el juego porfa | `apply:Q-001[add:ATEBKN-1L-001000=2,add:ATEYLN-1L-001000=2]` | `review` | None | safe miss | known — needs number words in rules |
| ca-by-content | cancel | cancela la cotizacion de las tintas | `apply:Q-002[cancel]` | `review` | None | safe miss | known — needs a cancel resolved by content (rules give up; the LLM's item-less cancel naming 'las tintas' is refused by the Guard) |
| ca-partial | cancel | cancela el microperforado nomas, lo demas sigue | `apply:Q-001[remove:AVMICS-1A-137050]` | `review` | None | safe miss | known — needs cancel + product mapped to a line removal; review by design |
| ca-negated | cancel | no no, no cancelen nada, seguimos con la cotizacion | `noop` | `review` | None | safe miss | known — needs a rules NONE intent for negated cancels |
| uq-quitale-dos | units_quantities | quitale dos a las frontlit | `apply:Q-001[set_qty:ALFBTC-013-320100=18]` | `review` | None | safe miss | known — rules have no relative intent; the Guard turns the LLM's reading into a delta |
| co-5-menos | corrections | 5 lonas frontlit menos | `apply:Q-001[set_qty:ALFBTC-013-320100=15]` | `review` | None | safe miss | known — rules have no relative intent; the Guard turns the LLM's reading into a delta |

## Mode `cascade` — 17 / 123 failing

wrong mutation: 0, extra op, no state change: 1, out-of-catalog misassigned: 0, silent miss: 0, safe miss: 16

| case | category | text | expected | got | source | class | status |
|---|---|---|---|---|---|---|---|
| co-eran-15 | corrections | perdon, eran 15 no 12 | `apply:Q-001[set_qty:APPVEB-05-122244=15]` | `apply:Q-001[set_qty:APPVEB-05-122244=15,set_qty:ARACBL-03-122244=2]` | llm | extra op, no state change | known — LLM resolved the elliptic correction from history and also restated the other line (`set_qty:ARACBL=2`, already 2): final state is the expected one, no event for the extra op. Needs nothing for correctness; an exact-ops contract would need the LLM to emit only the changed line |
| uq-litros | units_quantities | tinta cian 4 litros porfa | `new[ATECYN-1L-001000=4]` | `review` | llm | safe miss | known — the LLM flagged '4 litros' of tinta cian as not in the catalog (it sells 1 L bottles) → review; needs litros↔1 L in the prompt or rules |
| mi-two-intents | multi_item | agrega 2 acrilicos blancos de 3mm y que las lonas frontlit sean 10 | `apply:Q-001[add:ARACBL-03-122244=2,set_qty:ALFBTC-013-320100=10]` | `review` | None | safe miss | known — needs per-item intents in the contract (one intent per message); review by design |
| co-swap-colour | corrections | me equivoque, era el blanco no el transparente 🙈 | `apply:Q-001[add:ARACBL-03-122244=4,remove:ARACTR-03-122244]` | `review` | None | safe miss | known — needs a swap op (remove X + add Y) in the contract; review by design |
| co-swap-width | corrections | ay perdon el vinil mate era de 1.37 no de 1.52 | `apply:Q-001[add:AVBLMT-1A-137050=3,remove:AVBLMT-1A-152050]` | `review` | None | safe miss | known — needs a swap op in the contract; review by design |
| pr-quita-vinil | partial_remove | quita el vinil porfa | `apply:Q-001[remove:AVMICS-1A-137050]` | `review` | llm | safe miss | known — the LLM returned remove_item with no items for 'el vinil' → review `unknown_product`; needs a better prompt/example for single-line removals |
| pr-sacame-tintas | partial_remove | sacame las tintas, ya tenemos | `apply:Q-001[remove:ATECYN-1L-001000,remove:ATEMGN-1L-001000]` | `review` | llm | safe miss | known — LLM returned remove_item with no items; even with items, removing a whole family that covers several lines needs router support |
| oc-question-link | out_of_catalog | y acrilico dorado manejan? para ver si lo sumo a la Q-001 | `apply:Q-001[]` | `review` | None | safe miss | known — the LLM's reading was refused by the Guard (question + 'lo sumo'); needs the LLM-classified `mood` field to answer it as a query |
| qn-entrega | questions_noop | para cuando estaria la entrega? | `noop` | `review` | llm | safe miss | known — item-less query with no quote id: the router finds no quote by content → review `ambiguous_quote`; needs router: an item-less query is a no-op |
| qn-factura | questions_noop | me pueden facturar? necesito factura con mis datos fiscales | `noop` | `review` | None | safe miss | known — 'necesito factura' contains an order verb, so the Guard refuses a no-action reading (review by design: an order is never a silent no-op) |
| qn-price-en-vez-de | questions_noop | cuanto me sale si llevo 10 lonas frontlit en vez de 20? | `apply:Q-001[]` | `review` | None | safe miss | known — the Guard refuses any mutating reading of a price question; expected link-only answer needs the `mood` field (query) |
| rf-history-answer | references | 5 | `apply:Q-001[add:ALMCLC-0909-320100=5]` | `review` | llm | safe miss | known — the LLM read the bare '5' as update_qty of mesh (not in Q-001) → review; needs history resolution of a bare number answering the rep |
| mq-explicit-add | multi_quote | en la Q-002 agregale 1 tinta negra | `apply:Q-002[add:ATEBKN-1L-001000=1]` | `review` | rules | safe miss | known — needs router: ADD with an explicit quote id ignores the id (uses the chat-linked quote) |
| mq-add-by-content | multi_quote | sumale 2 sintras de 5mm | `apply:Q-002[set_qty:APPVEB-05-122244=12]` | `review` | rules | safe miss | known — needs router: ADD picks the chat-linked quote, not the one matching by content |
| vn-question | voice_note | eh hola si te queria preguntar si ustedes hacen envios a monterrey o hay que pasar a recoger porque la otra vez tardaron bastante y el cliente se enojo un poco | `noop` | `review` | llm | safe miss | known — same as qn-entrega (item-less logistics question → review) |
| ca-by-content | cancel | cancela la cotizacion de las tintas | `apply:Q-002[cancel]` | `review` | None | safe miss | known — needs a cancel resolved by content (rules give up; the LLM's item-less cancel naming 'las tintas' is refused by the Guard) |
| ca-partial | cancel | cancela el microperforado nomas, lo demas sigue | `apply:Q-001[remove:AVMICS-1A-137050]` | `review` | None | safe miss | known — needs cancel + product mapped to a line removal; review by design |

## Mode `llm` — 24 / 123 failing

wrong mutation: 1, extra op, no state change: 1, out-of-catalog misassigned: 0, silent miss: 1, safe miss: 21

| case | category | text | expected | got | source | class | status |
|---|---|---|---|---|---|---|---|
| cn-lona-250-length-open | catalog_new | cotizame 8 lonas de 2.50 | `review` | `new[ALFBTC-013-250100=8]` | llm | **wrong mutation** | **known — real wrong mutation (LLM-only ablation).** The LLM listed only the 100 m variants for '2.50' (Frontlit, Blackout, Mesh 2.50x100) and dropped Frontlit 2.50x50; the router's family default then picked Frontlit 2.50x100. The cascade is correct here (the rules' attribute filter keeps both Frontlit lengths → review). Needs a deterministic attribute check of LLM candidates (re-expand them with the rules' attribute filter before the default is applied) |
| co-eran-15 | corrections | perdon, eran 15 no 12 | `apply:Q-001[set_qty:APPVEB-05-122244=15]` | `apply:Q-001[set_qty:APPVEB-05-122244=15,set_qty:ARACBL-03-122244=2]` | llm | extra op, no state change | known — LLM resolved the elliptic correction from history and also restated the other line (`set_qty:ARACBL=2`, already 2): final state is the expected one, no event for the extra op. Needs nothing for correctness; an exact-ops contract would need the LLM to emit only the changed line |
| rf-vez-pasada | references | lo mismo que la vez pasada porfa | `review` | `noop` | llm | silent miss | **known — silent miss.** The LLM read 'lo mismo que la vez pasada' as `none`; the Guard checks temporal references only on mutating intents and there is no order verb, so it became a no-op instead of review. (Passed in the cascade run: the LLM answered differently there.) Needs the temporal check on non-mutating intents too, or the `mood` field |
| event2 | legacy | Buen dia, soy Mario de compras de ACME. Alice me pasó con ustedes, me confirmas qué lleva la cotización de las lonas? | `apply:Q-001[]` | `review` | llm | safe miss | known — the LLM returned the query without the product it asks about, so no quote matches by content → review `ambiguous_quote` (the rules answer it in the cascade); needs the prompt to list products in queries |
| cn-lona-220-default | catalog_new | cotizame 8 rollos de lona 2.20 | `new[ALFBTC-013-220100=8]` | `review` | llm | safe miss | known — the LLM flagged 'lona 2.20' as not in the catalog → review (the rules answer it in the cascade); needs a better size check in the prompt |
| ts-sintras-plis | typos_slang | las sintras q sean 12 plis | `apply:Q-001[set_qty:APPVEB-03-122244=12]` | `review` | llm | safe miss | known — the LLM read 'q sean 12' as add_items → no safe apply → review (the rules answer it in the cascade) |
| uq-litros | units_quantities | tinta cian 4 litros porfa | `new[ATECYN-1L-001000=4]` | `review` | llm | safe miss | known — the LLM flagged '4 litros' of tinta cian as not in the catalog (it sells 1 L bottles) → review; needs litros↔1 L in the prompt or rules |
| mi-two-intents | multi_item | agrega 2 acrilicos blancos de 3mm y que las lonas frontlit sean 10 | `apply:Q-001[add:ARACBL-03-122244=2,set_qty:ALFBTC-013-320100=10]` | `review` | None | safe miss | known — needs per-item intents in the contract (one intent per message); review by design |
| co-swap-colour | corrections | me equivoque, era el blanco no el transparente 🙈 | `apply:Q-001[add:ARACBL-03-122244=4,remove:ARACTR-03-122244]` | `review` | None | safe miss | known — needs a swap op (remove X + add Y) in the contract; review by design |
| co-swap-width | corrections | ay perdon el vinil mate era de 1.37 no de 1.52 | `apply:Q-001[add:AVBLMT-1A-137050=3,remove:AVBLMT-1A-152050]` | `review` | None | safe miss | known — needs a swap op in the contract; review by design |
| pr-quita-vinil | partial_remove | quita el vinil porfa | `apply:Q-001[remove:AVMICS-1A-137050]` | `review` | llm | safe miss | known — the LLM returned remove_item with no items for 'el vinil' → review `unknown_product`; needs a better prompt/example for single-line removals |
| pr-sacame-tintas | partial_remove | sacame las tintas, ya tenemos | `apply:Q-001[remove:ATECYN-1L-001000,remove:ATEMGN-1L-001000]` | `review` | llm | safe miss | known — LLM returned remove_item with no items; even with items, removing a whole family that covers several lines needs router support |
| oc-question-link | out_of_catalog | y acrilico dorado manejan? para ver si lo sumo a la Q-001 | `apply:Q-001[]` | `review` | None | safe miss | known — the LLM's reading was refused by the Guard (question + 'lo sumo'); needs the LLM-classified `mood` field to answer it as a query |
| qn-entrega | questions_noop | para cuando estaria la entrega? | `noop` | `review` | llm | safe miss | known — item-less query with no quote id: the router finds no quote by content → review `ambiguous_quote`; needs router: an item-less query is a no-op |
| qn-factura | questions_noop | me pueden facturar? necesito factura con mis datos fiscales | `noop` | `review` | None | safe miss | known — 'necesito factura' contains an order verb, so the Guard refuses a no-action reading (review by design: an order is never a silent no-op) |
| qn-price-en-vez-de | questions_noop | cuanto me sale si llevo 10 lonas frontlit en vez de 20? | `apply:Q-001[]` | `review` | None | safe miss | known — the Guard refuses any mutating reading of a price question; expected link-only answer needs the `mood` field (query) |
| rf-history-answer | references | 5 | `apply:Q-001[add:ALMCLC-0909-320100=5]` | `review` | llm | safe miss | known — needs history resolution of a bare number answering the rep |
| mq-explicit-add | multi_quote | en la Q-002 agregale 1 tinta negra | `apply:Q-002[add:ATEBKN-1L-001000=1]` | `review` | llm | safe miss | known — needs router: ADD with an explicit quote id ignores the id (uses the chat-linked quote) |
| mq-three-tintas | multi_quote | las tintas que sean 6 | `apply:Q-003[set_qty:ATEMGN-1L-001000=6]` | `review` | llm | safe miss | known — the LLM read 'que sean 6' as add_items; the chat is linked to 3 quotes → review `ambiguous_quote` (the rules answer it in the cascade) |
| mq-cross-conv-query | multi_quote | hola, soy Lucia de diseño, me pasas que lleva la cotizacion del sintra? | `apply:Q-002[]` | `review` | llm | safe miss | known — the LLM dropped 'del sintra' from the query, so no quote matches by content → review (the rules answer it in the cascade) |
| mq-add-by-content | multi_quote | sumale 2 sintras de 5mm | `apply:Q-002[set_qty:APPVEB-05-122244=12]` | `review` | llm | safe miss | known — needs router: ADD picks the chat-linked quote, not the one matching by content |
| vn-question | voice_note | eh hola si te queria preguntar si ustedes hacen envios a monterrey o hay que pasar a recoger porque la otra vez tardaron bastante y el cliente se enojo un poco | `noop` | `review` | llm | safe miss | known — same as qn-entrega (item-less logistics question → review) |
| ca-by-content | cancel | cancela la cotizacion de las tintas | `apply:Q-002[cancel]` | `review` | None | safe miss | known — needs a cancel resolved by content (rules give up; the LLM's item-less cancel naming 'las tintas' is refused by the Guard) |
| ca-partial | cancel | cancela el microperforado nomas, lo demas sigue | `apply:Q-001[remove:AVMICS-1A-137050]` | `review` | None | safe miss | known — needs cancel + product mapped to a line removal; review by design |

Out-of-catalog cases routed correctly, but a catalog SKU was listed for the unknown product (routing was saved by `in_catalog`/the router):

- oc-vinil-mate-127: extra SKUs AVBLMT-1A-106050, AVBLMT-1A-137050, AVBLMT-1A-152050


## Round-2 history: baseline wrong mutations and how each was closed

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
