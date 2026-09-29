"""Create a chunk-only cache for every text file in the local corpus."""

import argparse
from pathlib import Path

from file_loader import load_and_chunk_directory, no_embed_cache_file_name
from retriever import DEFAULT_CHUNK_SIZE, DEFAULT_OVERLAP_SIZE


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
    cache_path = data_directory.parent / "cache" / "corpus" / no_embed_cache_file_name(
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
