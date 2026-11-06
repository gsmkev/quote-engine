**Mode `rules`** on `koeti-lab` (123 golden cases)

| intent acc | SKU-set acc | routing acc (target+ops) | % rules (no LLM) | p50 ms | p95 ms | review rate | wrong apply/new | review instead of apply (safe miss) |
|---|---|---|---|---|---|---|---|---|
| 37% | 63% | 62% | 41% | 0 | 0 | 71% | 0 | 47 |

| category | n | routing exact | wrong mutations | safe misses |
|---|---|---|---|---|
| legacy | 23 | 74% | 0 | 6 |
| catalog_new | 9 | 100% | 0 | 0 |
| typos_slang | 8 | 75% | 0 | 2 |
| units_quantities | 8 | 12% | 0 | 7 |
| multi_item | 7 | 71% | 0 | 2 |
| corrections | 7 | 29% | 0 | 5 |
| partial_remove | 6 | 33% | 0 | 4 |
| out_of_catalog | 16 | 88% | 0 | 2 |
| questions_noop | 8 | 12% | 0 | 7 |
| references | 6 | 67% | 0 | 2 |
| multi_quote | 7 | 71% | 0 | 2 |
| voice_note | 6 | 17% | 0 | 5 |
| rep_outbound | 5 | 100% | 0 | 0 |
| cancel | 7 | 57% | 0 | 3 |

Routing misses:

| case | expected | got | source |
|---|---|---|---|
| para-ya-no-micro | apply:Q-001[remove:AVMICS-1A-137050] | review | None |
| typo-microperforadso | apply:Q-001[set_qty:AVMICS-1A-137050=12] | review | None |
| words-quince-frontlit | apply:Q-001[set_qty:ALFBTC-013-320100=15] | review | None |
| trap-gracias | noop | review | None |
| trap-ok-atento | noop | review | None |
| id-q1-mesh | apply:Q-001[set_qty:ALMCLC-0909-320100=8] | review | None |
| ts-acrilco-negro | new[ARACNG-03-122244=10] | review | None |
| ts-one-way | new[AVMICS-1A-152050=2] | review | None |
| uq-un-par | new[ALAMMT-01-137050=2] | review | None |
| uq-media-docena | new[ATEBKN-1L-001000=6] | review | None |
| uq-docena | new[APPVEB-03-122244=12] | review | None |
| uq-x2 | new[ARACTR-05-122244=2] | review | None |
| uq-2u | apply:Q-001[add:ALBKOC-013-250100=2] | review | None |
| uq-veinticinco | new[ALFBTC-013-160100=25] | review | None |
| uq-litros | new[ATECYN-1L-001000=4] | review | None |
| mi-two-intents | apply:Q-001[add:ARACBL-03-122244=2,set_qty:ALFBTC-013-320100=10] | review | None |
| mi-bullet-list | new[ALAMMT-01-137050=1,ALFBTC-013-320100=3,ALMCLC-0909-320100=2] | review | None |
| co-eran-15 | apply:Q-001[set_qty:APPVEB-05-122244=15] | review | None |
| co-swap-colour | apply:Q-001[add:ARACBL-03-122244=4,remove:ARACTR-03-122244] | review | None |
| co-no-eran-3 | apply:Q-001[set_qty:ARACNG-03-122244=5] | review | None |
| co-corrijo-blackout | apply:Q-001[set_qty:ALBKOC-013-320100=8] | review | None |
| co-swap-width | apply:Q-001[add:AVBLMT-1A-137050=3,remove:AVBLMT-1A-152050] | review | None |
| pr-quita-vinil | apply:Q-001[remove:AVMICS-1A-137050] | review | None |
| pr-ya-no-sintra | apply:Q-001[remove:APPVEB-05-122244] | review | None |
| pr-sacame-tintas | apply:Q-001[remove:ATECYN-1L-001000,remove:ATEMGN-1L-001000] | review | None |
| pr-quitale-2 | apply:Q-001[set_qty:ALFBTC-013-320100=18] | review | None |
| oc-question-noop | noop | review | None |
| oc-question-link | apply:Q-001[] | review | None |
| qn-hola | noop | review | None |
| qn-stock | noop | review | None |
| qn-entrega | noop | review | None |
| qn-total-q001 | apply:Q-001[] | review | None |
| qn-factura | noop | review | None |
| qn-gracias-jefe | noop | review | None |
| qn-price-en-vez-de | apply:Q-001[] | review | None |
| rf-history-esas | apply:Q-001[set_qty:ATECYN-1L-001000=12] | review | None |
| rf-history-answer | apply:Q-001[add:ALMCLC-0909-320100=5] | review | None |
| mq-explicit-add | apply:Q-002[add:ATEBKN-1L-001000=1] | review | rules |
| mq-add-by-content | apply:Q-002[set_qty:APPVEB-05-122244=12] | review | rules |
| vn-new-order | new[ALFBTC-013-320100=15,AVMICS-1A-137050=4] | review | None |
| vn-update | apply:Q-001[set_qty:ALFBTC-013-320100=15] | review | None |
| vn-question | noop | review | None |
| vn-cancel | apply:Q-001[cancel] | review | None |
| vn-add | apply:Q-001[add:ATEBKN-1L-001000=2,add:ATEYLN-1L-001000=2] | review | None |
| ca-by-content | apply:Q-002[cancel] | review | None |
| ca-partial | apply:Q-001[remove:AVMICS-1A-137050] | review | None |
| ca-negated | noop | review | None |
