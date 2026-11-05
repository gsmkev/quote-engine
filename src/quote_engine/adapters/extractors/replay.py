import hashlib
import json
from pathlib import Path

import structlog
from pydantic import BaseModel

from quote_engine.application.ports import ConversationCtx, MessageCtx
from quote_engine.domain.catalog import Catalog
from quote_engine.domain.interpretation import (
    ConversationExtraction,
    MessageInterpretation,
    make_llm_models,
)

log = structlog.get_logger()


class ReplayExtractor:
    """Serves recorded LLM outputs from `<dir>/<sha256(key)>.json`; None on a miss."""

    def __init__(self, dir: Path, catalog: Catalog) -> None:
        self.dir = dir
        self._interp, self._extraction = make_llm_models(catalog)

    @staticmethod
    def message_key(text: str) -> str:
        return "msg|" + text

    @staticmethod
    def conversation_key(messages: list[tuple[str, str]]) -> str:
        return "conv|" + "\n".join(f"{d}:{t}" for d, t in messages)

    def _path(self, key_input: str) -> Path:
        return self.dir / f"{hashlib.sha256(key_input.encode()).hexdigest()}.json"

    def _load(self, key_input: str) -> dict | None:
        path = self._path(key_input)
        if not path.exists():
            log.warning("replay_miss", key=path.stem)
            return None
        return json.loads(path.read_text())

    def record(self, key_input: str, obj: BaseModel) -> Path:
        path = self._path(key_input)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(obj.model_dump_json(indent=2) + "\n")
        return path

    async def interpret(self, ctx: MessageCtx) -> MessageInterpretation | None:
        data = self._load(self.message_key(ctx.text))
        return None if data is None else self._interp.model_validate({**data, "source": "replay"})

    async def extract_conversation(self, ctx: ConversationCtx) -> ConversationExtraction | None:
        data = self._load(self.conversation_key(ctx.messages))
        return None if data is None else self._extraction.model_validate(data)
