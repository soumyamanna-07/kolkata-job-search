"""Backend settings, read from the project's .env file (or real environment variables in production)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")


def _list(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


APP_ENV = os.getenv("APP_ENV", "development")          # development | production
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
# Only needed for older Supabase projects that sign logins with a shared secret (HS256).
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "").strip()

# Websites allowed to call this API from a browser (the React app).
CORS_ORIGINS = _list("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")

DB_POOL_MIN = int(os.getenv("DB_POOL_MIN", "1"))
DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", "5"))       # Supabase free plan allows few connections

# AI assistant (any OpenAI-compatible chat API; we use Groq). No key = assistant lists jobs without an AI answer.
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1").strip().rstrip("/")
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-20b").strip()
LLM_REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "").strip()     # e.g. "low" for gpt-oss models
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "30"))
# Stay inside the free plan: questions per visitor per minute, and AI answers per day for the whole site.
ASSISTANT_PER_MINUTE = int(os.getenv("ASSISTANT_PER_MINUTE", "6"))
ASSISTANT_DAILY_AI_ANSWERS = int(os.getenv("ASSISTANT_DAILY_AI_ANSWERS", "900"))
