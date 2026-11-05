import pytest

from quote_engine.domain.quote import (
    AddLine,
    Cancel,
    Cause,
    DomainError,
    LinkConversation,
    Quote,
    RemoveLine,
    SetQty,
)

FBT = "ALFBTC-013-320100"
MCL = "ALMCLC-0909-320100"
MIC = "AVMICS-1A-137050"
ACR = "ARACBL-03-122244"
CAUSE = Cause(message_id="m1")


def make() -> Quote:
    return Quote.create("Q-001", "C1", [(FBT, 20), (ACR, 3)], "661", CAUSE)


def types(q: Quote) -> list[str]:
    return [e.type for e in q.pending_events]


def test_create_emits_events_in_order():
    q = Quote.create("Q-001", "C1", [(FBT, 20), (MCL, 5)], "661", CAUSE)
    assert types(q) == [
        "QuoteCreated",
        "LineAdded",
        "LineAdded",
        "ConversationLinked",
    ]
    assert q.pending_events[0].payload == {"customer_id": "C1"}
    assert q.pending_events[1].payload == {"sku": FBT, "qty": 20}
    assert q.pending_events[3].payload == {"conversation_id": "661"}
    assert q.version == 1
    assert [q.lines[FBT].position, q.lines[MCL].position] == [0, 1]
    assert q.conversations == {"661"}
    assert q.status == "draft"


def test_set_qty_emits_change_and_bumps_version():
    q = make()
    q.pending_events.clear()
    q.apply([SetQty(FBT, 15)], CAUSE)
    assert [(e.type, e.payload) for e in q.pending_events] == [
        ("LineQtyChanged", {"sku": FBT, "from": 20, "to": 15})
    ]
    assert q.version == 2


def test_set_qty_same_is_noop():
    q = make()
    q.pending_events.clear()
    q.apply([SetQty(FBT, 20)], CAUSE)
    assert q.pending_events == []
    assert q.version == 1


def test_link_existing_conversation_is_noop():
    q = make()
    q.pending_events.clear()
    q.apply([LinkConversation("661")], CAUSE)
    assert q.pending_events == []
    assert q.version == 1


def test_batch_bumps_version_once():
    q = make()
    q.pending_events.clear()
    q.apply([LinkConversation("662"), SetQty(ACR, 4)], CAUSE)
    assert len(q.pending_events) == 2
    assert q.version == 2
    assert q.conversations == {"661", "662"}


def test_add_line_existing_raises():
    with pytest.raises(DomainError):
        make().apply([AddLine(FBT, 1)], CAUSE)


def test_set_qty_and_remove_missing_raise():
    with pytest.raises(DomainError):
        make().apply([SetQty(MIC, 1)], CAUSE)
    with pytest.raises(DomainError):
        make().apply([RemoveLine(MIC)], CAUSE)


@pytest.mark.parametrize("qty", [0, -1])
def test_non_positive_qty_raises(qty):
    with pytest.raises(DomainError):
        make().apply([SetQty(FBT, qty)], CAUSE)
    with pytest.raises(DomainError):
        make().apply([AddLine(MIC, qty)], CAUSE)


def test_batch_is_all_or_nothing():
    q = make()
    with pytest.raises(DomainError):
        q.apply([SetQty(FBT, 1), RemoveLine(MIC)], CAUSE)
    assert q.lines[FBT].qty == 20
    assert q.version == 1


def test_batch_accounts_for_earlier_ops():
    q = make()
    q.apply([AddLine(MIC, 2), SetQty(MIC, 3)], CAUSE)
    assert q.lines[MIC].qty == 3
    assert q.version == 2


def test_remove_line_keeps_positions_and_add_uses_max_plus_one():
    q = make()
    q.pending_events.clear()
    q.apply([RemoveLine(FBT)], CAUSE)
    assert q.pending_events[0].payload == {"sku": FBT, "qty": 20}
    q.apply([AddLine(MIC, 2)], CAUSE)
    assert q.line_items() == [(ACR, 3), (MIC, 2)]
    assert q.lines[ACR].position == 1
    assert q.lines[MIC].position == 2


def test_cancel_then_any_op_raises():
    q = make()
    q.pending_events.clear()
    q.apply([Cancel()], CAUSE)
    assert types(q) == ["QuoteCancelled"]
    assert q.pending_events[0].payload == {}
    assert q.status == "cancelled"
    with pytest.raises(DomainError):
        q.apply([SetQty(FBT, 1)], CAUSE)


def test_events_carry_cause():
    cause = Cause(message_id="m9", review_id=4)
    q = make()
    q.apply([SetQty(FBT, 1), LinkConversation("9")], cause)
    assert all(e.cause == cause for e in q.pending_events[-2:])
    assert all(e.cause == CAUSE for e in q.pending_events[:-2])
