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
from quote_engine.domain.quote import AddLine, Cancel, RemoveLine, SetQty
from quote_engine.domain.router import (
    Apply,
    Decision,
    NewQuote,
    NoOp,
    Op,
    QuoteView,
    route,
)

HERE = Path(__file__).parent
GOLDEN = HERE / "golden.jsonl"
CATALOG = HERE.parent / "fixtures" / "catalog.json"


class Expected(BaseModel):
    intent: str
    skus: list[str]
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
    decision: str
    source: str | None
    latency_ms: float


def op_str(op: Op) -> str | None:
    match op:
        case SetQty(sku=sku, qty=qty):
            return f"set_qty:{sku}={qty}"
        case AddLine(sku=sku, qty=qty):
            return f"add:{sku}={qty}"
        case RemoveLine(sku=sku):
            return f"remove:{sku}"
        case Cancel():
            return "cancel"
        case _:
            return None  # LinkConversation is not a quote mutation


def decision_str(d: Decision) -> str:
    """apply:Q-001[set_qty:SKU=8,..] | new[SKU=2,..] | noop | review; apply:Q-001[] = link only"""
    match d:
        case Apply(quote_id=qid, ops=ops):
            return f"apply:{qid}[{','.join(sorted(o for x in ops if (o := op_str(x))))}]"
        case NewQuote(lines=lines):
            return f"new[{','.join(sorted(f'{sku}={qty}' for sku, qty in lines))}]"
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
        "| intent acc | SKU-set acc | routing acc (target+ops) | % rules (no LLM) "
        "| p50 ms | p95 ms | review rate | wrong apply/new | review instead of apply (safe miss) |",
        "|---|---|---|---|---|---|---|---|---|",
        f"| {pct('intent_acc')} | {pct('sku_acc')} | {pct('routing_acc')} "
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

    total = len(GOLDEN.read_text().splitlines())
    progress = HERE / f".progress-{mode}.log"
    progress.write_text("")
    done = 0

    async def task(g: Golden) -> Result:
        nonlocal done
        quotes = [
            QuoteView(q["id"], q["lines"], frozenset(q["conversations"])) for q in g.open_quotes
        ]
        ctx = MessageCtx("eval", g.conversation_id, "C-eval", "inbound", g.text, [])
        start = time.monotonic()
        interp = await extractor.interpret(ctx)
        if interp is None:
            decision, intent, skus, source = "review", None, [], None
        else:
            decision = decision_str(route(interp, g.conversation_id, quotes))
            intent, source = interp.intent.value, interp.source
            skus = sorted({s for it in interp.items for s in it.sku_candidates})
        ms = (time.monotonic() - start) * 1000
        done += 1
        ok = decision == g.expected.decision
        with progress.open("a") as f:
            f.write(f"{mode} {done}/{total} {g.name} {'ok' if ok else 'FAIL'} {ms:.0f}\n")
        return Result(intent=intent, skus=skus, decision=decision, source=source, latency_ms=ms)

    goldens = {}
    for line in GOLDEN.read_text().splitlines():
        g = Golden.model_validate_json(line)
        assert g.name not in goldens, f"duplicate case name {g.name}"
        goldens[g.name] = g
    dataset = Dataset[Golden, Result, None](
        name="golden",
        cases=[Case(name=g.name, inputs=g) for g in goldens.values()],
        evaluators=[IntentMatch(), SkuSetMatch(), DecisionMatch()],
    )
    report = await dataset.evaluate(task, max_concurrency=1, progress=False)
    report.print(include_input=False, include_output=True)
    rows = []
    for c in report.cases:
        g = goldens[c.name]
        rows.append(
            {
                "name": c.name,
                "text": g.text,
                "expected": g.expected.model_dump(),
                "got": c.output.model_dump(),
            }
        )
    pairs = [(goldens[c.name].expected, c.output) for c in report.cases]
    return dataset, summarize(pairs), rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["cascade", "llm", "rules"], default="cascade")
    mode = ap.parse_args().mode
    host = os.environ.get("EVAL_HOST") or socket.gethostname().split(".")[0]
    progress = HERE / f".progress-{mode}.log"
    try:
        _, metrics, rows = asyncio.run(run(mode))
    except Exception as e:
        with progress.open("a") as f:
            f.write(f"{mode} ERROR {e!r}\n")
        raise
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
    with progress.open("a") as f:
        f.write(f"{mode} DONE\n")


if __name__ == "__main__":
    main()
