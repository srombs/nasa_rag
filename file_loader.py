"""File discovery, ingestion, and JSON caching for text documents."""

import json
from pathlib import Path

from chunkers import chunk_text
from embedder import embed_documents
from models import CorpusChunk, DocumentChunk

CACHE_FILE_NAME = "document_cache.json"
NO_EMBED_CACHE_FILE_NAME = "document_cache_no_embed.json"


def read_file(path: str | Path) -> str:
    """Read a UTF-8 text file into memory."""
    return Path(path).read_text(encoding="utf-8")


def load_and_embed_file(
    path: str | Path, chunk_size: int, overlap_size: int
) -> list[DocumentChunk]:
    """Read a text file, chunk it, embed its chunks, and return the objects."""
    file_path = Path(path)
    chunks = chunk_text(read_file(file_path), chunk_size, overlap_size)
    return embed_documents(chunks, source=file_path.name)


def load_and_chunk_file(
    path: str | Path, chunk_size: int, overlap_size: int
) -> list[CorpusChunk]:
    """Read a text file and return its chunks without creating embeddings."""
    file_path = Path(path)
    chunks = chunk_text(read_file(file_path), chunk_size, overlap_size)
    return [
        CorpusChunk(file_path.name, index, text) for index, text in enumerate(chunks)
    ]


def load_document_cache(path: str | Path) -> dict[str, list[DocumentChunk]]:
    """Load document chunks from a JSON cache, keyed by source file name."""
    cache_path = Path(path)
    if not cache_path.exists():
        return {}

    try:
        cache_data = json.loads(cache_path.read_text(encoding="utf-8"))
        cached_documents = cache_data["documents"]
    except (json.JSONDecodeError, KeyError) as error:
        raise ValueError(f"Invalid document cache: {cache_path}") from error

    if not isinstance(cached_documents, dict):
        raise ValueError(f"Invalid document cache: {cache_path}")

    document_cache: dict[str, list[DocumentChunk]] = {}
    for source, records in cached_documents.items():
        if not isinstance(source, str) or not isinstance(records, list):
            raise ValueError(f"Invalid document cache: {cache_path}")
        document_cache[source] = [
            DocumentChunk.from_cache_record(record)
            for record in records
            if isinstance(record, dict)
        ]
        if len(document_cache[source]) != len(records):
            raise ValueError(f"Invalid document cache: {cache_path}")
    return document_cache


def save_document_cache(
    path: str | Path, document_cache: dict[str, list[DocumentChunk]]
) -> None:
    """Persist chunks and embeddings to a JSON cache, grouped by source name."""
    cache_path = Path(path)
    cache_data = {
        "documents": {
            source: [chunk.to_cache_record() for chunk in chunks]
            for source, chunks in document_cache.items()
        }
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(cache_data, indent=2) + "\n", encoding="utf-8"
    )


def load_no_embed_document_cache(path: str | Path) -> dict[str, list[CorpusChunk]]:
    """Load chunk-only documents from a JSON cache, keyed by source file name."""
    cache_path = Path(path)
    if not cache_path.exists():
        return {}

    try:
        cache_data = json.loads(cache_path.read_text(encoding="utf-8"))
        cached_documents = cache_data["documents"]
    except (json.JSONDecodeError, KeyError) as error:
        raise ValueError(f"Invalid chunk-only cache: {cache_path}") from error

    if not isinstance(cached_documents, dict):
        raise ValueError(f"Invalid chunk-only cache: {cache_path}")

    document_cache: dict[str, list[CorpusChunk]] = {}
    for source, records in cached_documents.items():
        if not isinstance(source, str) or not isinstance(records, list):
            raise ValueError(f"Invalid chunk-only cache: {cache_path}")
        document_cache[source] = [
            CorpusChunk.from_cache_record(record)
            for record in records
            if isinstance(record, dict)
        ]
        if len(document_cache[source]) != len(records):
            raise ValueError(f"Invalid chunk-only cache: {cache_path}")
    return document_cache


def save_no_embed_document_cache(
    path: str | Path, document_cache: dict[str, list[CorpusChunk]]
) -> None:
    """Persist chunk-only documents without embedding vectors."""
    cache_path = Path(path)
    cache_data = {
        "documents": {
            source: [chunk.to_cache_record() for chunk in chunks]
            for source, chunks in document_cache.items()
        }
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(cache_data, indent=2) + "\n", encoding="utf-8"
    )


def load_and_embed_directory(
    directory: str | Path,
    chunk_size: int,
    overlap_size: int,
    cache_path: str | Path | None = None,
) -> list[DocumentChunk]:
    """Load each text file, reusing cached chunks and embeddings by file name."""
    directory_path = Path(directory)
    if not directory_path.is_dir():
        raise NotADirectoryError(f"Text data directory not found: {directory_path}")

    resolved_cache_path = (
        Path(cache_path)
        if cache_path is not None
        else directory_path.parent / "cache" / CACHE_FILE_NAME
    )
    document_cache = load_document_cache(resolved_cache_path)
    document_chunks: list[DocumentChunk] = []
    for file_path in sorted(directory_path.glob("*.txt")):
        cached_chunks = document_cache.get(file_path.name)
        if cached_chunks is None:
            cached_chunks = load_and_embed_file(file_path, chunk_size, overlap_size)
            document_cache[file_path.name] = cached_chunks
        document_chunks.extend(cached_chunks)

    save_document_cache(resolved_cache_path, document_cache)
    return document_chunks


def load_and_chunk_directory(
    directory: str | Path,
    chunk_size: int,
    overlap_size: int,
    cache_path: str | Path | None = None,
) -> list[CorpusChunk]:
    """Chunk each text file and persist source metadata/text without embeddings."""
    directory_path = Path(directory)
    if not directory_path.is_dir():
        raise NotADirectoryError(f"Text data directory not found: {directory_path}")

    resolved_cache_path = (
        Path(cache_path)
        if cache_path is not None
        else directory_path.parent / "cache" / NO_EMBED_CACHE_FILE_NAME
    )
    document_cache = load_no_embed_document_cache(resolved_cache_path)
    document_chunks: list[CorpusChunk] = []
    for file_path in sorted(directory_path.glob("*.txt")):
        cached_chunks = document_cache.get(file_path.name)
        if cached_chunks is None:
            cached_chunks = load_and_chunk_file(file_path, chunk_size, overlap_size)
            document_cache[file_path.name] = cached_chunks
        document_chunks.extend(cached_chunks)

    save_no_embed_document_cache(resolved_cache_path, document_cache)
    return document_chunks
