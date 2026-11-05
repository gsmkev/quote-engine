# LLD — Quote & State Engine

Low-level design. Read the [HLD](HLD.md) first. This document fixes schemas, contracts, algorithms and error handling, and describes the code as it is in this repository.

## 1. Repository layout

```
.
├── pyproject.toml            # uv; ruff config; pytest markers (llm, integration), addopts -m "not llm"
├── uv.lock
├── justfile                  # up, up-gpu, down, demo, demo-replay, logs, lint, fmt, typecheck, test, test-llm, eval, record-replay
├── docker-compose.yml        # postgres, api, worker + top-level `models: llm` (Docker Model Runner)
├── compose.replay.yaml       # override: no model, EXTRACTOR_MODE=replay
├── Dockerfile                # one image; api runs uvicorn, worker runs python -m quote_engine.worker
├── alembic/versions/0001_init.py
├── src/quote_engine/
│   ├── config.py             # pydantic-settings
│   ├── seed.py               # idempotent catalog seed (run by the api container)
│   ├── worker.py             # worker loop entrypoint
│   ├── domain/
│   │   ├── catalog.py        # Catalog, CatalogItem
│   │   ├── interpretation.py # Intent, MessageInterpretation, ConversationExtraction, make_llm_models, validate_skus
│   │   ├── quote.py          # Quote aggregate, ops, events, DomainError
│   │   └── router.py         # route() — pure
│   ├── application/
│   │   ├── ports.py          # Extractor protocol, MessageCtx, ConversationCtx
│   │   ├── ingest.py         # ingest_message / ingest_conversation
│   │   ├── process.py        # process_next() use case
│   │   └── reviews.py        # resolve_review use case
│   └── adapters/
│       ├── db/               # models.py, uow.py, repos.py, seed.py
│       ├── extractors/       # rules.py, llm.py, cascade.py, replay.py, factory.py
│       └── api/              # app.py, routes.py, schemas.py
├── fixtures/                 # catalog.json, challenge/*.json, llm_replay/<sha256>.json
├── evals/                    # golden.jsonl, run_evals.py, results-<mode>-<host>.{md,json}
├── scripts/                  # demo.sh, record_replay.py
├── tests/                    # unit/, integration/ (testcontainers), llm/
└── docs/                     # HLD.md, LLD.md
```

## 2. Database schema (Alembic migration 0001)

```sql
CREATE TABLE customers (id text PRIMARY KEY);
CREATE TABLE conversations (
  id text PRIMARY KEY,
  customer_id text NOT NULL REFERENCES customers(id)
);
CREATE TABLE catalog (
  sku text PRIMARY KEY,
  description text NOT NULL,
  aliases text[] NOT NULL DEFAULT '{}'
);

CREATE SEQUENCE quote_seq;
CREATE TABLE quotes (
  id text PRIMARY KEY,                         -- f"Q-{nextval('quote_seq'):03d}", built in Python
  customer_id text NOT NULL REFERENCES customers(id),
  status text NOT NULL CHECK (status IN ('draft','cancelled')),
  version int NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON quotes (customer_id, status);

CREATE TABLE quote_lines (
  quote_id text REFERENCES quotes(id),
  sku text NOT NULL REFERENCES catalog(sku),   -- 3rd guard against foreign SKUs
  qty int NOT NULL CHECK (qty > 0),
  position int NOT NULL,                       -- insertion order for output
  PRIMARY KEY (quote_id, sku)
);

CREATE TABLE quote_conversations (
  quote_id text REFERENCES quotes(id),
  conversation_id text REFERENCES conversations(id),
  linked_by_message_id text NOT NULL,
  linked_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (quote_id, conversation_id)
);

CREATE TABLE messages (
  message_id text PRIMARY KEY,
  conversation_id text NOT NULL REFERENCES conversations(id),
  customer_id text NOT NULL,
  direction text NOT NULL CHECK (direction IN ('inbound','outbound')),
  ts timestamptz NOT NULL,
  text text NOT NULL
);
CREATE INDEX ON messages (conversation_id, ts);

CREATE TABLE inbox (
  seq bigserial PRIMARY KEY,
  dedupe_key text NOT NULL UNIQUE,
  kind text NOT NULL CHECK (kind IN ('conversation','message')),
  customer_id text NOT NULL,
  payload jsonb NOT NULL,
  payload_hash text NOT NULL,
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','processed','needs_review','failed')),
  attempts int NOT NULL DEFAULT 0,
  decision jsonb,
  error text,
  received_at timestamptz NOT NULL DEFAULT now(),
  processed_at timestamptz
);
CREATE INDEX inbox_pending ON inbox (customer_id, seq) WHERE status = 'pending';

CREATE TABLE quote_events (
  id bigserial PRIMARY KEY,
  quote_id text NOT NULL REFERENCES quotes(id),
  message_id text,
  review_id bigint,
  type text NOT NULL,
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON quote_events (quote_id, id);

CREATE TABLE review_items (
  id bigserial PRIMARY KEY,
  inbox_seq bigint NOT NULL REFERENCES inbox(seq),
  customer_id text NOT NULL,
  reason text NOT NULL CHECK (reason IN ('ambiguous_quote','ambiguous_line','extraction_failed','unknown_product')),
  candidate_quote_ids text[] NOT NULL,
  interpretation jsonb,
  proposed jsonb,                              -- reserved; the router does not fill it yet
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved','dismissed')),
  resolution jsonb,
  resolved_at timestamptz
);
```

* There is no `processing` state. A row is claimed and handled inside **one transaction**, so it is never visible as in progress.
* If the process crashes, the transaction rolls back and the row stays `pending`: at-least-once, and safe because the state change commits with the status change.
* A failed attempt is recorded in the **same** transaction, after rolling back a savepoint around the work (see §8). At `MAX_ATTEMPTS = 3`, or immediately on a `DomainError`, the row becomes `failed`.
* Phase 1 history messages have no id; they are stored as `f"{conversation_id}:{sha256(ts|direction|text)[:12]}"`.

## 3. Domain contracts (Pydantic v2, `domain/`)

```python
# catalog.py
class CatalogItem(BaseModel): sku: str; description: str; aliases: list[str]
class Catalog(BaseModel):            # frozen; loaded from fixtures/catalog.json (worker) or the DB (api inline worker)
    items: dict[str, CatalogItem]
    skus: tuple[str, ...]            # property

# interpretation.py
class Intent(StrEnum):
    CREATE_QUOTE="create_quote"; ADD_ITEMS="add_items"; UPDATE_QTY="update_qty"
    REMOVE_ITEM="remove_item"; QUERY="query"; CANCEL="cancel"; NONE="none"

class ItemMention(BaseModel):
    mention: str
    sku_candidates: list[str] = Field(min_length=1)
    qty: PositiveInt | None = None
    previous_qty: PositiveInt | None = None

class MessageInterpretation(BaseModel):
    intent: Intent
    separate: bool = False
    items: list[ItemMention] = []
    explicit_quote_ids: list[str] = []
    source: Literal["rules", "llm", "replay"]

class ExtractedLine(BaseModel):
    sku: str; qty: PositiveInt; evidence: str
class ConversationExtraction(BaseModel):
    items: list[ExtractedLine]
```

* `make_llm_models(catalog)` builds the LLM-facing subclasses where `sku_candidates: list[Literal[*skus]]` and `sku: Literal[*skus]`. The JSON Schema sent to the model therefore carries `enum: [4 SKUs]` (constrained decoding).
* `validate_skus(interp, catalog)` re-checks every candidate in Python; `process_next` turns a foreign SKU into `None` (→ review). The `quote_lines.sku` FK is the third guard.

## 4. Quote aggregate (`domain/quote.py`)

```python
Op = Cancel | SetQty(sku, qty) | AddLine(sku, qty) | RemoveLine(sku) | LinkConversation(conversation_id)

@dataclass
class Quote:  # no ORM
    id, customer_id, status: "draft" | "cancelled", version, lines: dict[str, Line(qty, position)],
    conversations: set[str], pending_events: list[Event]

    @classmethod create(id, customer_id, lines: list[(sku, qty)], conversation_id, cause) -> Quote
        # QuoteCreated + LineAdded* + ConversationLinked, version stays 1
    def apply(ops: list[Op], cause: Cause) -> None
        # plans the whole batch on copies, then commits it: all-or-nothing
```

**Cause:** `Cause(message_id: str | None, review_id: int | None = None)`.

**Invariants** (a violation raises `DomainError` and nothing in the batch is applied):

* The quote is `draft`; a cancelled quote cannot be mutated (also later in the same batch).
* `SetQty` / `RemoveLine`: the SKU exists in `lines`.
* `AddLine`: the SKU does not exist yet (the router turns "add" to an existing SKU into `SetQty`).
* `qty > 0`.
* `SetQty` to the same qty is a **no-op with no event**, which keeps it idempotent.
* `LinkConversation` on a chat that is already linked is a no-op with no event.

`version += 1` once per `apply` batch that produced at least one event.

**Events**, as `type` and `payload`: `QuoteCreated{customer_id}`, `LineAdded{sku, qty}`, `LineQtyChanged{sku, from, to}`, `LineRemoved{sku, qty}`, `ConversationLinked{conversation_id}`, `QuoteCancelled{}`.

## 5. Router (`domain/router.py`) — pure

```python
@dataclass(frozen=True)
class QuoteView: id: str; lines: dict[str, int]; conversations: frozenset[str]

Decision = Apply(quote_id, ops) | NewQuote(lines: list[(sku, qty)]) \
         | Review(reason, candidates: list[str], proposed: Apply | None) | NoOp

def score(interp, q) -> int:
    s = 10 if q.id in interp.explicit_quote_ids else 0
    for it in interp.items:
        hit = set(it.sku_candidates) & q.lines.keys()
        if hit:
            s += 3
            if it.previous_qty and any(q.lines[k] == it.previous_qty for k in hit):
                s += 2
    return s

def _pick(interp, open_quotes):    # unique positive maximum, else None
def _resolve_line(it, q):          # candidates present in q, narrowed by previous_qty; exactly one or None
def _new_lines(items):             # every item has exactly 1 candidate and a qty, else None

def route(interp, conversation_id, open_quotes) -> Decision:
    link = LinkConversation(conversation_id)
    NONE                                         -> NoOp
    CREATE_QUOTE, or ADD_ITEMS with separate or no open quotes
                                                 -> NewQuote(_new_lines) | Review(unknown_product, [])
    ADD_ITEMS                                    -> exactly one open quote linked to this chat, else Review(ambiguous_quote, all)
                                                    ops = [link] + (SetQty(sku, existing+qty) if sku in quote else AddLine(sku, qty))
                                                    _new_lines None -> Review(unknown_product, [])
    CANCEL without items and without quote ids   -> exactly one open quote: Apply [link, Cancel]
                                                    else Review(ambiguous_quote, all)
    UPDATE_QTY / REMOVE_ITEM without items       -> Review(unknown_product, [picked] or all)
    otherwise (UPDATE_QTY, REMOVE_ITEM, QUERY, CANCEL with content):
        q = _pick(...)  or Review(ambiguous_quote, all)
        ops = [link]
        UPDATE_QTY / REMOVE_ITEM: per item _resolve_line or Review(ambiguous_line, [q]);
                                  update item without qty -> Review(unknown_product, [q])
                                  -> SetQty / RemoveLine
        CANCEL: + Cancel()
        QUERY:  just the link
        -> Apply(q.id, ops)
```

* Open quotes are the customer's `draft` quotes, ordered by id. Cancelled quotes are never candidates.
* The chat is used only in the `ADD_ITEMS` (no "aparte") branch. Everything else routes on content.
* `Review.proposed` is part of the contract and stored, but the router currently always passes `None`; reviewers get the candidates (with lines and version) instead.

**Router unit tests** (`tests/unit/test_router.py`, abbreviated):

| Open quotes (lines) | Interpretation | Expected |
|---------------------|----------------|----------|
| Q1{FBT:20, MCL:5, MIC:5} | update lonas{FBT,MCL} 15 prev 20 | Apply Q1 [link, SetQty(FBT,15)] |
| Q1                  | update lonas{FBT,MCL} 15, no prev | Review ambiguous_line |
| Q1                  | query lonas, from chat 662 | Apply Q1 [link 662] |
| Q1                  | add separate ACR 2 | NewQuote [(ACR,2)] |
| Q1{FBT} linked 662, Q2{ACR:2} | update ACR 4 from 662 | Apply Q2 [link 662, SetQty(ACR,4)] |
| Q1, Q2              | cancel, no items | Review ambiguous_quote [Q1,Q2] |
| Q1                  | cancel, no items | Apply Q1 [link, Cancel] |
| Q1{FBT}, Q2{FBT}    | update FBT 3     | Review ambiguous_quote (tie) |
| Q1{ACR}, Q2{ACR}    | update "Q-002" ACR 4 | Apply Q2 (explicit +10) |
| Q1, Q2, chat linked to both | add ACR 1 (no separate) | Review ambiguous_quote |
| none                | update ACR 4     | Review ambiguous_quote [] |
| Q1, Q2              | update with no items | Review unknown_product |
| Q1{ACR:3} linked    | add ACR 2 (no separate) | Apply Q1 [link, SetQty(ACR,5)] |
| none                | create lonas 2 (two candidates) | Review unknown_product |

## 6. Extractors (`adapters/extractors/`)

```python
class Extractor(Protocol):
    async def interpret(self, ctx: MessageCtx) -> MessageInterpretation | None
    async def extract_conversation(self, ctx: ConversationCtx) -> ConversationExtraction | None
```

`None` always means "I am not sure"; the caller turns it into a review, never a guess.

**`RuleExtractor`** (`rules.py`):

1. `norm(text)`: lowercase, strip accents (NFKD), `,` → `.` inside numbers, collapse whitespace.
2. **Intent**, first match in priority order:
   * cancel: `cancela*|anula*|ya no (lo )?quiero`;
   * update: `mejor (que )?sean|cambia*|en vez de`;
   * add: `cotiza(me|s|r|nos)|agrega*|suma|tambien|necesito`;
   * query: `que lleva|confirmas|cuanto|?$`.
   No match → `None`.
3. **Give-up guards** (→ `None`, i.e. LLM fallback): a negated cancel (`no (me|lo|la )?cancel*`); any `no N` that is not the previous quantity of a `sean N, no M`.
4. `explicit_quote_ids`: `q-?\d{3}` normalized to `Q-###` (and blanked out so the digits are not read as quantities).
5. **Products:** alias table from `catalog.aliases`, longest match first, word boundaries. A dimension token (`3.20x100`, `3mm`, `1.37`, …) within 25 characters narrows the candidates to SKUs whose description contains it.
6. **Quantities:** `(sean|seria|serian|a) N (, no M)?` binds qty (and previous qty) to the nearest product; `N rollos|piezas|unidades` and `N <product>` / `<product> N` bind qty. A tie in distance, a conflicting second value, or any **unbound number** → `None`.
7. **Coverage:** cancel with product mentions → `None`; no product (other intents) → `None`; a query that carries a qty → `None`; an update/add item with no qty → `None`.
8. `separate = aparte|otra cotizacion|por separado`.

`extract_conversation` always returns `None` (Phase 1 is the model's job).

**`LLMExtractor`** (`llm.py`):

* Client: `instructor.from_openai(AsyncOpenAI(base_url=settings.llm_base_url, api_key="dmr"), mode=instructor.Mode.JSON_SCHEMA)`. `llm_base_url` is Docker Model Runner's OpenAI-compatible base, including `/engines/v1`; Compose injects it.
* Parameters: `temperature=0`, `max_retries=2` (Instructor re-asks on validation errors), `timeout=LLM_TIMEOUT_S` (180).
* Message prompt: system = role, catalog table (`SKU | description`), rules ("only these SKUs; list every plausible SKU for an ambiguous mention; never invent quantities; resolve vague mentions with earlier messages"), one worked example. User = the last `CONTEXT_WINDOW_MESSAGES` (10) messages as `[direction] text`, then `MESSAGE: <text>`.
* Conversation prompt (Phase 1): the full thread; the rep's outbound replies can confirm a variant; only emit items with exactly one confirmed SKU and a customer-stated quantity; skip variants the rep said are unavailable; `evidence` quote per line.
* Any exception (timeout, connection, exhausted retries) → logged `llm_failed` → `None`.

**`CascadeExtractor`** (`cascade.py`): `first.interpret`, and only if that returns `None`, `fallback.interpret`. `extract_conversation` goes straight to the fallback. The interpretation's `source` (`rules` / `llm` / `replay`) is recorded in the inbox trace.

**`ReplayExtractor`** (`replay.py`): reads `fixtures/llm_replay/<sha256(key)>.json`, with key `"msg|" + text` or `"conv|" + "\n".join(f"{dir}:{text}")`. A missing or invalid fixture (e.g. a foreign SKU) is logged and returns `None` → review, not an exception. `scripts/record_replay.py` records the Phase 1 fixture from the real model. Also the test double.

**`EXTRACTOR_MODE`** (`factory.build_extractor`): `cascade` (default: rules → LLM) | `llm` (LLM only; eval ablation) | `rules` (rules only) | `replay` (rules → replay fixtures; no model).

## 7. Ingest (`application/ingest.py`)

```python
async def ingest_message(uow, p: MessageIn) -> Accepted | Duplicate | Conflict:
    h = canonical_hash(p.model_dump(mode="json"))  # sha256 of json.dumps(sort_keys, compact, ensure_ascii=False)
    seq = INSERT INTO inbox(dedupe_key=p.message_id, kind='message', ...) ON CONFLICT (dedupe_key) DO NOTHING RETURNING seq
    if seq: commit; return Accepted(seq)
    existing = SELECT seq, payload_hash FROM inbox WHERE dedupe_key = p.message_id
    return Duplicate(existing.seq) if existing.payload_hash == h else Conflict(existing.seq)
```

* Dedupe is by `message_id`, never by text: two different messages with the same text are both applied.
* **Conversation payload:** `dedupe_key = f"conv:{conversation_id}:{h[:16]}"`, `kind='conversation'`.
* Ingest only writes the inbox; customer/conversation/message upserts happen in the worker.

## 8. Worker (`application/process.py`, `worker.py`)

```sql
-- claim: oldest pending row whose customer has no earlier pending row
SELECT seq, kind, customer_id, payload FROM inbox i
WHERE i.status = 'pending'
  AND NOT EXISTS (SELECT 1 FROM inbox e
                  WHERE e.customer_id = i.customer_id AND e.status = 'pending' AND e.seq < i.seq)
ORDER BY i.seq
FOR UPDATE SKIP LOCKED
LIMIT 1;
```

**Why `NOT EXISTS`:** with several workers, `SKIP LOCKED` alone would let worker B take message 2 while worker A still holds message 1. The earlier row stays `pending` (and locked) until A commits, so message 2 cannot be claimed until message 1 is done. Per-customer order holds with N workers.

**`process_next(session_factory, extractor, catalog, *, max_attempts, context_window) -> bool`**, in one transaction:

1. Claim the row. None → return `False`.
2. `SELECT pg_advisory_xact_lock(hashtext(customer_id))`: serializes against review resolution for the same customer.
3. `SAVEPOINT` (`begin_nested`), then:
   * **message:** upsert customer + conversation; read the last N messages of the chat; insert the message. `outbound` → `processed`, trace `{"skipped": "outbound"}`. Otherwise `extractor.interpret(ctx)` → `validate_skus` (foreign → `None`) → `open_views(customer)` → `route(...)` + `route_scores(...)`.
   * **conversation:** upsert, store each history message under its synthetic id. If the thread is already linked to an open quote → `Review(ambiguous_quote, linked)` (a re-post must not create a duplicate). Otherwise `extract_conversation` → items → `NewQuote`, empty/`None`/foreign SKU → `Review(extraction_failed)`.
   * `_execute(decision)`: `NewQuote` → `Quote.create(next_id(), …, Cause(message_id))`; `Apply` → `get_for_update(quote_id)` (`SELECT … FOR UPDATE`) + `quote.apply(ops, cause)`; then `QuoteRepo.save` (quote row + version, line upserts/deletes, `quote_conversations` with `linked_by_message_id`, `quote_events`). `Review` → `review_items` row, status `needs_review`. `NoOp` → `processed`.
   * `inbox.finish(seq, status, trace)` with `trace = {extractor_source, interpretation, scores, decision, latency_ms}`.
4. **On an exception** inside the savepoint: roll back the savepoint only, then `record_failure` on the still-locked row: `attempts += 1`, `error`, `status = failed` if `DomainError` or `attempts >= max_attempts`, else `pending`. Recording the failure under the same row lock is what prevents a second worker from claiming the row between rollback and bookkeeping (a race found in review).
5. Commit; return `True`.

**Loop** (`worker.run`): `process_next` until it returns `False`, then wait `POLL_INTERVAL_S` (0.5 s) or until stop. SIGTERM/SIGINT set the stop event; the current message finishes first.

**Note:** the LLM call happens while the row and advisory locks are held. Acceptable at this scale (one customer blocks only itself). The upgrade path is two-phase processing: interpret outside the transaction, then re-read and route inside it using the version check.

## 9. Review resolution (`application/reviews.py`)

```python
class ResolveIn(BaseModel):
    action: Literal["apply", "dismiss"]
    quote_id: str | None = None
    expected_version: int | None = None
    ops: list[OpIn] = []        # discriminated on "op": cancel | set_qty | add_line | remove_line | link_conversation
    new_quote: bool = False     # create a quote from the add_line ops (e.g. extraction_failed on a new request)
```

In one transaction:

1. Lock the review row (`FOR UPDATE`). Missing or not `open` → `ReviewNotOpen` (409).
2. Take the customer's advisory lock.
3. **apply:** `Cause(message_id of the source message, review_id)`; `link_conversation` without an id defaults to the source message's conversation.
   * `new_quote` → `Quote.create(...)`;
   * otherwise `quote_id` and `expected_version` are required (else 422); load the quote `FOR UPDATE` (must belong to the review's customer); `version != expected_version` → `StaleVersion` (409 with the current quote); `quote.apply(ops, cause)`.
   * save.
4. Review → `resolved` (or `dismissed`), store `resolution`. The inbox row stays `needs_review`: the historical truth.
5. Any error rolls back; `DomainError` / `ValueError` → 422.

## 10. HTTP API (`adapters/api/`)

| Method & path | Request | Responses |
|---------------|---------|-----------|
| `POST /v1/conversations[?wait=true]` | challenge Phase 1 payload | 202 `{inbox_seq, status_url}` · 200 `{status:"duplicate", inbox_seq}` · 422 |
| `POST /v1/messages[?wait=true]` | challenge Phase 2 event | 202 · 200 duplicate · 409 `{error:"message_id reused with different payload"}` · 422 |
| `GET /v1/inbox/{seq}` | —       | 200 `{seq, status, decision, error}` · 404 |
| `GET /v1/quotes?customer=` | —       | 200 `{"quotes":[QuoteOut]}`, ordered by id |
| `GET /v1/quotes/{id}` | —       | 200 `QuoteOut + document_type:"Oferta_de_Venta"` · 404 |
| `GET /v1/quotes/{id}/history` | —       | 200 `[{id, type, message_text, payload, message_id, review_id, created_at}]` · 404 |
| `GET /v1/reviews?status=open&customer=` | —       | 200 `[{id, reason, message:{id,text,conversation_id}, candidates:[QuoteOut+version], proposed}]` |
| `POST /v1/reviews/{id}/resolve` | `ResolveIn` | 200 `{review, quote}` · 409 stale / not open · 422 invalid |
| `GET /health` | —       | `{db, llm, model, model_present}`; 200, or 503 when the DB is down (a missing model does not fail health) |

* **`QuoteOut`** has exactly the challenge shape: `{quote_id, status, conversations: sorted, line_items: [{sku, qty}] by position}`.
* **`?wait=true`:** after the insert, poll `inbox.status` every 250 ms until it is not `pending` or `WAIT_TIMEOUT_S` (300) elapses; then 200 `{inbox_seq, status, decision}`, or 202 on timeout.
* `/health` checks `GET {LLM_BASE_URL}/models` and whether the configured model is listed (DMR lists HF models as `huggingface.co/<lowercased ref>`).

## 11. Configuration (`config.py`, env)

| Variable | Default |
|----------|---------|
| `DATABASE_URL` | `postgresql+asyncpg://quote:quote@postgres:5432/quote` |
| `LLM_BASE_URL` | `http://localhost:12434/engines/v1` (Compose injects the in-network URL) |
| `LLM_MODEL` | `hf.co/unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M` |
| `EXTRACTOR_MODE` | `cascade` |
| `LLM_TIMEOUT_S` / `LLM_MAX_RETRIES` | 180 / 2 |
| `CONTEXT_WINDOW_MESSAGES` | 10 |
| `WAIT_TIMEOUT_S` / `POLL_INTERVAL_S` / `MAX_ATTEMPTS` | 300 / 0.5 / 3 |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset; reserved, not used yet |
| `API_PORT` (Compose / justfile only) | 8000 |

## 12. Logging

* **structlog** JSON with bound `inbox_seq`, `customer_id`, `message_id`.
* One line per stage: `claimed`, `interpreted{source, latency_ms}`, `routed{decision, scores}`, `applied{quote_id, events}`, `review_created{review_id, reason}`, `skipped`, `attempt_failed`; extractor-level `llm_ok` / `llm_failed`, `replay_miss`, `foreign_sku_rejected`.
* The full decision trace is also persisted in `inbox.decision` and readable via `GET /v1/inbox/{seq}`.

## 13. Testing matrix

| Layer | Tool | What |
|-------|------|------|
| Unit — router | pytest, parametrized | table in §5 |
| Unit — aggregate | pytest | invariants, all-or-nothing batches, idempotent no-ops, events, version bump |
| Unit — rules | pytest, parametrized | the 4 challenge events + cancel → exact interpretation; tricky phrasings → `None` |
| Unit — extractors / contracts | pytest | cascade fallback, replay hit/miss/invalid, LLM schema carries the SKU enum, foreign SKU rejected |
| Integration | pytest + testcontainers `postgres:17` + replay extractor + httpx `ASGITransport` | Phase 1 → Q-001; events 1–4 with state asserted after each, final == challenge JSON; restart (new engine) → same state; event 4 resent → duplicate, version unchanged; same text with a new id → applied; "mejor cancelalo" → review, no change; resolve stale → 409, resolve OK → cancelled with `review_id` in history; re-posted conversation → review; max attempts → failed; `DomainError` → failed at once; two concurrent workers keep per-customer order; failure bookkeeping keeps the row locked |
| LLM (`-m llm`) | real Docker Model Runner | Phase 1 sample → exact 3 lines; fallback phrasings; never a foreign SKU |
| Evals | pydantic-evals, `just eval mode=…` | 23-case golden set: intent acc, SKU-set acc, routing acc (target **and** ops), % rules, p50/p95, review rate, wrong mutations, safe misses; modes `cascade` / `llm` / `rules` |

## 14. Docker and justfile essentials

* **`models: llm`** (top level): `model: hf.co/unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M`, `context_size: 8192` (the model's default 262144 OOMs). `api` and `worker` bind it with `endpoint_var: LLM_BASE_URL, model_var: LLM_MODEL`.
* **`compose.replay.yaml`**: resets `models:` on both services and globally and sets `EXTRACTOR_MODE=replay`.
* **`api`** runs `alembic upgrade head`, seeds the catalog (idempotent), then `uvicorn --factory quote_engine.adapters.api.app:create_app_from_env`. Port `${API_PORT:-8000}`. The `worker` waits for the api to be healthy (migrations done).
* **`just up-gpu`**: `docker model reinstall-runner --gpu cuda`, then the same `up`.
* **`just demo`** (`scripts/demo.sh`, needs `curl` + `jq`):
  1. `/health` + a warm-up message;
  2. POST Phase 1 → print quotes;
  3. POST events 1–4 with `?wait=true`, printing `GET /v1/quotes?customer=C-10029` after each;
  4. resend event 4 → duplicate;
  5. POST "mejor cancelalo" → show `/v1/reviews`;
  6. print the history of Q-002;
  7. compare the final state with the challenge's expected JSON (exit 1 on mismatch).
