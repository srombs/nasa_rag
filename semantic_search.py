"""Starter documents for semantic search experiments."""

from collections.abc import Sequence
import argparse
import json
from math import sqrt
from pathlib import Path


EMBEDDING_MODEL = "text-embedding-3-small"
CACHE_FILE = Path("embeddings.txt")
TOP_RESULTS = 3

# documents = [
#     "Perseverance landed in Jezero Crater on Mars in February 2021.",
#     "The James Webb Space Telescope observes the universe primarily in infrared light.",
#     "Apollo 11 landed the first humans on the Moon in July 1969.",
#     "Cassini studied Saturn, its rings, and its moons before ending its mission in 2017.",
#     "The Curiosity rover landed in Gale Crater on Mars in August 2012.",
#     "The Hubble Space Telescope observes stars, galaxies, and other astronomical objects from orbit around Earth.",
#     "Voyager 1 launched in 1977 and became the first human-made spacecraft to enter interstellar space.",
#     "The Ingenuity helicopter performed the first powered controlled flight on another planet while operating on Mars.",
#     "The Artemis program aims to return humans to the Moon and establish a foundation for future missions to Mars.",
#     "The Parker Solar Probe studies the Sun's outer atmosphere and has traveled closer to the Sun than any previous spacecraft."
# ]

documents = [
    "Perseverance landed in Jezero Crater.",
    "The Mars 2020 rover touched down inside an ancient Martian lake bed.",
    "Jezero is a crater on Mars.",
    "Apollo astronauts landed on the Moon.",
    "NASA landed a spacecraft."
]




def embed_texts(
    texts: Sequence[str], cache_path: Path = CACHE_FILE
) -> list[list[float]]:
    """Return one embedding vector for each supplied text, in input order.

    The OpenAI SDK reads the API key from the ``OPENAI_API_KEY`` environment
    variable. An existing cache is reused when it was created for the same
    input texts and model.
    """
    input_texts = list(texts)
    if not input_texts:
        return []

    cached_embeddings = _read_cache(cache_path, input_texts)
    if cached_embeddings is not None:
        return cached_embeddings

    from openai import OpenAI

    response = OpenAI().embeddings.create(
        model=EMBEDDING_MODEL,
        input=input_texts,
    )
    embeddings = [
        item.embedding for item in sorted(response.data, key=lambda item: item.index)
    ]
    _write_cache(cache_path, input_texts, embeddings)
    return embeddings


def embed_query(query: str) -> list[float]:
    """Embed one search query without reading or writing the document cache."""
    if not query:
        raise ValueError("Query text cannot be empty.")

    from openai import OpenAI

    response = OpenAI().embeddings.create(
        model=EMBEDDING_MODEL,
        input=query,
    )
    return response.data[0].embedding


def cosine_similarity(vector_a: Sequence[float], vector_b: Sequence[float]) -> float:
    """Calculate cosine similarity between two equally sized vectors."""
    if len(vector_a) != len(vector_b):
        raise ValueError("Vectors must have the same number of dimensions.")

    dot_product = sum(a * b for a, b in zip(vector_a, vector_b, strict=True))
    magnitude_a = sqrt(sum(value * value for value in vector_a))
    magnitude_b = sqrt(sum(value * value for value in vector_b))
    if magnitude_a == 0 or magnitude_b == 0:
        raise ValueError("Cosine similarity is undefined for a zero vector.")
    return dot_product / (magnitude_a * magnitude_b)


def compare_query_to_documents(
    query_embedding: Sequence[float],
    document_embeddings: Sequence[Sequence[float]],
    document_texts: Sequence[str] = documents,
) -> list[tuple[str, float]]:
    """Score every document, then print the three best matches."""
    if len(document_embeddings) != len(document_texts):
        raise ValueError("Each document must have exactly one embedding.")

    results = [
        (document, cosine_similarity(query_embedding, embedding))
        for document, embedding in zip(document_texts, document_embeddings, strict=True)
    ]
    results.sort(key=lambda result: result[1], reverse=True)
    for document, score in results[:TOP_RESULTS]:
        print(f"{score:.4f}  {document}")
    return results


def search(query: str) -> list[tuple[str, float]]:
    """Embed a query, score it against the documents, and print the results."""
    return compare_query_to_documents(embed_query(query), embed_texts(documents))


def main() -> None:
    """Run a semantic search from the command line."""
    parser = argparse.ArgumentParser(
        description="Search the sample NASA documents semantically."
    )
    parser.add_argument("query", help="The question or search phrase to embed.")
    args = parser.parse_args()
    search(args.query)


def _read_cache(
    cache_path: Path, input_texts: list[str]
) -> list[list[float]] | None:
    """Return compatible cached embeddings, if available."""
    if not cache_path.is_file():
        return None

    try:
        cached_data = json.loads(cache_path.read_text())
    except json.JSONDecodeError as error:
        raise ValueError(f"Embedding cache is not valid JSON: {cache_path}") from error

    if (
        cached_data.get("model") != EMBEDDING_MODEL
        or cached_data.get("texts") != input_texts
    ):
        return None

    embeddings = cached_data.get("embeddings")
    if not isinstance(embeddings, list) or len(embeddings) != len(input_texts):
        return None
    return embeddings


def _write_cache(
    cache_path: Path, texts: list[str], embeddings: list[list[float]]
) -> None:
    """Save embeddings in a readable text file for later reuse."""
    cache_path.write_text(
        json.dumps(
            {"model": EMBEDDING_MODEL, "texts": texts, "embeddings": embeddings},
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
