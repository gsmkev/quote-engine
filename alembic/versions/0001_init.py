"""init schema"""

from alembic import op

revision = "0001"
down_revision = None

DDL = """
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
  id text PRIMARY KEY,                         -- 'Q-' || lpad(nextval('quote_seq')::text, 3, '0')
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
  message_id text,                             -- null only for review-originated ops without a message
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
  proposed jsonb,                              -- prefilled {quote_id, ops[]} when inferable
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved','dismissed')),
  resolution jsonb,
  resolved_at timestamptz
);
"""


def upgrade() -> None:
    for stmt in DDL.split(";"):
        if stmt.strip():
            op.execute(stmt)  # asyncpg runs one statement per call


def downgrade() -> None:
    op.execute(
        "DROP TABLE review_items, quote_events, inbox, messages, quote_conversations, "
        "quote_lines, quotes, catalog, conversations, customers CASCADE; "
        "DROP SEQUENCE quote_seq"
    )
