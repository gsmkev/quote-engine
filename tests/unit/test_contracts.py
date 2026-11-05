import re

import pytest
from pydantic import ValidationError

from quote_engine.domain.catalog import Catalog
from quote_engine.domain.interpretation import (
    ExtractedLine,
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


def test_catalog_contains_original_skus(cat):
    assert set(SKUS) <= set(cat.skus)


def test_llm_schema_has_sku_enum(cat):
    mi, ce = make_llm_models(cat)
    assert list(cat.skus) in _enums(mi.model_json_schema())
    assert list(cat.skus) in _enums(ce.model_json_schema())


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


def test_catalog_original_skus_keep_description(cat: Catalog) -> None:
    assert cat.items["ALFBTC-013-320100"].description == "Lona Frontlit BTE 13 3.20x100"
    assert cat.items["ALMCLC-0909-320100"].description == "Lona Mesh CLN 9x9 3.20x100"
    assert cat.items["AVMICS-1A-137050"].description == "Vinil Adhesivo Microperforado 1.37x50"
    assert cat.items["ARACBL-03-122244"].description == "Acrilico Blanco 3mm 1.22x2.44"


def test_catalog_size_and_sku_shape(cat: Catalog) -> None:
    assert 35 <= len(cat.items) <= 45
    assert all(re.fullmatch(r"[A-Z]{6}-[0-9A-Z]{2,4}-\d{6}", s) for s in cat.skus)


def test_catalog_attrs_unique_and_family_present(cat: Catalog) -> None:
    keys = ("family", "type", "width_m", "length_m", "thickness_mm", "color")
    tuples = [tuple(i.attrs.get(k) for k in keys) for i in cat.items.values()]
    assert all("family" in i.attrs for i in cat.items.values())
    assert len(set(tuples)) == len(tuples)


def test_catalog_defaults_are_frontlit_lonas(cat: Catalog) -> None:
    assert "ALFBTC-013-320100" in cat.defaults
    assert cat.defaults == cat.with_attr("type", "frontlit")
    assert cat.with_attr("type", "blackout") and not cat.defaults & cat.with_attr(
        "type", "blackout"
    )
    assert not cat.defaults & cat.with_attr("type", "mesh")


def test_lona_alias_on_every_lona_sku(cat: Catalog) -> None:
    lonas = cat.with_attr("family", "lona")
    assert len(lonas) >= 10
    assert all("lona" in cat.items[s].aliases for s in lonas)


def test_not_in_catalog_mention_needs_no_candidates():
    m = ItemMention(mention="lona blackout", sku_candidates=[], in_catalog=False)
    assert m.sku_candidates == [] and not m.in_catalog


def test_in_catalog_mention_requires_candidates():
    with pytest.raises(ValidationError):
        ItemMention(mention="x", sku_candidates=[])


def test_not_in_catalog_mention_rejects_candidates():
    with pytest.raises(ValidationError):
        ItemMention(mention="x", sku_candidates=[SKUS[0]], in_catalog=False)


def test_extracted_line_not_in_catalog_has_no_sku():
    line = ExtractedLine(sku=None, qty=3, evidence="e", in_catalog=False)
    assert line.sku is None
    with pytest.raises(ValidationError):
        ExtractedLine(sku=None, qty=3, evidence="e")
    with pytest.raises(ValidationError):
        ExtractedLine(sku=SKUS[0], qty=3, evidence="e", in_catalog=False)


def test_llm_models_allow_not_in_catalog_but_not_foreign(cat):
    mi, ce = make_llm_models(cat)
    ok = mi.model_validate(
        {
            "intent": "add_items",
            "items": [{"mention": "x", "sku_candidates": [], "in_catalog": False, "qty": 1}],
            "source": "llm",
        }
    )
    assert ok.items[0].sku_candidates == []
    assert ce.model_validate(
        {"items": [{"sku": None, "qty": 2, "evidence": "e", "in_catalog": False}]}
    )
    with pytest.raises(ValidationError):
        ce.model_validate({"items": [{"sku": "FAKE-1", "qty": 2, "evidence": "e"}]})
