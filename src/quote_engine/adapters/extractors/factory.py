from pathlib import Path

from quote_engine.adapters.extractors.cascade import CascadeExtractor
from quote_engine.adapters.extractors.replay import ReplayExtractor
from quote_engine.adapters.extractors.rules import RuleExtractor
from quote_engine.application.ports import Extractor
from quote_engine.config import Settings
from quote_engine.domain.catalog import Catalog

REPLAY_DIR = Path("fixtures/llm_replay")


def build_extractor(settings: Settings, catalog: Catalog) -> Extractor:
    mode = settings.extractor_mode
    rules = RuleExtractor(catalog)
    if mode == "rules":
        return rules
    if mode == "replay":
        return CascadeExtractor(rules, ReplayExtractor(REPLAY_DIR, catalog))
    if mode in ("cascade", "llm"):
        from quote_engine.adapters.extractors.llm import (  # ty: ignore[import-not-found]
            LLMExtractor,
        )

        llm = LLMExtractor(settings, catalog)
        return llm if mode == "llm" else CascadeExtractor(rules, llm)
    raise ValueError(f"unknown EXTRACTOR_MODE: {mode}")
