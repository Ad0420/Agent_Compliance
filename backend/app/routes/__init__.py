from .actions import router as actions_router
from .agents import router as agents_router
from .verification import router as verification_router
from .organizations import router as organizations_router
from .checkpoints import router as checkpoints_router
from .customers import router as customers_router
from .export import router as export_router
from .register import router as register_router
from .policies import router as policies_router
from .approvals import router as approvals_router
from .gates import router as gates_router
from .reviews import router as reviews_router
from .staff import router as staff_router
from .webhooks import router as webhooks_router
from .kms import router as kms_router

# routes/api_keys.py was removed in the E4 cleanup. API-key management now
# lives exclusively under /v1/dashboard/api-keys (Clerk-gated, see
# routes/dashboard_api_keys.py). The frontend /api-keys page is the only
# entry point.

__all__ = [
    "actions_router",
    "agents_router",
    "verification_router",
    "organizations_router",
    "checkpoints_router",
    "customers_router",
    "export_router",
    "register_router",
    "policies_router",
    "approvals_router",
    "gates_router",
    "reviews_router",
    "staff_router",
    "webhooks_router",
    "kms_router",
]
