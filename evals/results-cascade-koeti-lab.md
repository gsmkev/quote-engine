**Mode `cascade`** on `koeti-lab` (123 golden cases)

| intent acc | SKU-set acc | routing acc (target+ops) | % rules (no LLM) | p50 ms | p95 ms | review rate | wrong apply/new | review instead of apply (safe miss) |
|---|---|---|---|---|---|---|---|---|
| 72% | 85% | 86% | 41% | 7265 | 152808 | 46% | 1 | 16 |

| category | n | routing exact | wrong mutations | safe misses |
|---|---|---|---|---|
| legacy | 23 | 100% | 0 | 0 |
| catalog_new | 9 | 100% | 0 | 0 |
| typos_slang | 8 | 100% | 0 | 0 |
| units_quantities | 8 | 88% | 0 | 1 |
| multi_item | 7 | 86% | 0 | 1 |
| corrections | 7 | 57% | 1 | 2 |
| partial_remove | 6 | 67% | 0 | 2 |
| out_of_catalog | 16 | 94% | 0 | 1 |
| questions_noop | 8 | 62% | 0 | 3 |
| references | 6 | 83% | 0 | 1 |
| multi_quote | 7 | 71% | 0 | 2 |
| voice_note | 6 | 83% | 0 | 1 |
| rep_outbound | 5 | 100% | 0 | 0 |
| cancel | 7 | 71% | 0 | 2 |

Routing misses:

| case | expected | got | source |
|---|---|---|---|
| uq-litros | new[ATECYN-1L-001000=4] | review | llm |
| mi-two-intents | apply:Q-001[add:ARACBL-03-122244=2,set_qty:ALFBTC-013-320100=10] | review | None |
| co-eran-15 | apply:Q-001[set_qty:APPVEB-05-122244=15] | apply:Q-001[set_qty:APPVEB-05-122244=15,set_qty:ARACBL-03-122244=2] | llm |
| co-swap-colour | apply:Q-001[add:ARACBL-03-122244=4,remove:ARACTR-03-122244] | review | None |
| co-swap-width | apply:Q-001[add:AVBLMT-1A-137050=3,remove:AVBLMT-1A-152050] | review | None |
| pr-quita-vinil | apply:Q-001[remove:AVMICS-1A-137050] | review | llm |
| pr-sacame-tintas | apply:Q-001[remove:ATECYN-1L-001000,remove:ATEMGN-1L-001000] | review | llm |
| oc-question-link | apply:Q-001[] | review | None |
| qn-entrega | noop | review | llm |
| qn-factura | noop | review | None |
| qn-price-en-vez-de | apply:Q-001[] | review | None |
| rf-history-answer | apply:Q-001[add:ALMCLC-0909-320100=5] | review | llm |
| mq-explicit-add | apply:Q-002[add:ATEBKN-1L-001000=1] | review | rules |
| mq-add-by-content | apply:Q-002[set_qty:APPVEB-05-122244=12] | review | rules |
| vn-question | noop | review | llm |
| ca-by-content | apply:Q-002[cancel] | review | None |
| ca-partial | apply:Q-001[remove:AVMICS-1A-137050] | review | None |
