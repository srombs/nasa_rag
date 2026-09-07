"""FAISS vector-index construction for document embeddings."""

from collections.abc import Sequence

import faiss
import numpy as np


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


def create_query_matrix(query_embedding: Sequence[float]) -> np.ndarray:
    """Return a one-row, L2-normalized float32 matrix for FAISS search."""
    query_matrix = np.array([query_embedding], dtype=np.float32)
    if query_matrix.shape[1] == 0:
        raise ValueError("Query embedding must have at least one dimension.")

    faiss.normalize_L2(query_matrix)
    return query_matrix
