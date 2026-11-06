import re
import unicodedata
from difflib import get_close_matches

from quote_engine.domain.catalog import Catalog

_MIN_TOKEN = 3  # shorter alias tokens ("de", "x") are noise
_FUZZY_MIN = 5  # typo tolerance only on tokens at least this long


def _tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text.lower())
    return re.findall(r"[a-z]+", "".join(c for c in text if not unicodedata.combining(c)))


def relevant_skus(catalog: Catalog, texts: list[str]) -> tuple[str, ...]:
    """SKUs of every family the texts talk about (typo tolerant); full catalog if none match."""
    family_words: dict[str, set[str]] = {}
    for item in catalog.items.values():
        words = family_words.setdefault(str(item.attrs.get("family", item.sku)), set())
        words.update(t for a in item.aliases for t in _tokens(a) if len(t) >= _MIN_TOKEN)
    tokens = {t for text in texts for t in _tokens(text)}

    def hit(words: set[str]) -> bool:
        return any(
            t in words or (len(t) >= _FUZZY_MIN and get_close_matches(t, words, 1, 0.85))
            for t in tokens
        )

    hits = {f for f, words in family_words.items() if hit(words)}
    if not hits:
        return catalog.skus
    return tuple(s for s, i in catalog.items.items() if str(i.attrs.get("family", s)) in hits)
