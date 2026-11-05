import json
from pathlib import Path

import pytest

from quote_engine.adapters.extractors.llm import LLMExtractor
from quote_engine.application.ports import ConversationCtx, MessageCtx
from quote_engine.config import Settings
from quote_engine.domain.catalog import Catalog
from quote_engine.domain.interpretation import Intent

pytestmark = pytest.mark.llm

ROOT = Path(__file__).parent.parent.parent
FBT = "ALFBTC-013-320100"


@pytest.fixture(scope="module")
def llm(catalog: Catalog) -> LLMExtractor:
    return LLMExtractor(Settings(), catalog)


def msg(text: str) -> MessageCtx:
    history = [("inbound", "Cotizame 20 rollos de lona frontlit 3.20x100"), ("outbound", "Listo")]
    return MessageCtx("m1", "c1", "C-1", "inbound", text, history)


async def test_phase1_real_model(llm, catalog):
    p = json.loads((ROOT / "fixtures/challenge/phase1.json").read_text())
    messages = [(m["direction"], m["text"]) for m in p["conversation_history"]]
    result = await llm.extract_conversation(ConversationCtx("wa-thread-411", "C-10029", messages))
    assert result is not None
    assert {(i.sku, i.qty) for i in result.items} == {
        ("ALFBTC-013-320100", 20),
        ("ALMCLC-0909-320100", 5),
        ("AVMICS-1A-137050", 5),
    }


async def test_fallback_phrasing(llm):
    r = await llm.interpret(msg("mejor que sean quince de las lonas, no veinte"))
    assert r is not None
    assert r.source == "llm"
    assert r.intent == Intent.UPDATE_QTY
    [item] = r.items
    assert item.qty == 15
    assert item.previous_qty == 20
    assert FBT in item.sku_candidates


async def test_never_foreign_sku(llm, catalog):
    r = await llm.interpret(msg("cotizame 3 lonas de 5x100"))
    if r is not None:
        assert all(s in catalog.items for i in r.items for s in i.sku_candidates)
