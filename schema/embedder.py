"""
schema/embedder.py

Embeds table+column descriptions into a FAISS index for semantic retrieval.
Uses Google's text-embedding-004 model (768 dimensions) instead of Azure OpenAI.

Google's text-embedding-004 is a strong general-purpose embedding model,
well-suited for semantic search over structured schema descriptions.

Run build_faiss_index() once at setup:
    python -c "from schema.embedder import build_faiss_index; build_faiss_index()"

At runtime, load_faiss_index() is called once at startup via main.py lifespan.
"""

from __future__ import annotations
import os
import json
import logging
import numpy as np
import faiss
import google.generativeai as genai

import config
from schema.loader import SCHEMA_DESCRIPTIONS

logger = logging.getLogger(__name__)

# ── Google Generative AI client ───────────────────────────────────────────────
genai.configure(api_key=config.GOOGLE_API_KEY)

# Google's text-embedding-004 — 768 dimensions, best general-purpose model
_GOOGLE_EMBEDDING_MODEL = "models/gemini-embedding-001"

# ── FAISS index + metadata storage ───────────────────────────────────────────
_faiss_index: faiss.IndexFlatIP | None = None
_index_metadata: list[dict]            = []


def _embed(texts: list[str]) -> np.ndarray:
    """
    Embeds a list of texts using Google text-embedding-004.
    Returns a float32 numpy array of shape (len(texts), 768).
    Vectors are L2-normalised so inner product == cosine similarity.

    Google's embed_content supports batching up to 100 texts at once,
    so we process in chunks of 100 to stay within limits.
    """
    all_vectors = []
    chunk_size  = 100

    for i in range(0, len(texts), chunk_size):
        chunk = texts[i : i + chunk_size]
        response = genai.embed_content(
            model=_GOOGLE_EMBEDDING_MODEL,
            content=chunk,
            task_type="retrieval_document",   # optimised for document-side embeddings
        )
        all_vectors.extend(response["embedding"])

    vectors = np.array(all_vectors, dtype=np.float32)

    # L2-normalise for cosine similarity via inner product
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1e-10, norms)
    return vectors / norms


def _embed_query(text: str) -> np.ndarray:
    """
    Embeds a single query string using task_type='retrieval_query'.
    Google recommends using different task types for documents vs queries —
    this gives better retrieval accuracy than using the same task type for both.
    """
    response = genai.embed_content(
        model=_GOOGLE_EMBEDDING_MODEL,
        content=text,
        task_type="retrieval_query",   # optimised for query-side embeddings
    )
    vector = np.array(response["embedding"], dtype=np.float32).reshape(1, -1)

    # Normalise
    norm = np.linalg.norm(vector)
    if norm > 0:
        vector = vector / norm
    return vector


def build_faiss_index() -> None:
    """
    Builds the FAISS index from SCHEMA_DESCRIPTIONS and saves to disk.
    Run once at setup and whenever table descriptions change.

    Each table gets one embedding built from its full description + all column descriptions.
    """
    logger.info("Building FAISS index using Google text-embedding-004...")

    texts:    list[str]  = []
    metadata: list[dict] = []

    for table_name, table_data in SCHEMA_DESCRIPTIONS.items():
        col_texts = [
            f"{col_name}: {col_desc}"
            for col_name, col_desc in table_data.get("columns", {}).items()
        ]
        full_text = (
            f"Table: {table_name}\n"
            f"Description: {table_data['description']}\n"
            f"Columns:\n" + "\n".join(col_texts)
        )
        texts.append(full_text)
        metadata.append({
            "table_name":  table_name,
            "description": table_data["description"],
            "text":        full_text,
        })

    # Embed all table descriptions (task_type=retrieval_document)
    vectors = _embed(texts)

    # Confirm dimension matches config
    actual_dim = vectors.shape[1]
    if actual_dim != config.EMBEDDING_DIMENSION:
        logger.warning(
            f"Embedding dimension mismatch: got {actual_dim}, "
            f"config says {config.EMBEDDING_DIMENSION}. "
            f"Update EMBEDDING_DIMENSION in config.py to {actual_dim}."
        )
        # Auto-correct so the index doesn't break
        import config as cfg_module
        cfg_module.EMBEDDING_DIMENSION = actual_dim

    # Build FAISS flat inner product index
    index = faiss.IndexFlatIP(actual_dim)
    index.add(vectors)

    # Save to disk
    os.makedirs(os.path.dirname(config.FAISS_INDEX_PATH), exist_ok=True)
    faiss.write_index(index, config.FAISS_INDEX_PATH)

    metadata_path = config.FAISS_INDEX_PATH.replace(".index", "_metadata.json")
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    logger.info(
        f"FAISS index built: {len(texts)} tables → {config.FAISS_INDEX_PATH} "
        f"(dim={actual_dim})"
    )


def load_faiss_index() -> None:
    """
    Loads the FAISS index and metadata from disk into memory.
    Called once at startup via main.py lifespan.
    """
    global _faiss_index, _index_metadata

    if not os.path.exists(config.FAISS_INDEX_PATH):
        raise FileNotFoundError(
            f"FAISS index not found at {config.FAISS_INDEX_PATH}. "
            "Build it first:\n"
            "  python -c \"from schema.embedder import build_faiss_index; build_faiss_index()\""
        )

    _faiss_index = faiss.read_index(config.FAISS_INDEX_PATH)

    metadata_path = config.FAISS_INDEX_PATH.replace(".index", "_metadata.json")
    with open(metadata_path, "r") as f:
        _index_metadata = json.load(f)

    logger.info(f"FAISS index loaded: {_faiss_index.ntotal} tables (dim={_faiss_index.d}).")


def search_tables(query: str, top_k: int | None = None) -> list[dict]:
    """
    Searches the FAISS index for tables relevant to the query.

    Uses task_type='retrieval_query' for the query embedding to get
    better asymmetric retrieval (query vs document embedding types).

    Returns list of dicts ordered by descending similarity score:
        [{"table_name": ..., "description": ..., "score": float}, ...]
    """
    if _faiss_index is None:
        raise RuntimeError("FAISS index not loaded. Call load_faiss_index() at startup.")

    k = top_k or config.TOP_K_TABLES
    query_vector = _embed_query(query)

    scores, indices = _faiss_index.search(query_vector, k)

    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0:
            continue
        if score < config.SCHEMA_SIM_THRESHOLD:
            logger.debug(
                f"Table '{_index_metadata[idx]['table_name']}' below similarity "
                f"threshold ({score:.3f} < {config.SCHEMA_SIM_THRESHOLD})"
            )
            continue
        results.append({
            "table_name":  _index_metadata[idx]["table_name"],
            "description": _index_metadata[idx]["description"],
            "score":       float(score),
        })

    return results