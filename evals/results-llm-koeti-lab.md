**Mode `llm`** on `koeti-lab` (23 golden cases)

| intent acc | SKU-set acc | routing acc (target+ops) | % rules (no LLM) | p50 ms | p95 ms | review rate | wrong apply/new | review instead of apply (safe miss) |
|---|---|---|---|---|---|---|---|---|
| 96% | 87% | 91% | 0% | 22513 | 26915 | 22% | 0 | 2 |

Routing misses:

| case | expected | got | source |
|---|---|---|---|
| event2 | apply:Q-001[] | review | llm |
| id-q1-mesh | apply:Q-001[set_qty:ALMCLC-0909-320100=8] | review | llm |
