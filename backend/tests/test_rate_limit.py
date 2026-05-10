"""Rate-limiter middleware tests.

Focused on the JWT-prefix-collision regression: before the fix, every Clerk
RS256 JWT shared the same first-16-char prefix (``eyJhbGciOi...``) and so
every authenticated user collapsed into ONE rate-limit bucket. Any user
could DOS all others.
"""

from __future__ import annotations

import json
import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.config import settings
from app.middleware import rate_limit as rate_limit_module
from app.middleware.rate_limit import RateLimitMiddleware, _looks_like_jwt
from app.services import auth as auth_service


_TEST_ISSUER = "https://test-clerk.example.com"
_TEST_KID = "test-kid-rl"


def _pubkey_to_jwk(public_key) -> dict[str, Any]:
    return json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(public_key))


@pytest.fixture(scope="module")
def keypair():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = _pubkey_to_jwk(priv.public_key())
    jwk.update({"kid": _TEST_KID, "alg": "RS256", "use": "sig"})
    return {"priv": priv, "jwk": jwk}


@pytest.fixture(autouse=True)
def _configure_clerk(monkeypatch):
    monkeypatch.setattr(settings, "clerk_jwks_url", "https://fixture/jwks.json")
    monkeypatch.setattr(settings, "clerk_issuer", _TEST_ISSUER)
    monkeypatch.setattr(settings, "clerk_audience", None)
    monkeypatch.setattr(settings, "clerk_authorized_parties", None)
    auth_service._reset_jwks_cache_for_tests()
    yield
    auth_service._reset_jwks_cache_for_tests()


@pytest.fixture
def patched_jwks(monkeypatch, keypair):
    state = {"calls": 0, "keys": [keypair["jwk"]]}

    async def _fake_fetch(_url: str) -> dict:
        state["calls"] += 1
        return {"keys": list(state["keys"])}

    monkeypatch.setattr(auth_service, "_fetch_jwks", _fake_fetch)
    return state


def _sign(priv, *, sub: str, expires_in: int = 300) -> str:
    iat = int(time.time())
    claims = {
        "sub": sub,
        "iss": _TEST_ISSUER,
        "iat": iat,
        "exp": iat + expires_in,
    }
    return jwt.encode(claims, priv, algorithm="RS256", headers={"kid": _TEST_KID})


# ── Unit tests on the keying function ────────────────────────────────────────


def test_looks_like_jwt_true_for_3_segments():
    assert _looks_like_jwt("aaa.bbb.ccc") is True


def test_looks_like_jwt_false_for_api_key():
    assert _looks_like_jwt("al_live_abcdef0123456789") is False


def test_looks_like_jwt_false_for_two_segments():
    assert _looks_like_jwt("aaa.bbb") is False


def test_looks_like_jwt_false_for_empty_segment():
    assert _looks_like_jwt("aaa..ccc") is False


def test_jwt_users_get_distinct_buckets(keypair):
    """The crux of the fix: two distinct JWTs must map to distinct buckets.

    Before the fix, ``_get_key`` sliced ``auth[7:23]`` — the same 16 chars
    of base64-encoded ``{"alg":"RS256",...}`` for every Clerk JWT. Any user
    could fill the bucket and DOS all other users.
    """
    mw = RateLimitMiddleware(app=None)

    token_a = _sign(keypair["priv"], sub="user_alice")
    token_b = _sign(keypair["priv"], sub="user_bob")
    assert token_a != token_b

    class _FakeReq:
        def __init__(self, auth: str):
            self.headers = {"authorization": auth}
            self.client = None

    key_a = mw._get_key(_FakeReq(f"Bearer {token_a}"))
    key_b = mw._get_key(_FakeReq(f"Bearer {token_b}"))

    assert key_a.startswith("jwt:")
    assert key_b.startswith("jwt:")
    assert key_a != key_b, (
        "Distinct JWTs must hash to distinct rate-limit buckets — "
        "otherwise any user can DOS all other users."
    )


def test_api_key_path_unchanged():
    """The API-key path keeps its previous prefix-based bucketing so the
    existing /v1/* rate-limit behavior is preserved.
    """
    mw = RateLimitMiddleware(app=None)

    class _FakeReq:
        def __init__(self, auth: str):
            self.headers = {"authorization": auth}
            self.client = None

    key_a = mw._get_key(_FakeReq("Bearer al_live_abcdefgh12345678xxxx"))
    key_b = mw._get_key(_FakeReq("Bearer al_live_zzzzzzzz99999999xxxx"))

    assert key_a.startswith("key:")
    assert key_b.startswith("key:")
    assert key_a != key_b


# ── Integration tests through the FastAPI app ────────────────────────────────


@pytest.mark.asyncio
async def test_rate_limit_jwt_users_isolated(keypair, patched_jwks):
    """Saturate user-A's rate-limit bucket; user-B must remain unaffected.

    Before the fix the two users would share a bucket via the
    ``auth[7:23]`` slice (which is constant across all RS256 JWTs).

    This drives a small isolated FastAPI app (not the global one) so we
    can pin tight RPM/burst limits without polluting other tests.
    """
    from fastapi import Depends, FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.middleware.clerk_auth import require_clerk_auth

    test_app = FastAPI()
    # Tight limits: 5 req/min, burst 5/sec — fast to saturate.
    test_app.add_middleware(RateLimitMiddleware, rpm=5, burst=5)

    @test_app.get("/me")
    async def _me(claims: dict = Depends(require_clerk_auth)):
        return {"sub": claims["sub"]}

    token_a = _sign(keypair["priv"], sub="user_alice")
    token_b = _sign(keypair["priv"], sub="user_bob")
    assert token_a != token_b

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # User A: blow through the budget.
        statuses_a = []
        for _ in range(8):
            r = await client.get(
                "/me",
                headers={"Authorization": f"Bearer {token_a}"},
            )
            statuses_a.append(r.status_code)

        assert 429 in statuses_a, (
            f"Expected user A to hit the rate limit; statuses={statuses_a}"
        )

        # User B must still be served — separate bucket.
        r_b = await client.get(
            "/me",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert r_b.status_code == 200, (
            f"User B was rate-limited because of user A's traffic — "
            f"buckets are colliding. Status={r_b.status_code}, body={r_b.text}"
        )
