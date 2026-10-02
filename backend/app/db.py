"""Database connection pool shared by all API requests."""
from collections.abc import Iterator

import psycopg
from psycopg_pool import ConnectionPool

from app import config

pool: ConnectionPool | None = None


def open_pool() -> None:
    """Called once when the API starts."""
    global pool
    if not config.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set. Add it to the .env file in the project root.")
    pool = ConnectionPool(
        config.DATABASE_URL,
        min_size=config.DB_POOL_MIN,
        max_size=config.DB_POOL_MAX,
        kwargs={"autocommit": True, "application_name": "kjs-backend"},
        open=False,
    )
    pool.open(wait=True, timeout=30)


def close_pool() -> None:
    """Called once when the API stops."""
    if pool is not None:
        pool.close()


def get_conn() -> Iterator[psycopg.Connection]:
    """FastAPI dependency: borrow a connection for one request, then give it back."""
    if pool is None:
        raise RuntimeError("Database pool is not open")
    with pool.connection() as conn:
        yield conn
