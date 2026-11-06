import json
from pathlib import Path

import pytest

from quote_engine.domain.catalog import Catalog
from quote_engine.domain.catalog_filter import relevant_skus

ROOT = Path(__file__).parent.parent.parent


def families(catalog: Catalog, texts: list[str]) -> set[str]:
    return {str(catalog.items[s].attrs["family"]) for s in relevant_skus(catalog, texts)}


@pytest.mark.parametrize(
    ("texts", "expected"),
    [
        (["20 rollos lona 3.20 x 100, 5 de mesh"], {"lona"}),
        (["2 acrilcos blancos"], {"acrilico", "vinil"}),  # "blanco" is also a vinil colour
        (["cotizame 3 sintras"], {"pvc"}),
        (["Necesito TINTA ecosolvente y un Vinilo"], {"tinta", "vinil"}),
        (["quiero 2 de acrílico"], {"acrilico"}),
    ],
)
def test_families(catalog, texts, expected):
    assert families(catalog, texts) == expected


def test_no_match_returns_full_catalog(catalog):
    assert relevant_skus(catalog, ["hola que tal"]) == catalog.skus


def test_catalog_order_preserved(catalog):
    skus = relevant_skus(catalog, ["vinil y lona"])
    assert skus == tuple(s for s in catalog.skus if s in skus)


def test_phase1_challenge_conversation(catalog):
    p = json.loads((ROOT / "fixtures/challenge/phase1.json").read_text())
    skus = relevant_skus(catalog, [m["text"] for m in p["conversation_history"]])
    assert {"ALFBTC-013-320100", "ALMCLC-0909-320100", "AVMICS-1A-137050"} <= set(skus)
    assert len(skus) < len(catalog.skus)
