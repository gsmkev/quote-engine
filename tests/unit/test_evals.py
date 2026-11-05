from evals.run_evals import Expected, Result, summarize


def pair(exp_decision, got_decision, source="rules", ms=1.0):
    e = Expected(intent="add_items", skus=["A"], qty=1, decision=exp_decision)
    r = Result(
        intent="add_items", skus=["A"], qty=1, decision=got_decision, source=source, latency_ms=ms
    )
    return e, r


def test_summarize_separates_wrong_mutations_from_safe_misses():
    m = summarize(
        [
            pair("apply:Q-001", "apply:Q-001"),
            pair("apply:Q-001", "apply:Q-002", source="llm", ms=3.0),  # wrong mutation
            pair("new", "review", source="llm", ms=5.0),  # safe miss
            pair("noop", "new"),  # wrong mutation
        ]
    )
    assert m["routing_acc"] == 0.25
    assert m["wrong_mutations"] == 2
    assert m["safe_misses"] == 1
    assert m["review_rate"] == 0.25
    assert m["pct_rules"] == 0.5
    assert m["p50_ms"] == 2.0
