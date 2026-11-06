import re
import unicodedata


def norm(text: str) -> str:
    """Lowercase, strip accents, decimal comma to dot, collapse whitespace."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"(?<=\d),(?=\d)", ".", text)
    return re.sub(r"\s+", " ", text).strip()
