"""Word tokenization for BM25 retrieval."""

import re


TOKEN_PATTERN = re.compile(r"\b\w+\b")


def tokenize_text(text: str) -> list[str]:
    """Return lowercase word tokens, retaining stop words and duplicates."""
    return TOKEN_PATTERN.findall(text.lower())
