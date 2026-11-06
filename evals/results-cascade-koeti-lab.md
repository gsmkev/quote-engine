**Mode `cascade`** on `koeti-lab` (123 golden cases)

| intent acc | SKU-set acc | routing acc (target+ops) | % rules (no LLM) | p50 ms | p95 ms | review rate | wrong apply/new | review instead of apply (safe miss) |
|---|---|---|---|---|---|---|---|---|
| 71% | 81% | 69% | 33% | 17015 | 129287 | 45% | 10 | 25 |

| category | n | routing exact | wrong mutations | safe misses |
|---|---|---|---|---|
| legacy | 23 | 74% | 0 | 6 |
| catalog_new | 9 | 100% | 0 | 0 |
| typos_slang | 8 | 62% | 1 | 0 |
| units_quantities | 8 | 62% | 1 | 2 |
| multi_item | 7 | 71% | 1 | 1 |
| corrections | 7 | 57% | 1 | 2 |
| partial_remove | 6 | 33% | 1 | 3 |
| out_of_catalog | 16 | 88% | 0 | 1 |
| questions_noop | 8 | 38% | 1 | 4 |
| references | 6 | 50% | 2 | 1 |
| multi_quote | 7 | 57% | 0 | 3 |
| voice_note | 6 | 83% | 0 | 1 |
| rep_outbound | 5 | 100% | 0 | 0 |
| cancel | 7 | 57% | 2 | 1 |

Routing misses:

| case | expected | got | source |
|---|---|---|---|
| para-agrega-acrilicos | apply:Q-001[add:ARACBL-03-122244=3] | review | rules |
| para-new-mesh | new[ALMCLC-0909-320100=10] | review | rules |
| typo-acrilcos | new[ARACBL-03-122244=3] | review | llm |
| typo-lonsa | new[ALFBTC-013-320100=6] | review | llm |
| words-diez-mesh | new[ALMCLC-0909-320100=10] | review | llm |
| words-dos-acrilicos | apply:Q-001[add:ARACBL-03-122244=2] | review | llm |
| ts-trovicel | new[APPVEB-05-122244=4] | noop | llm |
| ts-one-way | new[AVMICS-1A-152050=2] | new[AVBLMT-1A-152050=2] | llm |
| ts-sintras-plis | apply:Q-001[set_qty:APPVEB-03-122244=12] | noop | llm |
| uq-docena | new[APPVEB-03-122244=12] | review | llm |
| uq-litros | new[ATECYN-1L-001000=4] | review | llm |
| uq-galones | review | new[ATEMGN-1L-001000=2] | llm |
| mi-add-two-new | apply:Q-001[add:ALAMBR-01-137050=2,add:ATEYLN-1L-001000=1] | review | rules |
| mi-two-intents | apply:Q-001[add:ARACBL-03-122244=2,set_qty:ALFBTC-013-320100=10] | apply:Q-001[add:ARACBL-03-122244=2,set_qty:ALFBTC-013-320100=30] | rules |
| co-eran-15 | apply:Q-001[set_qty:APPVEB-05-122244=15] | review | llm |
| co-swap-colour | apply:Q-001[add:ARACBL-03-122244=4,remove:ARACTR-03-122244] | apply:Q-001[set_qty:ARACTR-03-122244=4] | llm |
| co-swap-width | apply:Q-001[add:AVBLMT-1A-137050=3,remove:AVBLMT-1A-152050] | review | llm |
| pr-quita-vinil | apply:Q-001[remove:AVMICS-1A-137050] | review | llm |
| pr-ya-no-sintra | apply:Q-001[remove:APPVEB-05-122244] | review | llm |
| pr-sacame-tintas | apply:Q-001[remove:ATECYN-1L-001000,remove:ATEMGN-1L-001000] | review | llm |
| pr-quitale-2 | apply:Q-001[set_qty:ALFBTC-013-320100=18] | apply:Q-001[remove:ALFBTC-013-320100] | llm |
| oc-papel-foto | review | noop | llm |
| oc-question-noop | noop | review | llm |
| qn-precio | noop | review | rules |
| qn-stock | noop | review | llm |
| qn-entrega | noop | review | llm |
| qn-factura | noop | review | llm |
| qn-price-en-vez-de | apply:Q-001[] | apply:Q-001[set_qty:ALFBTC-013-320100=10] | llm |
| rf-la-de-ayer | review | apply:Q-001[set_qty:ALMCLC-0909-320100=10] | llm |
| rf-history-esas | apply:Q-001[set_qty:ATECYN-1L-001000=12] | apply:Q-001[set_qty:ATECYN-1L-001000=2] | llm |
| rf-history-answer | apply:Q-001[add:ALMCLC-0909-320100=5] | review | llm |
| mq-explicit-add | apply:Q-002[add:ATEBKN-1L-001000=1] | review | rules |
| mq-three-tintas | apply:Q-003[set_qty:ATEMGN-1L-001000=6] | review | llm |
| mq-add-by-content | apply:Q-002[set_qty:APPVEB-05-122244=12] | review | llm |
| vn-question | noop | review | llm |
| ca-by-content | apply:Q-002[cancel] | review | llm |
| ca-partial | apply:Q-001[remove:AVMICS-1A-137050] | apply:Q-001[cancel] | llm |
| ca-unknown-product | review | apply:Q-001[cancel] | rules |
