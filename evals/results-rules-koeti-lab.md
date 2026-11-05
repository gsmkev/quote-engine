**Mode `rules`** on `koeti-lab` (23 golden cases)

| intent acc | SKU-set acc | qty acc | routing acc | % rules (no LLM) | p50 ms | p95 ms | review rate | wrong apply/new | review instead of apply (safe miss) |
|---|---|---|---|---|---|---|---|---|---|
| 43% | 57% | 61% | 48% | 43% | 0 | 0 | 65% | 0 | 12 |

Routing misses:

| case | expected | got | source |
|---|---|---|---|
| para-frontlit | apply:Q-001 | review | None |
| para-suma-mesh | apply:Q-001 | review | None |
| para-ya-no-micro | apply:Q-001 | review | None |
| typo-acrilcos | new | review | None |
| typo-lonsa | new | review | None |
| typo-microperforadso | apply:Q-001 | review | None |
| words-diez-mesh | new | review | None |
| words-quince-frontlit | apply:Q-001 | review | None |
| words-dos-acrilicos | apply:Q-001 | review | None |
| trap-gracias | noop | review | None |
| trap-ok-atento | noop | review | None |
| id-q1-mesh | apply:Q-001 | review | None |
