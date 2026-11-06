import asyncio
import hashlib

import pytest
from helpers import (
    ACR,
    FBT,
    MCL,
    MIC,
    REPLAY_DIR,
    fx,
    inbox_rows,
    ingest,
    open_reviews,
    replay_extractor,
    run_all,
    state,
)
from sqlalchemy.ext.asyncio import async_sessionmaker

from quote_engine.adapters.db.repos import InboxRepo
from quote_engine.adapters.db.uow import UnitOfWork, make_engine
from quote_engine.adapters.extractors.replay import ReplayExtractor
from quote_engine.application import process
from quote_engine.application.ingest import Duplicate
from quote_engine.application.process import process_next
from quote_engine.domain.interpretation import ConversationExtraction, ExtractedLine
from quote_engine.domain.quote import DomainError, LinkConversation, RemoveLine
from quote_engine.domain.router import Apply

pytestmark = pytest.mark.integration

C = "C-10029"
T411, T662 = "wa-thread-411", "wa-thread-662"

PHASE1 = [
    {
        "quote_id": "Q-001",
        "status": "draft",
        "conversations": [T411],
        "line_items": [{"sku": FBT, "qty": 20}, {"sku": MCL, "qty": 5}, {"sku": MIC, "qty": 5}],
    }
]

FINAL = [
    {
        "quote_id": "Q-001",
        "status": "draft",
        "conversations": [T411, T662],
        "line_items": [{"sku": FBT, "qty": 15}, {"sku": MCL, "qty": 5}, {"sku": MIC, "qty": 5}],
    },
    {
        "quote_id": "Q-002",
        "status": "draft",
        "conversations": [T411, T662],
        "line_items": [{"sku": ACR, "qty": 4}],
    },
]


@pytest.fixture
def extractor(catalog):
    return replay_extractor(catalog)


@pytest.fixture
def run(session_factory, extractor, catalog):
    async def go(*names: str | dict) -> int:
        for n in names:
            await ingest(session_factory, fx(n) if isinstance(n, str) else n)
        return await run_all(session_factory, extractor, catalog)

    return go


async def run_challenge(run) -> None:
    await run("phase1", "event1", "event2", "event3", "event4")


def test_phase1_replay_fixture_present():
    p = fx("phase1")
    key = ReplayExtractor.conversation_key(
        [(m["direction"], m["text"]) for m in p["conversation_history"]]
    )
    path = REPLAY_DIR / f"{hashlib.sha256(key.encode()).hexdigest()}.json"
    print("phase1 replay fixture:", path.name)
    assert path.exists()


async def test_phase1_creates_q001(run, session_factory):
    assert await run("phase1") == 1
    assert await state(session_factory, C) == PHASE1
    [row] = await inbox_rows(session_factory)
    assert row.status == "processed"


async def test_events_1_to_4(run, session_factory):
    await run("phase1")

    await run("event1")
    s = await state(session_factory, C)
    assert s == [
        {**PHASE1[0], "line_items": [{"sku": FBT, "qty": 15}, *PHASE1[0]["line_items"][1:]]}
    ]

    await run("event2")
    s2 = await state(session_factory, C)
    assert s2 == [{**s[0], "conversations": [T411, T662]}]

    await run("event3")
    s3 = await state(session_factory, C)
    assert s3 == [
        s2[0],
        {
            "quote_id": "Q-002",
            "status": "draft",
            "conversations": [T411],
            "line_items": [{"sku": ACR, "qty": 2}],
        },
    ]

    await run("event4")
    assert await state(session_factory, C) == FINAL
    assert {r.status for r in await inbox_rows(session_factory)} == {"processed"}


async def test_decision_trace_recorded(run, session_factory):
    await run_challenge(run)
    e4 = (await inbox_rows(session_factory))[-1]
    d = e4.decision
    assert d["extractor_source"] == "rules"
    assert d["interpretation"]["intent"] == "update_qty"
    assert d["scores"] == {"Q-001": 0, "Q-002": 3}
    assert d["decision"]["type"] == "Apply"
    assert d["decision"]["quote_id"] == "Q-002"
    assert isinstance(d["latency_ms"], int | float)
    assert e4.processed_at is not None


async def test_restart_preserves_state(run, session_factory, pg_url):
    await run_challenge(run)
    await session_factory.kw["bind"].dispose()
    engine = make_engine(pg_url)
    try:
        fresh = async_sessionmaker(engine, expire_on_commit=False)
        assert await state(fresh, C) == FINAL
    finally:
        await engine.dispose()


async def q002_version(sf) -> int:
    async with UnitOfWork(sf) as uow:
        q = await uow.quotes.get_for_update("Q-002")
        assert q is not None
        return q.version


async def test_duplicate_event4_no_change(run, session_factory, extractor, catalog):
    await run_challenge(run)
    v = await q002_version(session_factory)
    assert isinstance(await ingest(session_factory, fx("event4")), Duplicate)
    assert await run_all(session_factory, extractor, catalog) == 0
    assert await q002_version(session_factory) == v
    assert await state(session_factory, C) == FINAL


async def test_same_text_new_id_applies(run, session_factory):
    await run_challenge(run)
    six = {**fx("event4"), "text": fx("event4")["text"].replace("sean 4", "sean 6")}
    await run({**six, "message_id": "wamid.662.0003"})
    assert (await state(session_factory, C))[1]["line_items"] == [{"sku": ACR, "qty": 6}]
    v = await q002_version(session_factory)

    assert await run({**six, "message_id": "wamid.662.0004"}) == 1
    assert (await state(session_factory, C))[1]["line_items"] == [{"sku": ACR, "qty": 6}]
    assert await q002_version(session_factory) == v
    last = (await inbox_rows(session_factory))[-1]
    assert (last.dedupe_key, last.status) == ("wamid.662.0004", "processed")


async def test_cancel_ambiguous_goes_to_review(run, session_factory):
    await run_challenge(run)
    await run("cancel")
    assert (await inbox_rows(session_factory))[-1].status == "needs_review"
    [review] = await open_reviews(session_factory)
    assert review.reason == "ambiguous_quote"
    assert review.candidate_quote_ids == ["Q-001", "Q-002"]
    assert review.interpretation["intent"] == "cancel"
    assert review.proposed is None
    assert await state(session_factory, C) == FINAL


async def test_reposted_conversation_needs_review(run, session_factory):
    await run("phase1")
    p = fx("phase1")
    extra = {"direction": "inbound", "timestamp": "2026-02-10T09:50:00Z", "text": "gracias"}
    await run({**p, "conversation_history": [*p["conversation_history"], extra]})
    assert [r.status for r in await inbox_rows(session_factory)] == ["processed", "needs_review"]
    [review] = await open_reviews(session_factory)
    assert (review.reason, review.candidate_quote_ids) == ("ambiguous_quote", ["Q-001"])
    assert await state(session_factory, C) == PHASE1


async def test_update_with_no_quotes_needs_review(run, session_factory):
    await run({**fx("event4"), "customer_id": "C-NEW"})
    [row] = await inbox_rows(session_factory)
    assert row.status == "needs_review"
    [review] = await open_reviews(session_factory)
    assert (review.reason, review.candidate_quote_ids) == ("ambiguous_quote", [])
    assert await state(session_factory, "C-NEW") == []


async def test_uninterpretable_message_needs_review(run, session_factory):
    await run("phase1", {**fx("event1"), "text": "hola, una pregunta rapida"})
    assert (await inbox_rows(session_factory))[-1].status == "needs_review"
    [review] = await open_reviews(session_factory)
    assert (review.reason, review.candidate_quote_ids) == ("extraction_failed", ["Q-001"])
    assert review.interpretation is None
    assert await state(session_factory, C) == PHASE1


async def test_outbound_message_skipped(run, session_factory):
    await run("phase1", {**fx("event1"), "direction": "outbound"})
    last = (await inbox_rows(session_factory))[-1]
    assert (last.status, last.decision) == ("processed", {"skipped": "outbound"})
    assert await state(session_factory, C) == PHASE1


async def test_history_has_causes(run, session_factory):
    await run_challenge(run)
    async with UnitOfWork(session_factory) as uow:
        h = await uow.quotes.history("Q-002")
        h1 = await uow.quotes.history("Q-001")
    assert [e["type"] for e in h] == [
        "QuoteCreated",
        "LineAdded",
        "ConversationLinked",
        "ConversationLinked",
        "LineQtyChanged",
    ]
    assert h[3]["payload"] == {"conversation_id": T662}
    assert h[3]["message_id"] == h[4]["message_id"] == "wamid.662.0002"
    assert h[0]["message_id"] == "wamid.411.0232"
    # Phase 1 events point at the synthetic id of the conversation's last message.
    assert h1[0]["message_id"].startswith(f"{T411}:")
    assert len(h1[0]["message_id"]) == len(T411) + 13


class Raises:
    def __init__(self, exc: Exception):
        self.exc = exc

    async def interpret(self, ctx):
        raise self.exc

    async def extract_conversation(self, ctx):
        raise self.exc


async def test_failed_after_max_attempts(session_factory, catalog):
    await ingest(session_factory, fx("event1"))
    boom = Raises(RuntimeError("model exploded"))
    for attempt in (1, 2):
        assert await process_next(session_factory, boom, catalog)
        [row] = await inbox_rows(session_factory)
        assert (row.status, row.attempts) == ("pending", attempt)
    assert await process_next(session_factory, boom, catalog)
    [row] = await inbox_rows(session_factory)
    assert (row.status, row.attempts) == ("failed", 3)
    assert "model exploded" in row.error
    assert not await process_next(session_factory, boom, catalog)


class Extracts:
    """Phase 1 extractor stub returning fixed lines (and no Phase 2 interpretation)."""

    def __init__(self, *lines: tuple[str, int]):
        self.lines = lines

    async def interpret(self, ctx):
        return None

    async def extract_conversation(self, ctx):
        return ConversationExtraction(
            items=[ExtractedLine(sku=s, qty=q, evidence="x") for s, q in self.lines]
        )


class ExtractsUnknown(Extracts):
    async def extract_conversation(self, ctx):
        lines = [ExtractedLine(sku=s, qty=q, evidence="x") for s, q in self.lines]
        lines.append(ExtractedLine(sku=None, qty=3, evidence="lona 5x100", in_catalog=False))
        return ConversationExtraction(items=lines)


async def test_phase1_not_in_catalog_goes_to_review_without_quote(session_factory, catalog):
    await ingest(session_factory, fx("phase1"))
    await run_all(session_factory, ExtractsUnknown((FBT, 20)), catalog)
    [row] = await inbox_rows(session_factory)
    assert row.status == "needs_review"
    [review] = await open_reviews(session_factory)
    assert (review.reason, review.candidate_quote_ids) == ("unknown_product", [])
    assert review.interpretation["items"][-1]["in_catalog"] is False
    assert await state(session_factory, C) == []


async def test_phase1_duplicate_skus_merged(session_factory, catalog):
    await ingest(session_factory, fx("phase1"))
    await run_all(session_factory, Extracts((FBT, 20), (MIC, 5), (FBT, 3)), catalog)
    [row] = await inbox_rows(session_factory)
    assert row.status == "processed"
    [q] = await state(session_factory, C)
    assert q["line_items"] == [{"sku": FBT, "qty": 23}, {"sku": MIC, "qty": 5}]


async def test_domain_error_on_execute_goes_to_review(run, session_factory, monkeypatch):
    await run("phase1")
    bad = Apply("Q-001", [LinkConversation(T411), RemoveLine(ACR)])
    monkeypatch.setattr(process, "route", lambda *a, **k: bad)
    await run("event1")
    e1 = (await inbox_rows(session_factory))[-1]
    assert (e1.status, e1.attempts, e1.error) == ("needs_review", 0, None)
    assert e1.decision["decision"]["type"] == "Review"
    assert e1.decision["decision"]["reason"] == "invalid_ops"
    [review] = await open_reviews(session_factory)
    assert (review.reason, review.candidate_quote_ids) == ("invalid_ops", ["Q-001"])
    assert review.proposed["type"] == "Apply"
    assert review.interpretation["intent"] == "update_qty"
    assert await state(session_factory, C) == PHASE1


async def test_domain_error_outside_execute_is_retried(session_factory, catalog):
    await ingest(session_factory, fx("event1"))
    assert await process_next(session_factory, Raises(DomainError("bad op")), catalog)
    [row] = await inbox_rows(session_factory)
    assert (row.status, row.attempts) == ("pending", 1)


async def test_customer_ordering_two_workers(session_factory, extractor, catalog):
    await ingest(session_factory, fx("phase1"))
    await run_all(session_factory, extractor, catalog)
    for name in ("event1", "event2", "event3", "event4"):
        await ingest(session_factory, fx(name))

    handled: list[int] = []

    async def worker() -> None:
        # Keep polling until the inbox is drained, so both workers really contend.
        while any(r.status == "pending" for r in await inbox_rows(session_factory)):
            if await process_next(session_factory, extractor, catalog):
                handled.append(1)
            else:
                await asyncio.sleep(0.005)

    await asyncio.gather(worker(), worker())
    assert len(handled) == 4
    assert await state(session_factory, C) == FINAL
    rows = await inbox_rows(session_factory)
    assert [r.processed_at for r in rows] == sorted(r.processed_at for r in rows)


async def test_failure_bookkeeping_keeps_row_locked(
    session_factory, extractor, catalog, monkeypatch
):
    """While a failed attempt is being recorded, no other worker may claim and apply the row."""
    await ingest(session_factory, fx("phase1"))
    await run_all(session_factory, extractor, catalog)
    await ingest(session_factory, fx("event1"))

    original = InboxRepo.record_failure
    competitor: list[bool] = []

    async def racing_record_failure(self, *args, **kwargs):
        # A second worker runs exactly in the bookkeeping window.
        competitor.append(await process_next(session_factory, extractor, catalog))
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(InboxRepo, "record_failure", racing_record_failure)
    assert await process_next(session_factory, Raises(RuntimeError("flaky")), catalog)

    assert competitor == [False]
    e1 = (await inbox_rows(session_factory))[-1]
    assert (e1.status, e1.attempts) == ("pending", 1)

    monkeypatch.undo()
    assert await run_all(session_factory, extractor, catalog) == 1
    e1 = (await inbox_rows(session_factory))[-1]
    assert (e1.status, e1.attempts) == ("processed", 1)
    async with UnitOfWork(session_factory) as uow:
        assert [e["type"] for e in await uow.quotes.history("Q-001")][-1] == "LineQtyChanged"
        assert sum(e["type"] == "LineQtyChanged" for e in await uow.quotes.history("Q-001")) == 1
