from .actions import router as actions_router
from .agents import router as agents_router
from .verification import router as verification_router
from .organizations import router as organizations_router
from .checkpoints import router as checkpoints_router
from .customers import router as customers_router
from .dev import router as dev_router
from .export import router as export_router
from .policies import router as policies_router
from .approvals import router as approvals_router
from .gates import router as gates_router
from .reviews import router as reviews_router
from .webhooks import router as webhooks_router

# routes/api_keys.py was removed in the E4 cleanup. API-key management now
# lives exclusively under /v1/dashboard/api-keys (Clerk-gated, see
# routes/dashboard_api_keys.py). The frontend /api-keys page is the only
# entry point.
#
# routes/register.py was removed in W2.3 (housekeeping trio). The 410-Gone
# stub served as a politeness layer for in-flight legacy clients after the
# Clerk org bridge landed (Workstream E3); enough time has passed that the
# path is dead code. New dev provisioning lives at POST /v1/dev/orgs
# (W1.6 — routes/dev.py); production provisioning is Clerk-only.

__all__ = [
    "actions_router",
    "agents_router",
    "verification_router",
    "organizations_router",
    "checkpoints_router",
    "customers_router",
    "dev_router",
    "export_router",
    "policies_router",
    "approvals_router",
    "gates_router",
    "reviews_router",
    "webhooks_router",
]
