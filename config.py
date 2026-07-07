"""
config.py
All environment variables and application-wide settings.
Copy .env.example to .env and fill in your values.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Azure OpenAI ────────────────────────────────────────────────────────────
AZURE_OPENAI_API_KEY      = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_ENDPOINT     = os.getenv("AZURE_OPENAI_ENDPOINT", "")        # e.g. https://YOUR-RESOURCE.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT   = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
AZURE_OPENAI_API_VERSION  = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")

# ── Supabase ────────────────────────────────────────────────────────────────
SUPABASE_URL              = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY      = os.getenv("SUPABASE_SERVICE_KEY", "")         # service_role key for backend

# ── FAISS / Embeddings ──────────────────────────────────────────────────────
FAISS_INDEX_PATH          = os.getenv("FAISS_INDEX_PATH", "faiss_index/schema.index")
EMBEDDING_MODEL           = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")  # Azure embedding deployment name
EMBEDDING_DIMENSION       = int(os.getenv("EMBEDDING_DIMENSION", "1536"))
TOP_K_TABLES              = int(os.getenv("TOP_K_TABLES", "8"))           # max tables retrieved from FAISS

# ── Pipeline Behaviour ───────────────────────────────────────────────────────
IR_CONFIDENCE_THRESHOLD   = float(os.getenv("IR_CONFIDENCE_THRESHOLD", "0.70"))
SCHEMA_SIM_THRESHOLD      = float(os.getenv("SCHEMA_SIM_THRESHOLD", "0.35"))  # min cosine sim for table retrieval
MAX_CORRECTION_RETRIES    = int(os.getenv("MAX_CORRECTION_RETRIES", "3"))
MAX_RESULT_ROWS           = int(os.getenv("MAX_RESULT_ROWS", "1000"))
QUERY_TIMEOUT_SECONDS     = int(os.getenv("QUERY_TIMEOUT_SECONDS", "30"))

# ── Multi-turn Chat ──────────────────────────────────────────────────────────
CONVERSATION_HISTORY_TURNS = int(os.getenv("CONVERSATION_HISTORY_TURNS", "3"))  # last N turns sent to LLM

# ── App ──────────────────────────────────────────────────────────────────────
APP_ENV                   = os.getenv("APP_ENV", "development")
LOG_LEVEL                 = os.getenv("LOG_LEVEL", "INFO")