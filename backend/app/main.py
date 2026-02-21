import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .config import settings
from .database import engine
from .models import Base
from .routes import (
    actions_router,
    agents_router,
    verification_router,
    organizations_router,
    api_keys_router,
    checkpoints_router,
)
from .middleware import RateLimitMiddleware
from .services.immutability import install_sqlite_triggers

logger = logging.getLogger("actionledger")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if settings.database_url.startswith("sqlite"):
            await conn.run_sync(install_sqlite_triggers)
    logger.info("Action Ledger API started — tables ready")
    yield
    # Shutdown: close DB connection pool
    await engine.dispose()


app = FastAPI(
    title="Action Ledger API",
    description="Immutable audit ledger for AI agent actions",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
app.add_middleware(RateLimitMiddleware)


@app.get("/health")
async def health_check():
    from .database import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    status = "ok" if db_ok else "degraded"
    return {"status": status, "environment": settings.environment, "database": db_ok}


# Register all routers
app.include_router(actions_router, prefix="/v1")
app.include_router(agents_router, prefix="/v1")
app.include_router(checkpoints_router, prefix="/v1")
app.include_router(verification_router, prefix="/v1")
app.include_router(organizations_router, prefix="/v1")
app.include_router(api_keys_router, prefix="/v1")
