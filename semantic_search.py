"""Starter documents for semantic search experiments."""

from collections.abc import Sequence
import argparse
from dataclasses import dataclass
from math import sqrt
from pathlib import Path


EMBEDDING_MODEL = "text-embedding-3-small"
TOP_RESULTS = 10


@dataclass
class DocumentChunk:
    """A text chunk and the vector used to search it."""

    source: str
    chunk_index: int
    text: str
    embed: list[float]
    similarity: float | None = None


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


def read_file(path: str | Path) -> str:
    """Read a UTF-8 text file into memory."""
    return Path(path).read_text(encoding="utf-8")


def chunk_text(text: str, chunk_size: int, overlap_size: int) -> list[str]:
    """Split text into word-based chunks with overlapping words."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero.")
    if overlap_size < 0 or overlap_size >= chunk_size:
        raise ValueError("overlap_size must be at least zero and less than chunk_size.")

    words = text.split()
    step_size = chunk_size - overlap_size
    results = []
    for start in range(0, len(words), step_size):
        chunk = words[start : start + chunk_size]
        if not chunk:
            break
        results.append(" ".join(chunk))
        if start + chunk_size >= len(words):
            break
    print(f"Created {len(results)} chunks.")
    return results




def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    """Return one embedding vector for each supplied text, in input order.

    The OpenAI SDK reads the API key from the ``OPENAI_API_KEY`` environment
    variable. Each non-empty call sends the texts to the API.
    """
    input_texts = list(texts)
    if not input_texts:
        return []

    from openai import OpenAI

    response = OpenAI().embeddings.create(
        model=EMBEDDING_MODEL,
        input=input_texts,
    )
    embeddings = [
        item.embedding for item in sorted(response.data, key=lambda item: item.index)
    ]
    return embeddings


def embed_documents(texts: Sequence[str], source: str) -> list[DocumentChunk]:
    """Embed text strings and store each returned vector with its chunk data."""
    text_list = list(texts)
    embeddings = embed_texts(text_list)
    return [
        DocumentChunk(
            source=source,
            chunk_index=index,
            text=text,
            embed=embedding,
        )
        for index, (text, embedding) in enumerate(
            zip(text_list, embeddings, strict=True)
        )
    ]


def load_and_embed_file(
    path: str | Path, chunk_size: int, overlap_size: int
) -> list[DocumentChunk]:
    """Read a text file, chunk it, embed its chunks, and return the objects."""
    file_path = Path(path)
    chunks = chunk_text(read_file(file_path), chunk_size, overlap_size)
    return embed_documents(chunks, source=file_path.name)


def embed_query(query: str) -> list[float]:
    """Embed one search query."""
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


def score_document_chunks(
    query_embedding: Sequence[float], document_chunks: Sequence[DocumentChunk]
) -> list[DocumentChunk]:
    """Store each chunk's similarity to the query and return ranked chunks."""
    for document_chunk in document_chunks:
        document_chunk.similarity = cosine_similarity(
            query_embedding, document_chunk.embed
        )
    return sorted(
        document_chunks,
        key=lambda chunk: chunk.similarity if chunk.similarity is not None else -1.0,
        reverse=True,
    )


def print_ranked_chunks(document_chunks: Sequence[DocumentChunk]) -> None:
    """Print the top ranked chunks without exposing their embedding vectors."""
    for chunk in document_chunks[:TOP_RESULTS]:
        print(
            f"{chunk.similarity:.4f} | {chunk.source} | "
            f"chunk {chunk.chunk_index} | {chunk.text}"
        )


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
    document_chunks = embed_documents(documents, source="sample_documents")
    ranked_chunks = score_document_chunks(embed_query(query), document_chunks)
    print_ranked_chunks(ranked_chunks)
    return [(chunk.text, chunk.similarity) for chunk in ranked_chunks]


def main() -> None:
    """Run a semantic search from the command line."""
    parser = argparse.ArgumentParser(
        description="Search the Hubble text document semantically."
    )
    parser.add_argument("query", help="The question or search phrase to embed.")
    args = parser.parse_args()

    hubble_path = Path(__file__).with_name("hubble.txt")
    document_chunks = load_and_embed_file(hubble_path, chunk_size=100, overlap_size=20)
    ranked_chunks = score_document_chunks(embed_query(args.query), document_chunks)
    print_ranked_chunks(ranked_chunks)


if __name__ == "__main__":
    main()
