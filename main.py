"""
main.py

FastAPI application entry point.

Responsibilities:
  - App creation and CORS configuration
  - Startup lifecycle: load schema, build graph, load FAISS index
  - Router registration
  - Health check endpoint
  - Global exception handler

Run locally:
    uvicorn main:app --reload --port 8000

The startup sequence is critical — the pipeline layers depend on
in-memory state (schema cache, graph, FAISS index) being ready before
any request hits the routers. FastAPI's lifespan handler ensures this.
"""

from __future__ import annotations
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import config
from routers import chat, sessions
from schema.loader import load_schema
from schema.graph import build_graph
from schema.embedder import load_faiss_index

# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Startup / Shutdown lifecycle ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs on startup (before first request) and on shutdown.

    Startup order matters:
      1. Load schema from Supabase → populates in-memory cache
      2. Build FK graph from schema → enables join resolution
      3. Load FAISS index from disk → enables schema retrieval

    If FAISS index doesn't exist yet, logs a clear instruction.
    """
    logger.info("=== Text-to-SQL service starting up ===")

    # Step 1: Load schema metadata from Supabase
    logger.info("Step 1/3: Loading schema from Supabase...")
    try:
        schema = load_schema()
        logger.info(f"Schema loaded: {len(schema)} tables.")
    except Exception as e:
        logger.error(f"FATAL: Could not load schema from Supabase: {e}")
        logger.error("Check SUPABASE_URL and SUPABASE_SERVICE_KEY in your .env file.")
        logger.error("Also ensure the get_primary_keys() and get_foreign_keys() RPC functions are created in Supabase.")
        raise

    # Step 2: Build FK graph
    logger.info("Step 2/3: Building schema relationship graph...")
    try:
        build_graph(schema)
        logger.info("Schema graph built.")
    except Exception as e:
        logger.error(f"FATAL: Could not build schema graph: {e}")
        raise

    # Step 3: Load FAISS index
    logger.info("Step 3/3: Loading FAISS index...")
    try:
        load_faiss_index()
        logger.info("FAISS index loaded.")
    except FileNotFoundError as e:
        logger.error(f"FATAL: {e}")
        logger.error(
            "Build the FAISS index first by running:\n"
            "  python -c \"from schema.embedder import build_faiss_index; build_faiss_index()\"\n"
            "This only needs to be done once (or when schema descriptions change)."
        )
        raise
    except Exception as e:
        logger.error(f"FATAL: Could not load FAISS index: {e}")
        raise

    logger.info("=== Startup complete. Ready to serve requests. ===")
    yield

    # Shutdown
    logger.info("=== Text-to-SQL service shutting down. ===")


# ── App creation ──────────────────────────────────────────────────────────────
app = FastAPI(
    title="Text-to-SQL API",
    description=(
        "Production-grade Text-to-SQL system using Azure OpenAI, Supabase, and FAISS. "
        "Converts natural language questions into validated, executable SQL queries "
        "against an e-commerce database."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ── CORS ──────────────────────────────────────────────────────────────────────
# For internal use — adjust origins to match your frontend URL in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # tighten this to specific origins in prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(chat.router)
app.include_router(sessions.router)


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health", tags=["meta"])
async def health_check():
    """
    Simple health check. Returns 200 if the service is up and
    the schema/graph/FAISS are all loaded.
    """
    from schema.loader import get_cached_schema
    from schema.embedder import _faiss_index
    from schema.graph import _graph

    schema_ok = get_cached_schema() is not None
    graph_ok  = len(_graph) > 0
    faiss_ok  = _faiss_index is not None

    status = "ok" if all([schema_ok, graph_ok, faiss_ok]) else "degraded"

    return {
        "status":      status,
        "schema_loaded": schema_ok,
        "graph_built":   graph_ok,
        "faiss_loaded":  faiss_ok,
    }


# ── Global exception handler ──────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.url}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred. Please try again."},
    )


# ── Dev entrypoint ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=config.APP_ENV == "development",
        log_level=config.LOG_LEVEL.lower(),
    )