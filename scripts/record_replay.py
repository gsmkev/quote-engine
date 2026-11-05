"""Run Phase 1 through the real LLMExtractor and record the output as a replay fixture."""

import asyncio
import json
from pathlib import Path

from quote_engine.adapters.extractors.llm import LLMExtractor
from quote_engine.adapters.extractors.replay import ReplayExtractor
from quote_engine.application.ports import ConversationCtx
from quote_engine.config import Settings
from quote_engine.domain.catalog import Catalog

ROOT = Path(__file__).parent.parent


async def main() -> None:
    catalog = Catalog.from_json(ROOT / "fixtures/catalog.json")
    p = json.loads((ROOT / "fixtures/challenge/phase1.json").read_text())
    messages = [(m["direction"], m["text"]) for m in p["conversation_history"]]
    llm = LLMExtractor(Settings(), catalog)
    result = await llm.extract_conversation(
        ConversationCtx(p["conversation_id"], p["customer_id"], messages)
    )
    if result is None:
        raise SystemExit("extraction failed")
    replay = ReplayExtractor(ROOT / "fixtures/llm_replay", catalog)
    print(replay.record(ReplayExtractor.conversation_key(messages), result))


asyncio.run(main())
