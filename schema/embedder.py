"""
schema/embedder.py

Embeds table+column descriptions into a FAISS index for semantic retrieval.
Builds the index from SCHEMA_DESCRIPTIONS in schema/loader.py.

Run build_faiss_index() once (or whenever schema descriptions change):
    python -c "from schema.embedder import build_faiss_index; build_faiss_index()"

At runtime, load_faiss_index() is called once at startup.
"""

from __future__ import annotations
import os
import json
import logging
import numpy as np
import faiss
from openai import AzureOpenAI

import config
from schema.loader import SCHEMA_DESCRIPTIONS

logger = logging.getLogger(__name__)

# ── Azure OpenAI client for embeddings ──────────────────────────────────────
_embedding_client = AzureOpenAI(
    api_key=config.AZURE_OPENAI_API_KEY,
    azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
    api_version=config.AZURE_OPENAI_API_VERSION,
)

# ── FAISS index + metadata storage ──────────────────────────────────────────
_faiss_index: faiss.IndexFlatIP | None = None       # Inner product (cosine after normalisation)
_index_metadata: list[dict]            = []          # Parallel list: index position → table/description info


def _embed(texts: list[str]) -> np.ndarray:
    """
    Embeds a list of texts using Azure OpenAI embeddings.
    Returns a float32 numpy array of shape (len(texts), EMBEDDING_DIMENSION).
    Vectors are L2-normalised so that inner product = cosine similarity.
    """
    response = _embedding_client.embeddings.create(
        model=config.EMBEDDING_MODEL,
        input=texts,
    )
    vectors = np.array(
        [item.embedding for item in response.data],
        dtype=np.float32
    )
    # Normalise for cosine similarity via inner product
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1e-10, norms)
    return vectors / norms


def build_faiss_index() -> None:
    """
    Builds the FAISS index from SCHEMA_DESCRIPTIONS and saves it to disk.
    Run this once at setup and whenever table descriptions change.

    Each table gets one embedding entry built from:
      - The table description (with aliases)
      - All column names and their descriptions concatenated

    This gives the retriever a rich semantic representation of each table.
    """
    logger.info("Building FAISS index from schema descriptions...")

    texts: list[str]    = []
    metadata: list[dict] = []

    for table_name, table_data in SCHEMA_DESCRIPTIONS.items():
        # Build a rich text blob for this table
        col_texts = []
        for col_name, col_desc in table_data.get("columns", {}).items():
            col_texts.append(f"{col_name}: {col_desc}")

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

    # Embed all table descriptions
    vectors = _embed(texts)

    # Build FAISS index (Inner Product on normalised vectors = cosine similarity)
    index = faiss.IndexFlatIP(config.EMBEDDING_DIMENSION)
    index.add(vectors)

    # Save index and metadata to disk
    os.makedirs(os.path.dirname(config.FAISS_INDEX_PATH), exist_ok=True)
    faiss.write_index(index, config.FAISS_INDEX_PATH)

    metadata_path = config.FAISS_INDEX_PATH.replace(".index", "_metadata.json")
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    logger.info(f"FAISS index built: {len(texts)} tables indexed → {config.FAISS_INDEX_PATH}")


def load_faiss_index() -> None:
    """
    Loads the FAISS index and metadata from disk into memory.
    Called once at application startup.
    """
    global _faiss_index, _index_metadata

    if not os.path.exists(config.FAISS_INDEX_PATH):
        raise FileNotFoundError(
            f"FAISS index not found at {config.FAISS_INDEX_PATH}. "
            "Run build_faiss_index() first: "
            "python -c \"from schema.embedder import build_faiss_index; build_faiss_index()\""
        )

    _faiss_index = faiss.read_index(config.FAISS_INDEX_PATH)

    metadata_path = config.FAISS_INDEX_PATH.replace(".index", "_metadata.json")
    with open(metadata_path, "r") as f:
        _index_metadata = json.load(f)

    logger.info(f"FAISS index loaded: {_faiss_index.ntotal} tables.")


def search_tables(query: str, top_k: int | None = None) -> list[dict]:
    """
    Given a natural language query (or list of entities joined as a string),
    returns the top-k most relevant tables with their similarity scores.

    Returns:
        List of dicts: [{"table_name": ..., "description": ..., "score": float}, ...]
        Ordered by descending similarity score.
    """
    if _faiss_index is None:
        raise RuntimeError("FAISS index not loaded. Call load_faiss_index() at startup.")

    k = top_k or config.TOP_K_TABLES
    query_vector = _embed([query])

    scores, indices = _faiss_index.search(query_vector, k)

    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0:
            continue  # FAISS returns -1 for empty slots
        if score < config.SCHEMA_SIM_THRESHOLD:
            logger.debug(f"Table {_index_metadata[idx]['table_name']} below similarity threshold ({score:.3f})")
            continue
        results.append({
            "table_name":  _index_metadata[idx]["table_name"],
            "description": _index_metadata[idx]["description"],
            "score":       float(score),
        })

    return results