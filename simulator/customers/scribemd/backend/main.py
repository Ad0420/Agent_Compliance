"""FastAPI app factory for the ScribeMD demo backend.

Run locally:

    uvicorn simulator.customers.scribemd.backend.main:app --reload --port 8001

The frontend dev server (Wave 2 work) lives at port 3001.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from simulator.customers.scribemd.backend.config import get_settings
from simulator.customers.scribemd.backend.db import dispose_db, init_db
from simulator.customers.scribemd.backend.routes import (
    approvals,
    auth as auth_routes,
    encounters,
    events,
    reviews,
    webhooks,
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
        title="ScribeMD Backend",
        version="0.1.0",
        description=(
            "Customer-facing backend for the ScribeMD demo (Use Case 1). "
            "Wraps `run_encounter` as an HTTP/SSE service so a browser can "
            "drive the AI-scribe pipeline."
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
        return {"ok": True, "service": "scribemd-backend"}

    app.include_router(auth_routes.router)
    app.include_router(encounters.router)
    app.include_router(approvals.router)
    app.include_router(events.router)
    app.include_router(reviews.router)
    app.include_router(webhooks.router)

    return app


app = create_app()
