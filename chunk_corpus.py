"""Create a chunk-only cache for every text file in the local corpus."""

import argparse
from pathlib import Path

from file_loader import NO_EMBED_CACHE_FILE_NAME, load_and_chunk_directory
from retriever import DEFAULT_CHUNK_SIZE, DEFAULT_OVERLAP_SIZE


def no_embed_cache_file_name(chunk_size: int, overlap_size: int) -> str:
    """Return the chunk-only cache name for the requested chunk configuration."""
    if (
        chunk_size == DEFAULT_CHUNK_SIZE
        and overlap_size == DEFAULT_OVERLAP_SIZE
    ):
        return NO_EMBED_CACHE_FILE_NAME
    return f"document_cache_{chunk_size}_{overlap_size}_no_embed.json"


def main() -> None:
    """Chunk the local corpus and save the resulting no-embedding JSON cache."""
    parser = argparse.ArgumentParser(
        description="Chunk the NASA corpus without creating embeddings."
    )
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
    args = parser.parse_args()

    data_directory = Path(__file__).with_name("data")
    cache_path = data_directory.parent / "cache" / no_embed_cache_file_name(
        args.chunk_size, args.overlap_size
    )
    chunks = load_and_chunk_directory(
        data_directory,
        chunk_size=args.chunk_size,
        overlap_size=args.overlap_size,
        cache_path=cache_path,
    )
    print(f"Saved {len(chunks)} unembedded chunks to {cache_path}.")


if __name__ == "__main__":
    main()
