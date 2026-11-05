"""Golden-set evals: extraction + routing per case (no DB). `python -m evals.run_evals --mode X`."""

import argparse
import asyncio
import json
import os
import socket
import statistics
import time
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from quote_engine.adapters.extractors.factory import build_extractor
from quote_engine.application.ports import MessageCtx
from quote_engine.config import Settings
from quote_engine.domain.catalog import Catalog
from quote_engine.domain.router import Apply, Decision, NewQuote, NoOp, QuoteView, route

HERE = Path(__file__).parent
GOLDEN = HERE / "golden.jsonl"
CATALOG = HERE.parent / "fixtures" / "catalog.json"


class Expected(BaseModel):
    intent: str
    skus: list[str]
    qty: int | None
    decision: str


class Golden(BaseModel):
    name: str
    text: str
    open_quotes: list[dict]
    conversation_id: str
    expected: Expected


class Result(BaseModel):
    intent: str | None  # None: the extractor gave up / failed
    skus: list[str]
    qty: int | None
    decision: str
    source: str | None
    latency_ms: float


def decision_str(d: Decision) -> str:
    match d:
        case Apply(quote_id=qid):
            return f"apply:{qid}"
        case NewQuote():
            return "new"
        case NoOp():
            return "noop"
        case _:
            return "review"


def is_mutation(decision: str) -> bool:
    return decision.startswith(("apply", "new"))


@dataclass
class IntentMatch(Evaluator[Golden, Result, None]):
    def evaluate(self, ctx: EvaluatorContext[Golden, Result, None]) -> bool:
        return ctx.output.intent == ctx.inputs.expected.intent


@dataclass
class SkuSetMatch(Evaluator[Golden, Result, None]):
    def evaluate(self, ctx: EvaluatorContext[Golden, Result, None]) -> bool:
        return set(ctx.output.skus) == set(ctx.inputs.expected.skus)


@dataclass
class DecisionMatch(Evaluator[Golden, Result, None]):
    def evaluate(self, ctx: EvaluatorContext[Golden, Result, None]) -> bool:
        return ctx.output.decision == ctx.inputs.expected.decision


def percentile(values: list[float], p: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, round(p * (len(s) - 1)))] if s else 0.0


def summarize(pairs: list[tuple[Expected, Result]]) -> dict[str, float | int]:
    n = len(pairs)
    lat = [r.latency_ms for _, r in pairs]
    wrong = sum(1 for e, r in pairs if is_mutation(r.decision) and r.decision != e.decision)
    safe_miss = sum(1 for e, r in pairs if r.decision == "review" and e.decision != "review")
    return {
        "n": n,
        "intent_acc": sum(r.intent == e.intent for e, r in pairs) / n,
        "sku_acc": sum(set(r.skus) == set(e.skus) for e, r in pairs) / n,
        "qty_acc": sum(r.qty == e.qty for e, r in pairs) / n,
        "routing_acc": sum(r.decision == e.decision for e, r in pairs) / n,
        "pct_rules": sum(r.source == "rules" for _, r in pairs) / n,
        "p50_ms": statistics.median(lat) if lat else 0.0,
        "p95_ms": percentile(lat, 0.95),
        "review_rate": sum(r.decision == "review" for _, r in pairs) / n,
        "wrong_mutations": wrong,
        "safe_misses": safe_miss,
    }


def render_md(mode: str, host: str, m: dict[str, float | int], rows: list[dict]) -> str:
    pct = lambda k: f"{m[k]:.0%}"  # noqa: E731
    out = [
        f"**Mode `{mode}`** on `{host}` ({m['n']} golden cases)",
        "",
        "| intent acc | SKU-set acc | qty acc | routing acc | % rules (no LLM) | p50 ms | p95 ms "
        "| review rate | wrong apply/new | review instead of apply (safe miss) |",
        "|---|---|---|---|---|---|---|---|---|---|",
        f"| {pct('intent_acc')} | {pct('sku_acc')} | {pct('qty_acc')} | {pct('routing_acc')} "
        f"| {pct('pct_rules')} | {m['p50_ms']:.0f} | {m['p95_ms']:.0f} | {pct('review_rate')} "
        f"| {m['wrong_mutations']} | {m['safe_misses']} |",
        "",
    ]
    misses = [r for r in rows if r["got"]["decision"] != r["expected"]["decision"]]
    if misses:
        out += ["Routing misses:", "", "| case | expected | got | source |", "|---|---|---|---|"]
        out += [
            f"| {r['name']} | {r['expected']['decision']} | {r['got']['decision']} "
            f"| {r['got']['source']} |"
            for r in misses
        ]
    return "\n".join(out) + "\n"


async def run(mode: str) -> tuple[Dataset[Golden, Result, None], dict, list[dict]]:
    settings = Settings(extractor_mode=mode)
    extractor = build_extractor(settings, Catalog.from_json(CATALOG))

    async def task(g: Golden) -> Result:
        quotes = [
            QuoteView(q["id"], q["lines"], frozenset(q["conversations"])) for q in g.open_quotes
        ]
        ctx = MessageCtx("eval", g.conversation_id, "C-eval", "inbound", g.text, [])
        start = time.monotonic()
        interp = await extractor.interpret(ctx)
        if interp is None:
            decision, intent, skus, qty, source = "review", None, [], None, None
        else:
            decision = decision_str(route(interp, g.conversation_id, quotes))
            intent, source = interp.intent.value, interp.source
            skus = sorted({s for it in interp.items for s in it.sku_candidates})
            qty = interp.items[0].qty if interp.items else None
        ms = (time.monotonic() - start) * 1000
        return Result(
            intent=intent, skus=skus, qty=qty, decision=decision, source=source, latency_ms=ms
        )

    goldens = [Golden.model_validate_json(line) for line in GOLDEN.read_text().splitlines()]
    dataset = Dataset[Golden, Result, None](
        name="golden",
        cases=[Case(name=g.name, inputs=g) for g in goldens],
        evaluators=[IntentMatch(), SkuSetMatch(), DecisionMatch()],
    )
    report = await dataset.evaluate(task, max_concurrency=1, progress=False)
    report.print(include_input=False, include_output=True)
    rows = []
    for c in report.cases:
        g = next(x for x in goldens if x.name == c.name)
        rows.append(
            {
                "name": c.name,
                "text": g.text,
                "expected": g.expected.model_dump(),
                "got": c.output.model_dump(),
            }
        )
    pairs = [(g.expected, c.output) for c in report.cases for g in goldens if g.name == c.name]
    return dataset, summarize(pairs), rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["cascade", "llm", "rules"], default="cascade")
    mode = ap.parse_args().mode
    host = os.environ.get("EVAL_HOST") or socket.gethostname().split(".")[0]
    _, metrics, rows = asyncio.run(run(mode))
    md = render_md(mode, host, metrics, rows)
    print("\n" + md)
    base = HERE / f"results-{mode}-{host}"
    base.with_suffix(".json").write_text(
        json.dumps(
            {"mode": mode, "host": host, "metrics": metrics, "cases": rows},
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    base.with_suffix(".md").write_text(md)


if __name__ == "__main__":
    main()
