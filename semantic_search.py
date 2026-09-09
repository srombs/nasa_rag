"""Starter documents for semantic search experiments."""

from collections.abc import Sequence
import argparse
import logging
from math import sqrt
from pathlib import Path

from embedder import embed_documents, embed_query
from models import DocumentChunk
from retriever import DEFAULT_CHUNK_SIZE, DEFAULT_OVERLAP_SIZE, FaissRetriever

TOP_RESULTS = 10
TOP_K = 3


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


def print_ranked_chunks(
    document_chunks: Sequence[DocumentChunk], top_k: int = TOP_RESULTS
) -> None:
    """Print the requested number of ranked chunks without their vectors."""
    if top_k < 0:
        raise ValueError("top_k must be at least zero.")

    for chunk in document_chunks[:top_k]:
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


def load_retriever(
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap_size: int = DEFAULT_OVERLAP_SIZE,
) -> FaissRetriever:
    """Load the FAISS retriever used by command-line and evaluation searches."""
    data_directory = Path(__file__).with_name("data")
    retriever = FaissRetriever(
        data_directory, chunk_size=chunk_size, overlap_size=overlap_size
    )
    retriever.load()
    return retriever


def run_search(
    query: str, retriever: FaissRetriever, top_k: int = TOP_K
) -> list[DocumentChunk]:
    """Run one query through the configured document retriever."""
    return retriever.search(query, top_k=top_k)


def main() -> None:
    """Run a semantic search from the command line."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s | %(name)s | %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="Search the NASA text documents semantically."
    )
    parser.add_argument("query", help="The question or search phrase to embed.")
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help=f"Words per chunk (default: {DEFAULT_CHUNK_SIZE}).",
    )
    parser.add_argument(
        "--overlap-size",
        type=int,
        default=DEFAULT_OVERLAP_SIZE,
        help=f"Overlapping words per chunk (default: {DEFAULT_OVERLAP_SIZE}).",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=TOP_K,
        help=f"Number of chunks to return (default: {TOP_K}).",
    )
    args = parser.parse_args()

    retriever = load_retriever(args.chunk_size, args.overlap_size)
    ranked_chunks = run_search(args.query, retriever, top_k=args.top_k)
    print(f"Question: {args.query}")
    print_ranked_chunks(ranked_chunks, top_k=args.top_k)


if __name__ == "__main__":
    main()
