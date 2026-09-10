"""FAISS vector-index construction for document embeddings."""

from collections.abc import Sequence
import logging
from pathlib import Path

import faiss
import numpy as np

from models import DocumentChunk


LOGGER = logging.getLogger(__name__)


class VectorStoreError(RuntimeError):
    """Raised when a FAISS vector-store operation cannot be completed."""


def validate_index(index: faiss.Index, chunks: Sequence[DocumentChunk]) -> None:
    """Ensure every indexed vector has corresponding chunk metadata."""
    if index.ntotal != len(chunks):
        raise VectorStoreError(
            f"Index contains {index.ntotal} vectors "
            f"but metadata contains {len(chunks)} chunks."
        )


def _prepare_matrix(matrix: np.ndarray, label: str) -> np.ndarray:
    """Return a validated, contiguous float32 embedding matrix."""
    prepared_matrix = np.array(matrix, dtype=np.float32, order="C", copy=True)
    if prepared_matrix.ndim != 2:
        raise ValueError(f"{label} must have two dimensions.")
    if prepared_matrix.shape[0] == 0:
        raise ValueError(f"{label} cannot be empty.")
    if prepared_matrix.shape[1] == 0:
        raise ValueError(f"{label} vectors must have at least one dimension.")
    if not np.isfinite(prepared_matrix).all():
        raise ValueError(f"{label} must contain only finite values.")
    if np.any(np.linalg.norm(prepared_matrix, axis=1) == 0):
        raise ValueError(f"{label} cannot contain zero vectors.")
    return prepared_matrix


def create_index(matrix: np.ndarray) -> faiss.IndexFlatIP:
    """Create an inner-product FAISS index containing every matrix row."""
    prepared_matrix = _prepare_matrix(matrix, "Embedding matrix")
    try:
        index = faiss.IndexFlatIP(prepared_matrix.shape[1])
        faiss.normalize_L2(prepared_matrix)
        index.add(prepared_matrix)
        return index
    except Exception as error:
        LOGGER.exception("Failed to create FAISS index.")
        raise VectorStoreError("Unable to create FAISS index.") from error


def load_or_create_index(
    matrix: np.ndarray, cache_path: str | Path
) -> faiss.IndexFlatIP:
    """Load a compatible FAISS index cache or create and persist a new one."""
    prepared_matrix = _prepare_matrix(matrix, "Embedding matrix")
    index_path = Path(cache_path)
    if index_path.exists():
        try:
            cached_index = faiss.read_index(str(index_path))
        except RuntimeError:
            LOGGER.warning("Ignoring unreadable FAISS index cache: %s", index_path)
        else:
            if (
                cached_index.ntotal == prepared_matrix.shape[0]
                and cached_index.d == prepared_matrix.shape[1]
            ):
                LOGGER.info("Loaded FAISS index cache from %s.", index_path)
                return cached_index
            LOGGER.info("Rebuilding incompatible FAISS index cache: %s", index_path)

    index = create_index(prepared_matrix)
    try:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(index, str(index_path))
    except Exception as error:
        LOGGER.exception("Failed to write FAISS index cache: %s", index_path)
        raise VectorStoreError("Unable to write FAISS index cache.") from error
    LOGGER.info("Wrote FAISS index cache to %s.", index_path)
    return index


def create_query_matrix(query_embedding: Sequence[float]) -> np.ndarray:
    """Return a one-row, L2-normalized float32 matrix for FAISS search."""
    query_matrix = _prepare_matrix(
        np.array([query_embedding], dtype=np.float32), "Query embedding"
    )
    try:
        faiss.normalize_L2(query_matrix)
        return query_matrix
    except Exception as error:
        LOGGER.exception("Failed to normalize query embedding.")
        raise VectorStoreError("Unable to normalize query embedding.") from error
