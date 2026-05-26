"""Tests for ``simulator/scripts/bootstrap_orgs.py`` (W1.6).

Three behaviours covered:

1. **Idempotent re-bootstrap** — running with an env-file key that
   validates against the expected org skips the POST and never tries
   to mint a new key.
2. **Stale-key warning** — when the env-file key authenticates against
   a DIFFERENT org's display name, the script warns the operator and
   does NOT auto-overwrite.
3. **Fresh provision** — when neither env-key nor existing org is
   present, the script POSTs to ``/v1/dev/orgs`` and writes the
   returned raw key to the env file.

All HTTP calls are stubbed via monkeypatch on ``httpx.get`` /
``httpx.post`` so the tests do not require a live backend.
"""
from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import httpx
import pytest

from simulator.scripts import bootstrap_orgs
from simulator.shared import vera_setup


@pytest.fixture
def tmp_env(tmp_path, monkeypatch):
    """Re-point ``ENV_LOCAL`` (and re-export) at a temp file."""
    env_path = tmp_path / ".env.local"
    monkeypatch.setattr(vera_setup, "ENV_LOCAL", env_path)
    monkeypatch.setattr(bootstrap_orgs, "ENV_LOCAL", env_path)
    # Clear any test-pollution env vars that would short-circuit get_api_key.
    for slug in vera_setup.CUSTOMERS:
        monkeypatch.delenv(vera_setup._key_var(slug), raising=False)
    monkeypatch.setenv("VERA_API_URL", "http://test")
    yield env_path


class _FakeResp:
    def __init__(self, status_code: int, json_body: dict | None = None):
        self.status_code = status_code
        self._json = json_body or {}
        self.text = str(self._json)

    def json(self):
        return self._json

    def raise_for_status(self):
        if 400 <= self.status_code:
            raise httpx.HTTPStatusError(
                f"{self.status_code}",
                request=None,  # type: ignore[arg-type]
                response=None,  # type: ignore[arg-type]
            )


def test_bootstrap_skips_when_env_key_validates(tmp_env, monkeypatch):
    """Env-file already has the right key → no POST, no overwrite."""
    # Pre-seed env file + env var with a matching key.
    tmp_env.write_text("VERA_API_KEY_SCRIBEMD=al_test_existing_key\n")
    monkeypatch.setenv("VERA_API_KEY_SCRIBEMD", "al_test_existing_key")

    posted = []

    def fake_get(url, **kwargs):
        # /v1/dev/orgs?name=ScribeMD Health → no existing org by name
        if "/v1/dev/orgs" in url:
            return _FakeResp(200, {"orgs": []})
        # /v1/organizations/me — validates the existing key
        if "/v1/organizations/me" in url:
            return _FakeResp(200, {"id": "org-1", "name": "ScribeMD Health"})
        raise AssertionError(f"unexpected GET {url}")

    def fake_post(url, **kwargs):
        posted.append((url, kwargs.get("json")))
        return _FakeResp(201, {})

    monkeypatch.setattr(bootstrap_orgs.httpx, "get", fake_get)
    monkeypatch.setattr(vera_setup.httpx, "get", fake_get)
    monkeypatch.setattr(vera_setup.httpx, "post", fake_post)

    rc = bootstrap_orgs.main_for_tests(only=["scribemd"], with_baa=True)
    assert rc == 0
    assert posted == [], "Bootstrap should not POST when env key validates"
    # Env file unchanged (still has the original key).
    assert "al_test_existing_key" in tmp_env.read_text()


def test_bootstrap_warns_on_stale_key_does_not_overwrite(
    tmp_env, monkeypatch
):
    """Env key validates against a DIFFERENT org → warn, don't overwrite."""
    tmp_env.write_text("VERA_API_KEY_SCRIBEMD=al_test_stale_key\n")
    monkeypatch.setenv("VERA_API_KEY_SCRIBEMD", "al_test_stale_key")

    posted = []

    def fake_get(url, **kwargs):
        if "/v1/dev/orgs" in url:
            return _FakeResp(200, {"orgs": []})
        if "/v1/organizations/me" in url:
            # The stale key authenticates, but to a different org name.
            return _FakeResp(200, {"id": "other-org", "name": "Some Other Org"})
        raise AssertionError(f"unexpected GET {url}")

    def fake_post(url, **kwargs):
        posted.append((url, kwargs.get("json")))
        return _FakeResp(201, {})

    monkeypatch.setattr(bootstrap_orgs.httpx, "get", fake_get)
    monkeypatch.setattr(vera_setup.httpx, "get", fake_get)
    monkeypatch.setattr(vera_setup.httpx, "post", fake_post)

    stderr = io.StringIO()
    with redirect_stderr(stderr), redirect_stdout(io.StringIO()):
        rc = bootstrap_orgs.main_for_tests(only=["scribemd"], with_baa=True)

    assert rc == 0
    assert posted == [], "Bootstrap must not auto-overwrite a stale key"
    # Env file untouched.
    assert tmp_env.read_text().strip() == "VERA_API_KEY_SCRIBEMD=al_test_stale_key"
    # The stale-key warning surfaced to stderr.
    err = stderr.getvalue()
    assert "stale" in err.lower() or "bound to org" in err
    assert "Some Other Org" in err


def test_bootstrap_creates_org_on_fresh_run(tmp_env, monkeypatch):
    """No env key + no existing org → POST /v1/dev/orgs and write key."""
    # No pre-existing env file or env var.
    assert not tmp_env.exists()

    def fake_get(url, **kwargs):
        if "/v1/dev/orgs" in url:
            return _FakeResp(200, {"orgs": []})
        raise AssertionError(f"unexpected GET {url}")

    def fake_post(url, **kwargs):
        assert "/v1/dev/orgs" in url, url
        assert kwargs["json"]["name"] == "ScribeMD Health"
        assert kwargs["json"]["with_baa"] is True
        return _FakeResp(
            201,
            {
                "org_id": "new-org-uuid",
                "name": "ScribeMD Health",
                "api_key": "al_test_fresh_key_value",
                "api_key_prefix": "al_test_fre",
                "has_baa": True,
            },
        )

    monkeypatch.setattr(bootstrap_orgs.httpx, "get", fake_get)
    monkeypatch.setattr(vera_setup.httpx, "get", fake_get)
    monkeypatch.setattr(vera_setup.httpx, "post", fake_post)

    rc = bootstrap_orgs.main_for_tests(only=["scribemd"], with_baa=True)
    assert rc == 0

    written = tmp_env.read_text()
    assert "VERA_API_KEY_SCRIBEMD=al_test_fresh_key_value" in written


def test_validate_key_org_match_detects_mismatch(monkeypatch):
    """``validate_key_org_match`` unit: returns (False, msg) on name mismatch."""

    def fake_get(url, **kwargs):
        return _FakeResp(200, {"id": "x", "name": "Wrong Org"})

    monkeypatch.setattr(vera_setup.httpx, "get", fake_get)
    matches, err = vera_setup.validate_key_org_match(
        "http://test", "al_test_anything", "Expected Org"
    )
    assert matches is False
    assert err is not None
    assert "Wrong Org" in err
    assert "Expected Org" in err


def test_validate_key_org_match_returns_true_on_match(monkeypatch):
    def fake_get(url, **kwargs):
        return _FakeResp(200, {"id": "x", "name": "Match"})

    monkeypatch.setattr(vera_setup.httpx, "get", fake_get)
    matches, err = vera_setup.validate_key_org_match(
        "http://test", "al_test_anything", "Match"
    )
    assert matches is True
    assert err is None


def test_validate_key_org_match_handles_401(monkeypatch):
    def fake_get(url, **kwargs):
        return _FakeResp(401, {"detail": "Invalid"})

    monkeypatch.setattr(vera_setup.httpx, "get", fake_get)
    matches, err = vera_setup.validate_key_org_match(
        "http://test", "al_test_revoked", "Anything"
    )
    assert matches is False
    assert err is not None
    assert "401" in err or "authenticate" in err
