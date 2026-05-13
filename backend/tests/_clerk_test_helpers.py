"""Shared Clerk JWT signing helpers for Phase 4a RBAC + audit tests.

We can't reuse ``tests/test_dashboard_api_keys.py`` directly (its fixtures
are module-scoped and tied to one set of admin/developer users) — but the
underlying machinery is the same: generate a fixture RSA keypair, expose
it as a JWKS dict, monkey-patch ``_fetch_jwks`` so verification reads
our fixture, and sign tokens with the private half.
"""
from __future__ import annotations

import json
import time
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa


TEST_ISSUER = "https://test-clerk.example.com"
TEST_KID = "rbac-kid-1"


def pubkey_to_jwk(public_key) -> dict[str, Any]:
    return json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(public_key))


def make_keypair() -> dict[str, Any]:
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = pubkey_to_jwk(priv.public_key())
    jwk.update({"kid": TEST_KID, "alg": "RS256", "use": "sig"})
    return {"priv": priv, "jwk": jwk}


def sign_token(
    priv,
    *,
    sub: str,
    org_id: str | None,
    expires_in: int = 300,
) -> str:
    iat = int(time.time())
    claims: dict[str, Any] = {
        "sub": sub,
        "iss": TEST_ISSUER,
        "iat": iat,
        "exp": iat + expires_in,
    }
    if org_id is not None:
        claims["org_id"] = org_id
    return jwt.encode(claims, priv, algorithm="RS256", headers={"kid": TEST_KID})


def reset_rate_limit(app) -> None:
    """The RateLimit middleware uses an in-process bucket. When tests run
    quickly the bucket can hold over from earlier suites and trip 429s on
    legitimate hits. Clear it before each test."""
    stack = getattr(app, "middleware_stack", None)
    visited = set()
    while stack is not None and id(stack) not in visited:
        visited.add(id(stack))
        if type(stack).__name__ == "RateLimitMiddleware":
            requests = getattr(stack, "_requests", None)
            if requests is not None:
                requests.clear()
        stack = getattr(stack, "app", None)
