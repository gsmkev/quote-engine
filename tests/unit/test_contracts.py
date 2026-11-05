import pytest
from pydantic import ValidationError

from quote_engine.domain.catalog import Catalog
from quote_engine.domain.interpretation import (
    ItemMention,
    MessageInterpretation,
    make_llm_models,
    validate_skus,
)

SKUS = (
    "ALFBTC-013-320100",
    "ALMCLC-0909-320100",
    "AVMICS-1A-137050",
    "ARACBL-03-122244",
)


@pytest.fixture
def cat() -> Catalog:
    return Catalog.from_json("fixtures/catalog.json")


def _enums(node) -> list[list[str]]:
    found = []
    if isinstance(node, dict):
        if "enum" in node:
            found.append(node["enum"])
        for v in node.values():
            found += _enums(v)
    elif isinstance(node, list):
        for v in node:
            found += _enums(v)
    return found


def test_catalog_loads_four_skus(cat):
    assert cat.skus == SKUS


def test_llm_schema_has_sku_enum(cat):
    mi, ce = make_llm_models(cat)
    assert list(SKUS) in _enums(mi.model_json_schema())
    assert list(SKUS) in _enums(ce.model_json_schema())


def test_llm_model_rejects_foreign_sku(cat):
    mi, _ = make_llm_models(cat)
    with pytest.raises(ValidationError):
        mi.model_validate(
            {
                "intent": "update_qty",
                "items": [{"mention": "x", "sku_candidates": ["FAKE-1"], "qty": 1}],
                "source": "llm",
            }
        )


def test_validate_skus_rejects_foreign(cat):
    interp = MessageInterpretation(
        intent="update_qty",
        items=[ItemMention(mention="x", sku_candidates=["FAKE-1"], qty=1)],
        source="rules",
    )
    with pytest.raises(ValueError):
        validate_skus(interp, cat)
