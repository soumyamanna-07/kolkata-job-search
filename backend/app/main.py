"""Kolkata Live Job Search - backend API.

Run locally (from the backend/ folder):
    uvicorn app.main:app --reload
Then open http://127.0.0.1:8000/docs to see and try every endpoint.
"""
from contextlib import asynccontextmanager

import psycopg
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import config, db
from app.routers import admin, assistant, cv, employer, jobs, match, me, reports


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.open_pool()
    yield
    db.close_pool()


app = FastAPI(
    title="Kolkata Live Job Search API",
    version="0.1.0",
    description="Live, open jobs in Kolkata - search, filters, matching.",
    lifespan=lifespan,
    # hide the interactive docs in production
    docs_url=None if config.APP_ENV == "production" else "/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(jobs.router)
app.include_router(reports.router)
app.include_router(me.router)
app.include_router(cv.router)
app.include_router(match.router)
app.include_router(assistant.router)
app.include_router(employer.router)
app.include_router(admin.router)


@app.get("/health", tags=["system"])
def health(conn: psycopg.Connection = Depends(db.get_conn)):
    """Is the API up, and can it reach the database?"""
    conn.execute("select 1")
    return {"status": "ok", "database": "ok"}
