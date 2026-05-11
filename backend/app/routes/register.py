"""Legacy self-serve org registration — DEPRECATED in Workstream E3.

Before the Clerk org bridge, this route created an Organization + admin
API key in one shot. Now orgs are provisioned via Clerk: a user signs up
through Clerk's UI, creates an organization there, Clerk fires the
``organization.created`` webhook, and the backend creates the matching
``Organization`` row. Once authenticated via Clerk the user mints API keys
from ``/dashboard/api-keys``.

The route is kept (rather than removed) so that any in-flight legacy
clients get a clear 410 Gone with migration guidance instead of a generic
404. Tests in ``tests/test_register_deprecated.py`` lock the behaviour.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["register"])


@router.post("/register", deprecated=True, status_code=410)
async def register_deprecated():
    """POST /v1/register — 410 Gone. Provisioning now happens via Clerk."""
    raise HTTPException(
        status_code=410,
        detail={
            "error": "endpoint_removed",
            "message": (
                "POST /v1/register is no longer supported. Sign up via Clerk "
                "at https://app.usevera.xyz/register, then mint an API key "
                "from /dashboard/api-keys."
            ),
            "migration_url": "https://docs.usevera.xyz/migration/clerk-org-bridge",
        },
    )
