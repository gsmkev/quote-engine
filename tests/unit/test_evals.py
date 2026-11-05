from evals.run_evals import Expected, Result, decision_str, summarize


def pair(exp_decision, got_decision, source="rules", ms=1.0):
    e = Expected(intent="add_items", skus=["A"], decision=exp_decision)
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


def test_same_target_different_ops_counts_as_wrong_mutation():
    e = Expected(intent="update_qty", skus=["A"], decision="apply:Q-001[set_qty:A=8]")
    silent_drop = Result(
        intent="update_qty", skus=[], decision="apply:Q-001[]", source="llm", latency_ms=1.0
    )
    assert summarize([(e, silent_drop)])["wrong_mutations"] == 1


def test_decision_str_includes_mutating_ops():
    from quote_engine.domain.quote import LinkConversation, SetQty
    from quote_engine.domain.router import Apply, NewQuote

    d = Apply("Q-001", [LinkConversation("c"), SetQty("A", 8)])
    assert decision_str(d) == "apply:Q-001[set_qty:A=8]"
    assert decision_str(Apply("Q-001", [LinkConversation("c")])) == "apply:Q-001[]"
    assert decision_str(NewQuote([("B", 2), ("A", 1)])) == "new[A=1,B=2]"
