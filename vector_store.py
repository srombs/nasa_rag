"""FAISS vector-index construction for document embeddings."""

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
