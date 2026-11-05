**Mode `rules`** on `koeti-lab` (23 golden cases)

| intent acc | SKU-set acc | routing acc (target+ops) | % rules (no LLM) | p50 ms | p95 ms | review rate | wrong apply/new | review instead of apply (safe miss) |
|---|---|---|---|---|---|---|---|---|
| 43% | 57% | 48% | 43% | 0 | 0 | 65% | 0 | 12 |

Routing misses:

| case | expected | got | source |
|---|---|---|---|
| para-frontlit | apply:Q-001[set_qty:ALFBTC-013-320100=15] | review | None |
| para-suma-mesh | apply:Q-001[set_qty:ALMCLC-0909-320100=6] | review | None |
| para-ya-no-micro | apply:Q-001[remove:AVMICS-1A-137050] | review | None |
| typo-acrilcos | new[ARACBL-03-122244=3] | review | None |
| typo-lonsa | new[ALFBTC-013-320100=6] | review | None |
| typo-microperforadso | apply:Q-001[set_qty:AVMICS-1A-137050=12] | review | None |
| words-diez-mesh | new[ALMCLC-0909-320100=10] | review | None |
| words-quince-frontlit | apply:Q-001[set_qty:ALFBTC-013-320100=15] | review | None |
| words-dos-acrilicos | apply:Q-001[add:ARACBL-03-122244=2] | review | None |
| trap-gracias | noop | review | None |
| trap-ok-atento | noop | review | None |
| id-q1-mesh | apply:Q-001[set_qty:ALMCLC-0909-320100=8] | review | None |
