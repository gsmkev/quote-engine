**Mode `llm`** on `koeti-lab` (23 golden cases)

| intent acc | SKU-set acc | qty acc | routing acc | % rules (no LLM) | p50 ms | p95 ms | review rate | wrong apply/new | review instead of apply (safe miss) |
|---|---|---|---|---|---|---|---|---|---|
| 96% | 87% | 96% | 96% | 0% | 22620 | 27597 | 17% | 0 | 1 |

Routing misses:

| case | expected | got | source |
|---|---|---|---|
| event2 | apply:Q-001 | review | llm |
