"""
config.py
All environment variables and application-wide settings.
Copy .env.example to .env and fill in your values.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Azure OpenAI (LLM only — used for query understanding + SQL generation) ──
AZURE_OPENAI_API_KEY      = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_ENDPOINT     = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_DEPLOYMENT   = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
AZURE_OPENAI_API_VERSION  = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")

# ── Google Embeddings (used for FAISS schema retrieval) ──────────────────────
# Get your free key at: https://aistudio.google.com/app/apikey
GOOGLE_API_KEY            = os.getenv("GOOGLE_API_KEY", "")
# text-embedding-004 outputs 768 dimensions
EMBEDDING_DIMENSION       = int(os.getenv("EMBEDDING_DIMENSION", "3072"))

# ── Supabase ──────────────────────────────────────────────────────────────────
SUPABASE_URL              = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY      = os.getenv("SUPABASE_SERVICE_KEY", "")

# ── FAISS ─────────────────────────────────────────────────────────────────────
FAISS_INDEX_PATH          = os.getenv("FAISS_INDEX_PATH", "faiss_index/schema.index")
TOP_K_TABLES              = int(os.getenv("TOP_K_TABLES", "8"))

# ── Pipeline Behaviour ────────────────────────────────────────────────────────
IR_CONFIDENCE_THRESHOLD   = float(os.getenv("IR_CONFIDENCE_THRESHOLD", "0.70"))
SCHEMA_SIM_THRESHOLD      = float(os.getenv("SCHEMA_SIM_THRESHOLD", "0.35"))
MAX_CORRECTION_RETRIES    = int(os.getenv("MAX_CORRECTION_RETRIES", "3"))
MAX_RESULT_ROWS           = int(os.getenv("MAX_RESULT_ROWS", "1000"))
QUERY_TIMEOUT_SECONDS     = int(os.getenv("QUERY_TIMEOUT_SECONDS", "30"))

# ── Multi-turn Chat ───────────────────────────────────────────────────────────
CONVERSATION_HISTORY_TURNS = int(os.getenv("CONVERSATION_HISTORY_TURNS", "3"))

# ── App ───────────────────────────────────────────────────────────────────────
APP_ENV                   = os.getenv("APP_ENV", "development")
LOG_LEVEL                 = os.getenv("LOG_LEVEL", "INFO")