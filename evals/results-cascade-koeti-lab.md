**Mode `cascade`** on `koeti-lab` (23 golden cases)

| intent acc | SKU-set acc | routing acc (target+ops) | % rules (no LLM) | p50 ms | p95 ms | review rate | wrong apply/new | review instead of apply (safe miss) |
|---|---|---|---|---|---|---|---|---|
| 100% | 91% | 96% | 43% | 3325 | 23884 | 17% | 0 | 1 |

Routing misses:

| case | expected | got | source |
|---|---|---|---|
| id-q1-mesh | apply:Q-001[set_qty:ALMCLC-0909-320100=8] | review | llm |
