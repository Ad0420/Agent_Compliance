"""Vera bootstrap and per-customer client factory.

Each mock customer in the simulator is a separate Vera org. This module:
  1. Registers each customer's org against Vera (idempotent — reuses an
     existing key if `.env.local` already has one for the slug AND it
     authenticates against the expected org).
  2. Validates that a key in `.env.local` actually maps to the org the
     slug expects — catches the W1.6 ``stale-bootstrap-key-tied-to-
     different-org`` finding where a re-bootstrap left the env file
     with a key pointing at a now-deleted org_id.
  3. Hands out a configured `VeraClient` for a given customer slug.

The mapping of slug → display name lives in `CUSTOMERS`. To add a new
mock customer, append a row and re-run
``python -m simulator.scripts.bootstrap_orgs``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv

from vera import VeraClient


REPO_ROOT = Path(__file__).resolve().parents[2]
SIM_ROOT = Path(__file__).resolve().parents[1]
ENV_LOCAL = SIM_ROOT / ".env.local"


@dataclass(frozen=True)
class CustomerSpec:
    slug: str
    display_name: str
    use_case: str
    description: str


CUSTOMERS: dict[str, CustomerSpec] = {
    "scribemd": CustomerSpec(
        slug="scribemd",
        display_name="ScribeMD Health",
        use_case="UC-1: AI scribe → chart entry",
        description="AI scribe vendor for hospitals (Abridge/Ambience-style).",
    ),
    "triageguard": CustomerSpec(
        slug="triageguard",
        display_name="TriageGuard",
        use_case="UC-3: AI triage / symptom checker",
        description="Telehealth front-door (K Health/Amwell-style).",
    ),
    "authassist": CustomerSpec(
        slug="authassist",
        display_name="AuthAssist RCM",
        use_case="UC-2: Prior authorization agent",
        description="Prior auth automation for health systems (Cohere-style).",
    ),
}


# ── env helpers ─────────────────────────────────────────────────────────────


def _load_env() -> None:
    """Load .env.local first (per-customer keys), then .env (defaults)."""
    if ENV_LOCAL.exists():
        load_dotenv(ENV_LOCAL, override=False)
    default_env = SIM_ROOT / ".env"
    if default_env.exists():
        load_dotenv(default_env, override=False)


def _key_var(slug: str) -> str:
    return f"VERA_API_KEY_{slug.upper()}"


def _vera_url() -> str:
    _load_env()
    return os.environ.get("VERA_API_URL", "https://api.usevera.xyz").rstrip("/")


def get_api_key(slug: str) -> Optional[str]:
    _load_env()
    return os.environ.get(_key_var(slug))


# ── registration ────────────────────────────────────────────────────────────


def register_org(
    spec: CustomerSpec,
    api_url: Optional[str] = None,
    *,
    with_baa: bool = True,
) -> tuple[str, str]:
    """Register a Vera org for this mock customer and return ``(org_id, raw_key)``.

    Uses the dev-mode endpoint ``POST /v1/dev/orgs`` (W1.6); the legacy
    ``POST /v1/register`` returned 410 Gone and is no longer reachable.
    Idempotency lives at TWO layers:

    1. **Env-var layer.** If ``VERA_API_KEY_<SLUG>`` already exists in
       ``.env.local`` AND it authenticates against an org matching the
       slug's display name, we skip the create and return the existing
       key. This is the fast path and the common case.

    2. **DB layer.** ``POST /v1/dev/orgs`` is gated by a UNIQUE
       constraint on ``organizations.name`` (migration
       ``s9n1o2p3q4r5``). A duplicate name returns 409. If the env
       layer's key DOES NOT match the expected org we treat it as
       stale and surface a clear error rather than silently overwriting.

    Set ``with_baa=True`` (default) to also seed an active BAA + scope.
    Required so Gate 3 (``stale_baa``) doesn't BLOCK every action this
    org tries to take.
    """
    api_url = (api_url or _vera_url()).rstrip("/")
    url = f"{api_url}/v1/dev/orgs"
    payload = {"name": spec.display_name, "with_baa": with_baa}
    resp = httpx.post(url, json=payload, timeout=30.0)
    if resp.status_code == 409:
        # Unique-name collision on the DB layer. The caller has an org
        # with this name but we don't have the raw key — the only way
        # to recover is for the operator to clean up the duplicate
        # (or move the existing key into .env.local manually).
        raise RuntimeError(
            f"An org named {spec.display_name!r} already exists on "
            f"{api_url} but no API key is available locally. Either "
            "(a) restore the existing key into simulator/.env.local "
            f"as {_key_var(spec.slug)}=... and re-run, or (b) delete "
            "the duplicate org manually before re-bootstrapping."
        )
    if resp.status_code == 404:
        # The dev endpoint is hidden in non-development environments.
        raise RuntimeError(
            f"POST /v1/dev/orgs returned 404 on {api_url}. The dev "
            "endpoint is only enabled when ENVIRONMENT=development. "
            "Either start the backend with ENVIRONMENT=development or "
            "use the production Clerk-based flow at "
            "https://app.usevera.xyz/register."
        )
    resp.raise_for_status()
    data = resp.json()
    return data["org_id"], data["api_key"]


def write_key_to_env_local(slug: str, raw_key: str) -> None:
    """Append or update ``VERA_API_KEY_<SLUG>=...`` in .env.local."""
    var = _key_var(slug)
    line = f"{var}={raw_key}"

    if not ENV_LOCAL.exists():
        ENV_LOCAL.write_text(
            "# Auto-generated by simulator/scripts/bootstrap_orgs.py — do not commit.\n"
            f"{line}\n"
        )
        return

    lines = ENV_LOCAL.read_text().splitlines()
    replaced = False
    for i, l in enumerate(lines):
        if l.startswith(f"{var}="):
            lines[i] = line
            replaced = True
            break
    if not replaced:
        lines.append(line)
    ENV_LOCAL.write_text("\n".join(lines) + "\n")


# ── key/org validation (W1.6 — stale-bootstrap-key-tied-to-different-org) ──


def validate_key_org_match(
    api_url: str,
    api_key: str,
    expected_display_name: str,
) -> tuple[bool, Optional[str]]:
    """Return ``(matches, error_msg)``.

    Hits ``GET /v1/organizations/me`` with the supplied API key. If
    the resulting org's ``name`` doesn't match ``expected_display_name``,
    returns ``(False, "<helpful message>")`` so the caller can warn the
    operator. ``(True, None)`` on a match. ``(False, "<error>")`` on
    any network/auth failure (caller decides whether to overwrite).

    This closes the Phase 2 finding ``stale-bootstrap-key-tied-to-
    different-org``: previously the bootstrap script trusted any key
    in ``.env.local`` and didn't notice when an iteration left an
    orphan key bound to a now-deleted org_id.
    """
    api_url = api_url.rstrip("/")
    try:
        resp = httpx.get(
            f"{api_url}/v1/organizations/me",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        return False, f"network error while validating key: {exc!s}"

    if resp.status_code == 401:
        return False, (
            "API key in .env.local did not authenticate (401). The key "
            "may be revoked or the backend was reset."
        )
    if resp.status_code != 200:
        return False, (
            f"GET /v1/organizations/me returned {resp.status_code}: "
            f"{resp.text[:200]}"
        )

    try:
        body = resp.json()
    except ValueError as exc:
        return False, f"could not parse /v1/organizations/me response: {exc!s}"

    actual_name = body.get("name")
    if actual_name != expected_display_name:
        return False, (
            f"API key in .env.local is bound to org {actual_name!r} "
            f"but the slug expects {expected_display_name!r}. The env "
            "file has a stale key — delete the line and re-run bootstrap."
        )
    return True, None


# ── client factory ──────────────────────────────────────────────────────────


def get_client(
    slug: str,
    *,
    agent_name: str,
    model_id: Optional[str] = None,
    framework: Optional[str] = None,
) -> VeraClient:
    """Return a Vera client configured for this mock customer.

    Raises if the customer hasn't been bootstrapped — run
    ``python -m simulator.scripts.bootstrap_orgs`` first.
    """
    if slug not in CUSTOMERS:
        raise KeyError(f"Unknown customer slug: {slug!r}. Known: {list(CUSTOMERS)}")
    api_key = get_api_key(slug)
    if not api_key:
        raise RuntimeError(
            f"No API key for {slug!r} in .env.local — run "
            "`python -m simulator.scripts.bootstrap_orgs` to register the org."
        )
    return VeraClient(
        api_url=_vera_url(),
        api_key=api_key,
        agent_name=agent_name,
        model_id=model_id,
        framework=framework,
    )
