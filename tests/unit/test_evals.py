from evals.run_evals import Expected, Result, decision_str, summarize


def pair(exp_decision, got_decision, source="rules", ms=1.0):
    e = Expected(intent="add_items", skus=["A"], decision=exp_decision)
    r = Result(intent="add_items", skus=["A"], decision=got_decision, source=source, latency_ms=ms)
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


def test_golden_defaults_are_backward_compatible():
    from evals.run_evals import Golden

    g = Golden.model_validate_json(
        '{"name":"x","text":"t","open_quotes":[],"conversation_id":"c",'
        '"expected":{"intent":"other","skus":[],"decision":"noop"}}'
    )
    assert (g.direction, g.history, g.category) == ("inbound", [], "legacy")


def test_summarize_per_category():
    m = summarize(
        [
            pair("apply:Q-001", "apply:Q-001"),
            pair("apply:Q-001", "apply:Q-002"),  # wrong mutation
            pair("new", "review"),  # safe miss
        ],
        ["a", "a", "b"],
    )
    assert m["per_category"] == {
        "a": {"n": 2, "routing_acc": 0.5, "wrong_mutations": 1, "safe_misses": 0},
        "b": {"n": 1, "routing_acc": 0.0, "wrong_mutations": 0, "safe_misses": 1},
    }


class FakeExtractor:
    def __init__(self):
        self.ctxs = []

    async def interpret(self, ctx):
        self.ctxs.append(ctx)
        return None

    async def extract_conversation(self, ctx):
        return None


def _golden(**kw):
    from evals.run_evals import Golden

    base: dict = {
        "name": "x", "text": "hi", "open_quotes": [], "conversation_id": "c",
        "expected": {"intent": "other", "skus": [], "decision": "noop"},
    }  # fmt: skip
    return Golden.model_validate(base | kw)


async def test_outbound_case_is_noop_without_extractor():
    from evals.run_evals import CATALOG, run_case
    from quote_engine.domain.catalog import Catalog

    ex = FakeExtractor()
    r = await run_case(_golden(direction="outbound"), ex, Catalog.from_json(CATALOG))
    assert ex.ctxs == []
    assert (r.decision, r.source) == ("noop", "skipped")
    assert r.intent == "none"  # skipped outbound means "no intent", not "extractor gave up"


async def test_history_and_direction_reach_the_context():
    from evals.run_evals import CATALOG, run_case
    from quote_engine.domain.catalog import Catalog

    ex = FakeExtractor()
    g = _golden(history=[("outbound", "Quote Q-1?"), ("inbound", "yes")])
    await run_case(g, ex, Catalog.from_json(CATALOG))
    assert ex.ctxs[0].history == [("outbound", "Quote Q-1?"), ("inbound", "yes")]
    assert ex.ctxs[0].direction == "inbound"


def test_filtered_run_leaves_canonical_results_untouched(tmp_path, monkeypatch, capsys):
    import sys

    import evals.run_evals as ev

    async def fake_run(mode, only=None):
        assert only == {"a", "b"}  # whitespace stripped
        e, r = pair("noop", "noop")
        return None, summarize([(e, r)]), []

    monkeypatch.setattr(ev, "HERE", tmp_path)
    monkeypatch.setattr(ev, "run", fake_run)
    monkeypatch.setenv("EVAL_HOST", "h")
    canon = tmp_path / "results-rules-h.json"
    canon.write_text("CANON")
    (tmp_path / "results-rules-h.md").write_text("CANON")
    monkeypatch.setattr(sys, "argv", ["x", "--mode", "rules", "--only", "a, b"])
    ev.main()
    assert canon.read_text() == "CANON"
    assert (tmp_path / "results-rules-h.md").read_text() == "CANON"
    assert (tmp_path / "results-rules-h.only.json").exists()
    assert (tmp_path / "results-rules-h.only.md").exists()
