"""Regression test for the Phase 3 CORS hotfix.

Wave 3D.3's ``PUT /v1/dashboard/s3-export-arn`` was silently
CORS-blocked because ``app.main.CORSMiddleware.allow_methods`` had
``["GET", "POST", "PATCH", "DELETE", "OPTIONS"]`` but no ``PUT``.

Every browser request to a PUT endpoint failed the preflight check
("Response to preflight request doesn't pass access control check").
Found during Phase 3 Scenario 2 acceptance testing.

This test pins the allow_methods list so a future drift fails fast in
CI rather than waiting for a manual dashboard walkthrough to surface
the regression.

If a future endpoint introduces a new HTTP verb (e.g. HEAD for HEAD
checks on evidence downloads), add it here AND to
``backend/app/main.py``'s ``allow_methods`` list — and document why in
both spots.
"""
from __future__ import annotations

from starlette.middleware.cors import CORSMiddleware

from app.main import app


def _get_cors_middleware_config() -> dict:
    """Pull the CORSMiddleware constructor kwargs off the running app.

    Starlette stores middleware as a list of ``Middleware`` records on
    ``app.user_middleware``. Each record carries the class + the kwargs
    it was added with. We find the CORS entry and return its kwargs.
    """
    for record in app.user_middleware:
        if record.cls is CORSMiddleware:
            return dict(record.kwargs)
    raise AssertionError("CORSMiddleware not registered on app")


def test_cors_allow_methods_includes_all_route_verbs():
    """Every HTTP verb our routes use must be in CORS allow_methods.

    Today: GET, POST, PUT, PATCH, DELETE. Plus OPTIONS for the preflight
    itself. If a route adds a new verb (e.g. HEAD), this test will fail
    and the developer needs to update both the route and the CORS list.
    """
    kwargs = _get_cors_middleware_config()
    methods = set(kwargs.get("allow_methods", []))
    required = {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
    missing = required - methods
    assert not missing, (
        f"CORS allow_methods is missing {missing}. Every HTTP verb that "
        f"the API routes use must be in this list, otherwise browser "
        f"requests are CORS-blocked at preflight. Edit "
        f"backend/app/main.py and add the missing method(s)."
    )


def test_cors_allow_methods_explicitly_includes_put():
    """Pin PUT specifically — this is the verb that regressed in Phase 3.

    Wave 3D.3 (PR #241) introduced ``PUT /v1/dashboard/s3-export-arn``
    and ``DELETE`` for unset-the-ARN, but the CORS list was only updated
    for DELETE. PUT silently broke. Keep this assertion as a backstop
    so a future cleanup doesn't accidentally remove PUT without thinking.
    """
    kwargs = _get_cors_middleware_config()
    methods = kwargs.get("allow_methods", [])
    assert "PUT" in methods, (
        "PUT must be in CORSMiddleware allow_methods. The Wave 3D.3 "
        "Settings → Off-Vera mirror save endpoint depends on it. See "
        "the hotfix PR + docs/v1/phase3-acceptance-test-plan.md "
        "Scenario 2 finding for the original bug report."
    )
