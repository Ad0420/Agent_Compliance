import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from .config import settings
from .database import engine
from .models import Base
from .routes import (
    actions_router,
    agents_router,
    verification_router,
    organizations_router,
    checkpoints_router,
    checkpoints_by_date_router,
    customer_chain_summary_router,
    customers_router,
    dev_router,
    export_router,
    policies_router,
    approvals_router,
    gates_router,
    reviews_router,
    staff_router,
    webhooks_router,
    kms_router,
    records_router,
    dashboard_chain_integrity_router,
)
from .routes.dashboard_demo import router as dashboard_demo_router
from .routes.dashboard_api_keys import router as dashboard_api_keys_router
from .routes.dashboard_sync import router as dashboard_sync_router
from .routes.dashboard_compliance import (
    router as dashboard_compliance_router,
    compliance_router as dashboard_compliance_namespace_router,
)
from .routes.dashboard_s3_mirror import router as dashboard_s3_mirror_router
from .routes.clerk_webhooks import router as clerk_webhooks_router
from .middleware import (
    ComplianceAuditMiddleware,
    RateLimitMiddleware,
    RequestIDMiddleware,
)
from .services.immutability import install_sqlite_triggers
from .services.webhook_sweeper import start_in_process as start_webhook_sweeper
from .services.webhook_sweeper import stop_in_process as stop_webhook_sweeper
from .services.checkpoint_sweeper import (
    start_in_process as start_checkpoint_sweeper,
    stop_in_process as stop_checkpoint_sweeper,
)

logger = logging.getLogger("vera")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if settings.database_url.startswith("sqlite"):
            await conn.run_sync(install_sqlite_triggers)
    # Wave 2B PR A3 — webhook delivery sweeper. Background asyncio task
    # that retries failed deliveries + sweeps expired approvals on the
    # same tick. Gated by VERA_WEBHOOK_SWEEPER_ENABLED so tests that
    # don't want time-driven side effects can disable it. See
    # ``app/services/webhook_sweeper.py``.
    start_webhook_sweeper()
    # Phase 3 Wave 3A.b — per-org checkpoint cadence sweeper. Separate
    # background asyncio task that walks the org table once per tick
    # (default 5 min) and creates checkpoints for orgs whose cadence
    # threshold has elapsed. Gated by VERA_CHECKPOINT_SWEEPER_ENABLED.
    # See ``app/services/checkpoint_sweeper.py``.
    start_checkpoint_sweeper()
    logger.info("Vera API started — tables ready")
    yield
    # Shutdown: stop sweepers first so they stop grabbing rows mid-shutdown,
    # then close the DB pool.
    await stop_webhook_sweeper()
    await stop_checkpoint_sweeper()
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
    # PUT added in the Phase 3 CORS hotfix — the Wave 3D.3 S3 mirror
    # endpoint ``PUT /v1/dashboard/s3-export-arn`` was being CORS-blocked
    # from any browser because PUT was missing here. Found during Phase 3
    # acceptance testing (Scenario 2). See ``docs/v1/phase3-acceptance-test-plan.md``.
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
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


@app.exception_handler(StarletteHTTPException)
async def _flatten_dict_detail(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Flatten ``HTTPException(detail=dict(...))`` into the response body.

    FastAPI's default exception handler wraps **every** ``HTTPException.detail``
    under a top-level ``{"detail": ...}`` envelope. For structured error
    payloads (``HTTPException(detail={"code": "baa_required", "fix_url": ...})``)
    that produces ``{"detail": {"code": ...}}`` — the SDK's ``wrap_httpx_error``
    reads ``body.get("code")`` from the *top level* so the nested shape silently
    falls through to the generic 4xx mapping and a real ``PolicyBlock``
    misclassifies as ``VeraAuthError``.

    This handler lifts dict-typed ``detail`` payloads to the top level so the
    wire envelope is ``{"code": ..., "detail": ..., "fix_url": ...}``. String
    ``detail`` values continue to round-trip as ``{"detail": "<string>"}``
    (preserving FastAPI's default for unstructured errors).
    """
    # Preserve any headers the route handler attached (e.g. ``Retry-After``
    # on 409 ``checkpoint_pending``). FastAPI's default handler drops them
    # when the body is rewritten; we replicate the route's intent.
    headers = getattr(exc, "headers", None)
    if isinstance(exc.detail, dict):
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.detail,
            headers=headers,
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=headers,
    )


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
# Phase 3 Wave 3B.1 — GET /v1/checkpoints/{date} for auditor diff workflow.
# Separate from the /v1/verify/checkpoints router above (different prefix
# + different IAM model: this one supports staff X-Org-Id reads).
app.include_router(checkpoints_by_date_router, prefix="/v1")
# Wave 3D.2 — Customer Verification & Evidence Trail panel data feed +
# evidence bundle export. Mounted under the same /v1/customers prefix
# the existing customers_router uses; registering BEFORE customers_router
# ensures the more-specific paths (/{tenant_id}/chain-summary,
# /{tenant_id}/evidence-export) match before the catch-all PATCH/GET on
# the customers router would intercept them. FastAPI matches in
# registration order.
app.include_router(customer_chain_summary_router, prefix="/v1")
app.include_router(customers_router, prefix="/v1")
# Dev-only org provisioning (W1.6). The router itself raises 404 in any
# non-development environment so this never accidentally exposes
# org-creation on production. See ``routes/dev.py``.
app.include_router(dev_router, prefix="/v1")
app.include_router(verification_router, prefix="/v1")
app.include_router(organizations_router, prefix="/v1")
app.include_router(export_router, prefix="/v1")
app.include_router(policies_router, prefix="/v1")
app.include_router(approvals_router, prefix="/v1")
app.include_router(gates_router, prefix="/v1")
app.include_router(reviews_router, prefix="/v1")
app.include_router(staff_router, prefix="/v1")
app.include_router(webhooks_router, prefix="/v1")
# Phase 3 Wave 3A.a — KMS key history (eng review finding 1A).
# Read-only history dump consumed by Wave 3C `vera verify --offline`.
app.include_router(kms_router, prefix="/v1")
# Phase 3 Wave 3B.2 — Merkle proof exposure for any sealed action record.
# Returns the canonical bytes, leaf hash, Merkle path, sealing checkpoint
# id, and the checkpoint's KMS signature so an offline verifier can
# reconstruct the root and validate the signature without trusting the
# Vera API. See ``routes/records.py`` for the per-tier IAM rules.
app.include_router(records_router, prefix="/v1")
# Dashboard routes — authenticated via Clerk JWT (humans). The router defines
# its own /v1/dashboard prefix, so no extra prefix here. Existing /v1/* routes
# above continue to use API-key auth (machines).
app.include_router(dashboard_demo_router)
app.include_router(dashboard_api_keys_router)
app.include_router(dashboard_sync_router)
# /v1/dashboard/{actions,approvals,violations,export,verify,data-subjects}
# — Clerk-authenticated read mirrors for compliance reviewers, plus the
# /v1/dashboard/compliance/{summary,recent,exports,review-trail} namespace
# for the Phase 4b compliance landing page.
app.include_router(dashboard_compliance_router)
app.include_router(dashboard_compliance_namespace_router)
# Phase 3 Wave 3D.3 — Settings → Off-Vera S3 mirror configuration surface.
# /v1/dashboard/s3-export-config + /v1/dashboard/s3-export-arn{,/validate,/probe}.
app.include_router(dashboard_s3_mirror_router)
# Phase 3 Wave 3D.1 — Home page Chain Integrity tile. The router defines its
# own /v1/dashboard prefix; auth is dual-mode (API key OR Clerk JWT) via
# ``require_permission_with_context`` so the same endpoint serves the SDK
# health-check use case AND the dashboard tile.
app.include_router(dashboard_chain_integrity_router, prefix="/v1")
# Clerk webhooks — signature-verified via Svix, no bearer auth. Mounted at
# /v1 so the public path is /v1/clerk/webhooks (matches the env.example doc).
app.include_router(clerk_webhooks_router, prefix="/v1")
