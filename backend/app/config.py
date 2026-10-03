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

# Links inside emails: the website (job pages) and this API (unsubscribe links).
APP_URL = os.getenv("APP_URL", "http://localhost:5173").strip().rstrip("/")
API_URL = os.getenv("API_URL", "http://127.0.0.1:8000").strip().rstrip("/")

# Job alert emails, through any SMTP server (Gmail app password, Brevo, ...). No SMTP_HOST = no emails sent.
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))           # 587 = STARTTLS, 465 = SSL
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()
MAIL_FROM = os.getenv("MAIL_FROM", "").strip()            # the address emails come from
MAIL_FROM_NAME = os.getenv("MAIL_FROM_NAME", "Kolkata Live Job Search").strip()
# Signs the unsubscribe links in emails, so nobody can switch off other people's alerts. Keep it secret.
ALERTS_SECRET = os.getenv("ALERTS_SECRET", "").strip()
ALERT_EMAILS_PER_RUN = int(os.getenv("ALERT_EMAILS_PER_RUN", "400"))   # Gmail allows ~500 a day
