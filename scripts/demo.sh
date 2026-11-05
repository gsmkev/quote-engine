#!/usr/bin/env bash
# End-to-end demo of the challenge scenario against a running stack (see `just demo`).
set -euo pipefail
cd "$(dirname "$0")/.."

API="${API_URL:-http://localhost:${API_PORT:-8000}}"
FX=fixtures/challenge
C=C-10029

step() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
# Pretty-print an ingest response: outcome first, then how it was decided.
SUMMARY='if .decision then {inbox_seq, status,
  extractor: .decision.extractor_source, latency_ms: .decision.latency_ms,
  decision: .decision.decision, router_scores: .decision.scores,
  interpretation: .decision.interpretation} else . end'
show() { jq "$SUMMARY"; }
post() { curl -fsS -X POST "$API$1" -H 'content-type: application/json' --data @"$2" | show; }
quotes() { curl -fsS "$API/v1/quotes?customer=$C" | jq .; }

step "0. Health / warm-up"
curl -fsS "$API/health" | jq .
curl -fsS -X POST "$API/v1/messages?wait=true" -H 'content-type: application/json' \
  -d '{"message_id":"warmup","conversation_id":"warmup","customer_id":"C-WARMUP","direction":"inbound","timestamp":"2026-01-01T00:00:00Z","text":"hola"}' | show

step "1. Phase 1: conversation history -> draft quote"
post "/v1/conversations?wait=true" $FX/phase1.json
quotes

n=1
for e in event1 event2 event3 event4; do
  step "2.$n Phase 2: $e — $(jq -r .text $FX/$e.json)"
  post "/v1/messages?wait=true" $FX/$e.json
  quotes
  n=$((n + 1))
done

step "3. Resend event4 (same message_id, same payload) -> duplicate"
curl -fsS -X POST "$API/v1/messages?wait=true" -H 'content-type: application/json' \
  --data @$FX/event4.json | jq -ce '.status == "duplicate"' \
  || { echo "FAIL: resent event4 was not reported as duplicate" >&2; exit 1; }

step "4. Ambiguous message '$(jq -r .text $FX/cancel.json)' -> human review"
post "/v1/messages?wait=true" $FX/cancel.json
curl -fsS "$API/v1/reviews?customer=$C" | jq .

step "5. History of Q-002"
curl -fsS "$API/v1/quotes/Q-002/history" | jq .

step "6. Final state check"
expected='[
 {"quote_id":"Q-001","status":"draft","conversations":["wa-thread-411","wa-thread-662"],
  "line_items":[{"sku":"ALFBTC-013-320100","qty":15},{"sku":"ALMCLC-0909-320100","qty":5},{"sku":"AVMICS-1A-137050","qty":5}]},
 {"quote_id":"Q-002","status":"draft","conversations":["wa-thread-411","wa-thread-662"],
  "line_items":[{"sku":"ARACBL-03-122244","qty":4}]}]'
actual=$(curl -fsS "$API/v1/quotes?customer=$C" | jq -c '[.quotes[] | {quote_id,status,conversations,line_items}]')
if [ "$(jq -S . <<<"$actual")" = "$(jq -S . <<<"$expected")" ]; then
  echo "✅ final quotes match the challenge's expected state"
else
  echo "❌ final quotes differ from the challenge's expected state"; echo "$actual" | jq .; exit 1
fi
