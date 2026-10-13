"""Settings for the data pipeline, read from the project's .env file."""
import os
from pathlib import Path

from dotenv import load_dotenv

# .env lives in the project root (one level above data_pipeline/)
ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")


def require(name: str) -> str:
    """Return a required setting, or stop with a clear message if it is missing."""
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing setting: {name}. Add it to the .env file in the project root.")
    return value


DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "").strip()
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "").strip()
JOOBLE_API_KEY = os.getenv("JOOBLE_API_KEY", "").strip()
CAREERJET_API_KEY = os.getenv("CAREERJET_API_KEY", "").strip()
# Careerjet asks for the IP of the person searching; for our daily batch run, our own server's IP.
CAREERJET_USER_IP = os.getenv("CAREERJET_USER_IP", "").strip()
