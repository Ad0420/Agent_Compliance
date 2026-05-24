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
    checkpoints_router,
    customers_router,
    export_router,
    register_router,
    policies_router,
    approvals_router,
    webhooks_router,
)
from .routes.dashboard_demo import router as dashboard_demo_router
from .routes.dashboard_api_keys import router as dashboard_api_keys_router
from .routes.dashboard_compliance import (
    router as dashboard_compliance_router,
    compliance_router as dashboard_compliance_namespace_router,
)
from .routes.clerk_webhooks import router as clerk_webhooks_router
from .middleware import (
    ComplianceAuditMiddleware,
    RateLimitMiddleware,
    RequestIDMiddleware,
)
from .services.immutability import install_sqlite_triggers

logger = logging.getLogger("vera")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if settings.database_url.startswith("sqlite"):
            await conn.run_sync(install_sqlite_triggers)
    logger.info("Vera API started — tables ready")
    yield
    # Shutdown: close DB connection pool
    await engine.dispose()


app = FastAPI(
    title="Vera API",
    description="Tamper-proof audit trail for AI agents",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
app.add_middleware(RateLimitMiddleware)
# Compliance audit middleware lives between RequestID (outer) and the route
# handlers (inner). It needs ``request.state.request_id`` to be set by the
# time it dispatches, so it's added BEFORE RequestIDMiddleware (Starlette's
# add_middleware is LIFO — the last add is the outermost). The middleware
# reads the per-request ``_audit_ctx`` populated by ``compliance_review_audit``
# and writes a ComplianceReviewRecord after the route returns, capturing
# the real response.status_code (which a BackgroundTasks-based approach
# can't see when the handler returns a dict / Pydantic model).
app.add_middleware(ComplianceAuditMiddleware)
# Added last so it is the outermost middleware: every response — including
# rate-limit 429s and CORS preflights — carries an X-Request-ID header.
app.add_middleware(RequestIDMiddleware)


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
    db_type = "sqlite" if settings.database_url.startswith("sqlite") else "postgresql"
    return {"status": status, "environment": settings.environment, "database": db_ok, "db_type": db_type}


# Register all routers
app.include_router(actions_router, prefix="/v1")
app.include_router(agents_router, prefix="/v1")
app.include_router(checkpoints_router, prefix="/v1")
app.include_router(customers_router, prefix="/v1")
app.include_router(verification_router, prefix="/v1")
app.include_router(organizations_router, prefix="/v1")
app.include_router(export_router, prefix="/v1")
app.include_router(register_router, prefix="/v1")
app.include_router(policies_router, prefix="/v1")
app.include_router(approvals_router, prefix="/v1")
app.include_router(webhooks_router, prefix="/v1")
# Dashboard routes — authenticated via Clerk JWT (humans). The router defines
# its own /v1/dashboard prefix, so no extra prefix here. Existing /v1/* routes
# above continue to use API-key auth (machines).
app.include_router(dashboard_demo_router)
app.include_router(dashboard_api_keys_router)
# /v1/dashboard/{actions,approvals,violations,export,verify,data-subjects}
# — Clerk-authenticated read mirrors for compliance reviewers, plus the
# /v1/dashboard/compliance/{summary,recent,exports,review-trail} namespace
# for the Phase 4b compliance landing page.
app.include_router(dashboard_compliance_router)
app.include_router(dashboard_compliance_namespace_router)
# Clerk webhooks — signature-verified via Svix, no bearer auth. Mounted at
# /v1 so the public path is /v1/clerk/webhooks (matches the env.example doc).
app.include_router(clerk_webhooks_router, prefix="/v1")
