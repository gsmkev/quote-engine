import hashlib
import json

import pytest

from quote_engine.adapters.extractors.cascade import CascadeExtractor
from quote_engine.adapters.extractors.factory import build_extractor
from quote_engine.adapters.extractors.replay import ReplayExtractor
from quote_engine.adapters.extractors.rules import RuleExtractor
from quote_engine.application.ports import ConversationCtx, MessageCtx
from quote_engine.config import Settings
from quote_engine.domain.catalog import Catalog
from quote_engine.domain.interpretation import (
    ConversationExtraction,
    ExtractedLine,
    Intent,
    MessageInterpretation,
)

catalog = Catalog.from_json("fixtures/catalog.json")
ACR = "ARACBL-03-122244"


def msg(text: str) -> MessageCtx:
    return MessageCtx("m1", "c1", "cust", "inbound", text, [])


CONV = ConversationCtx("c1", "cust", [("inbound", "necesito 2 acrilicos"), ("outbound", "ok")])
EXTRACTION = ConversationExtraction(items=[ExtractedLine(sku=ACR, qty=2, evidence="2 acrilicos")])


class Fixed:
    def __init__(self, interp=None, extraction=None):
        self.interp, self.extraction, self.calls = interp, extraction, 0

    async def interpret(self, ctx):
        self.calls += 1
        return self.interp

    async def extract_conversation(self, ctx):
        self.calls += 1
        return self.extraction


async def test_replay_conversation_hit(tmp_path):
    r = ReplayExtractor(tmp_path, catalog)
    r.record(ReplayExtractor.conversation_key(CONV.messages), EXTRACTION)
    got = await r.extract_conversation(CONV)
    assert got is not None
    assert got.model_dump() == EXTRACTION.model_dump()


async def test_replay_message_hit_is_tagged_replay(tmp_path):
    r = ReplayExtractor(tmp_path, catalog)
    stored = MessageInterpretation(intent=Intent.QUERY, source="llm")
    r.record(ReplayExtractor.message_key("hola?"), stored)
    got = await r.interpret(msg("hola?"))
    assert got is not None
    assert got.intent is Intent.QUERY
    assert got.source == "replay"


async def test_replay_miss_returns_none(tmp_path):
    r = ReplayExtractor(tmp_path, catalog)
    assert await r.interpret(msg("nada")) is None
    assert await r.extract_conversation(CONV) is None


async def test_replay_rejects_foreign_sku(tmp_path):
    r = ReplayExtractor(tmp_path, catalog)
    key = ReplayExtractor.conversation_key(CONV.messages)
    bad = {"items": [{"sku": "FAKE-SKU", "qty": 1, "evidence": "x"}]}
    r.record(key, ConversationExtraction.model_validate(bad))
    assert await r.extract_conversation(CONV) is None
    r.record(
        ReplayExtractor.message_key("x"), MessageInterpretation(intent=Intent.NONE, source="llm")
    )
    r._path(ReplayExtractor.message_key("x")).write_text('{"intent": "bogus"}')
    assert await r.interpret(msg("x")) is None


async def test_replay_key_is_sha256_of_key_input(tmp_path):
    r = ReplayExtractor(tmp_path, catalog)
    path = r.record("msg|hola", MessageInterpretation(intent=Intent.NONE, source="llm"))
    assert path == tmp_path / f"{hashlib.sha256(b'msg|hola').hexdigest()}.json"
    assert json.loads(path.read_text())["intent"] == "none"


async def test_cascade_uses_first_when_it_answers():
    hit = MessageInterpretation(intent=Intent.QUERY, source="rules")
    first, fallback = Fixed(interp=hit), Fixed()
    assert await CascadeExtractor(first, fallback).interpret(msg("x")) is hit
    assert fallback.calls == 0


async def test_cascade_falls_back_on_none():
    hit = MessageInterpretation(intent=Intent.QUERY, source="replay")
    assert await CascadeExtractor(Fixed(), Fixed(interp=hit)).interpret(msg("x")) is hit
    assert await CascadeExtractor(Fixed(), None).interpret(msg("x")) is None


async def test_cascade_conversation_always_uses_fallback():
    first = Fixed(extraction=EXTRACTION)
    assert await CascadeExtractor(first, Fixed()).extract_conversation(CONV) is None
    assert first.calls == 0
    fb = Fixed(extraction=EXTRACTION)
    assert await CascadeExtractor(first, fb).extract_conversation(CONV) is EXTRACTION
    assert await CascadeExtractor(first, None).extract_conversation(CONV) is None


def test_build_extractor_modes():
    assert isinstance(build_extractor(Settings(extractor_mode="rules"), catalog), RuleExtractor)
    replay = build_extractor(Settings(extractor_mode="replay"), catalog)
    assert isinstance(replay, CascadeExtractor)
    assert isinstance(replay.first, RuleExtractor)
    assert isinstance(replay.fallback, ReplayExtractor)
    with pytest.raises(ValueError, match="bogus"):
        build_extractor(Settings(extractor_mode="bogus"), catalog)
