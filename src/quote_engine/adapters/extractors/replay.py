import hashlib
import json
from pathlib import Path

import structlog
from pydantic import BaseModel, ValidationError

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

    def _validate[T: BaseModel](self, model: type[T], data: dict | None) -> T | None:
        if data is None:
            return None
        try:
            return model.model_validate(data)
        except ValidationError as e:
            # An invalid recording (e.g. a foreign SKU) is a miss: route to review, don't retry.
            log.warning("replay_invalid", error=str(e))
            return None

    async def interpret(self, ctx: MessageCtx) -> MessageInterpretation | None:
        data = self._load(self.message_key(ctx.text))
        return self._validate(self._interp, data and {**data, "source": "replay"})

    async def extract_conversation(self, ctx: ConversationCtx) -> ConversationExtraction | None:
        return self._validate(self._extraction, self._load(self.conversation_key(ctx.messages)))
