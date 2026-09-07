"""FAISS vector-index construction for document embeddings."""

from collections.abc import Sequence
import logging
from pathlib import Path

import faiss
import numpy as np


LOGGER = logging.getLogger(__name__)


def create_index(matrix: np.ndarray) -> faiss.IndexFlatIP:
    """Create an inner-product FAISS index containing every matrix row."""
    if matrix.ndim != 2:
        raise ValueError("Embedding matrix must have two dimensions.")
    if matrix.shape[0] == 0:
        raise ValueError("Cannot create a FAISS index without document embeddings.")
    if matrix.shape[1] == 0:
        raise ValueError("Embedding vectors must have at least one dimension.")

    matrix = np.ascontiguousarray(matrix, dtype=np.float32)
    dimension = matrix.shape[1]
    index = faiss.IndexFlatIP(dimension)
    faiss.normalize_L2(matrix)
    index.add(matrix)
    return index


def load_or_create_index(
    matrix: np.ndarray, cache_path: str | Path
) -> faiss.IndexFlatIP:
    """Load a compatible FAISS index cache or create and persist a new one."""
    index_path = Path(cache_path)
    if index_path.exists():
        try:
            cached_index = faiss.read_index(str(index_path))
        except RuntimeError:
            LOGGER.warning("Ignoring unreadable FAISS index cache: %s", index_path)
        else:
            if (
                cached_index.ntotal == matrix.shape[0]
                and cached_index.d == matrix.shape[1]
            ):
                LOGGER.info("Loaded FAISS index cache from %s.", index_path)
                return cached_index
            LOGGER.info("Rebuilding incompatible FAISS index cache: %s", index_path)

    index = create_index(matrix)
    faiss.write_index(index, str(index_path))
    LOGGER.info("Wrote FAISS index cache to %s.", index_path)
    return index


def create_query_matrix(query_embedding: Sequence[float]) -> np.ndarray:
    """Return a one-row, L2-normalized float32 matrix for FAISS search."""
    query_matrix = np.array([query_embedding], dtype=np.float32)
    if query_matrix.shape[1] == 0:
        raise ValueError("Query embedding must have at least one dimension.")

    faiss.normalize_L2(query_matrix)
    return query_matrix
