"""FastAPI app factory for the TriageGuard demo backend.

Run locally:

    uvicorn simulator.customers.triageguard.backend.main:app --reload --port 8002

The frontend dev server (Wave 4B work) lives at port 3002.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from simulator.customers.triageguard.backend.config import get_settings
from simulator.customers.triageguard.backend.db import dispose_db, init_db
from simulator.customers.triageguard.backend.routes import (
    auth as auth_routes,
    events,
    reviews,
    sessions,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    try:
        yield
    finally:
        await dispose_db()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="TriageGuard Backend",
        version="0.1.0",
        description=(
            "Customer-facing backend for the TriageGuard demo (Use Case 3). "
            "Wraps `run_session` as an HTTP/SSE service so a browser can "
            "drive the AI-triage pipeline."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health", tags=["meta"])
    async def health() -> dict:
        return {"ok": True, "service": "triageguard-backend"}

    app.include_router(auth_routes.router)
    app.include_router(sessions.router)
    app.include_router(reviews.router)
    app.include_router(events.router)

    return app


app = create_app()
