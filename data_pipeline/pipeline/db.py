"""Database connection for the data pipeline."""
import psycopg

from pipeline.config import require


def connect() -> psycopg.Connection:
    """Open a connection to the Supabase Postgres database."""
    return psycopg.connect(
        require("DATABASE_URL"),
        connect_timeout=15,
        application_name="kjs-data-pipeline",
    )