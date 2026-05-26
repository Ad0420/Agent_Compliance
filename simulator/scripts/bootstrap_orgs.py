"""Bootstrap a Vera dev org for every mock customer.

W1.6 rewrite. Replaces the dead ``POST /v1/register`` call with the
new dev-only ``POST /v1/dev/orgs`` endpoint shipped in the same PR.

Idempotency lives at THREE layers (each guards a different failure
mode that surfaced during Phase 2 acceptance testing):

  1. **Existence pre-check.** ``GET /v1/dev/orgs?name=<display>`` before
     attempting a create. If the slug already has an org provisioned
     on the backend, we skip the POST and reuse the env-file key (if
     present) or print operator-actionable guidance.
  2. **Env-file presence.** If ``VERA_API_KEY_<SLUG>`` is already in
     ``.env.local`` AND it validates against the expected org (closes
     finding ``stale-bootstrap-key-tied-to-different-org``), we treat
     the slug as fully bootstrapped.
  3. **DB-level UNIQUE constraint.** ``organizations.name`` is UNIQUE
     per migration ``s9n1o2p3q4r5``; a duplicate name returns 409 from
     the dev endpoint with a structured ``org_name_taken`` envelope.

Each successful provision:
  - Calls POST /v1/dev/orgs on Vera (requires
    ``ENVIRONMENT=development`` on the backend).
  - Persists the resulting raw key to ``.env.local`` as
    ``VERA_API_KEY_<SLUG>=...``.
  - Optionally registers the customer's compliance policies
    (``--policies``).

Usage:
    python -m simulator.scripts.bootstrap_orgs
    python -m simulator.scripts.bootstrap_orgs --only scribemd
    python -m simulator.scripts.bootstrap_orgs --policies
    python -m simulator.scripts.bootstrap_orgs --no-baa  # skip BAA seed
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

import httpx

from simulator.shared.vera_setup import (
    CUSTOMERS,
    ENV_LOCAL,
    CustomerSpec,
    _key_var,
    _vera_url,
    get_api_key,
    register_org,
    validate_key_org_match,
    write_key_to_env_local,
)


def _maybe_register_policies(slug: str, api_key: str, api_url: str) -> None:
    """Best-effort: install per-customer policies if a policies module exists."""
    try:
        if slug == "scribemd":
            from simulator.customers.scribemd.policies import register_policies

            print(f"  Installing policies for {slug}...")
            register_policies(api_url, api_key)
        else:
            print(f"  (no policies module yet for {slug})")
    except ImportError:
        print(f"  (policies module not implemented for {slug})")
    except Exception as e:  # noqa: BLE001
        print(f"  ! policy registration failed for {slug}: {e}", file=sys.stderr)


def _org_already_exists(
    api_url: str, display_name: str
) -> Optional[dict]:
    """Return the org dict from ``GET /v1/dev/orgs?name=<display>`` or None.

    Returns ``None`` if the dev endpoint isn't reachable (e.g. backend
    isn't in dev mode); the caller's ``register_org`` call will surface
    the actionable error. Otherwise returns the matching org dict.
    """
    try:
        resp = httpx.get(
            f"{api_url}/v1/dev/orgs",
            params={"name": display_name},
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        print(f"  ! could not check for existing org: {exc!s}", file=sys.stderr)
        return None
    if resp.status_code != 200:
        return None
    orgs = resp.json().get("orgs", [])
    return orgs[0] if orgs else None


def _handle_slug(
    spec: CustomerSpec,
    *,
    api_url: str,
    with_baa: bool,
    install_policies: bool,
) -> None:
    """Bootstrap one slug. Prints progress + warnings."""
    slug = spec.slug
    print(f"[{slug}] {spec.display_name}")

    existing_key = get_api_key(slug)
    existing_org = _org_already_exists(api_url, spec.display_name)

    if existing_key:
        # Validate the env-file key actually belongs to the slug's org
        # (closes ``stale-bootstrap-key-tied-to-different-org``).
        matches, err = validate_key_org_match(
            api_url, existing_key, spec.display_name
        )
        if matches:
            print("  · key already in .env.local and validated against expected org")
            if install_policies:
                _maybe_register_policies(slug, existing_key, api_url)
            return
        else:
            # WARN — operator action required. We deliberately do NOT
            # auto-overwrite a stale key because the env file is the
            # only place a raw key lives once minted (we can't re-read
            # it from the backend). Silently overwriting would lose
            # the operator's record of which org the key authorizes.
            print(f"  ! WARNING: {err}", file=sys.stderr)
            print(
                f"  ! Delete the {_key_var(slug)} line from "
                f"{ENV_LOCAL} and re-run to mint a fresh key.",
                file=sys.stderr,
            )
            return

    if existing_org is not None:
        # The slug's org already exists on the backend, but we don't
        # have its raw key locally (raw keys are unrecoverable from
        # the DB). The operator must either restore the key into
        # .env.local manually or accept a fresh duplicate key for the
        # same org (which our create path can't do because of the
        # unique-name constraint). We surface the situation cleanly.
        print(
            f"  ! org {spec.display_name!r} (id={existing_org['org_id']}) "
            f"already exists on backend but no key in .env.local",
            file=sys.stderr,
        )
        print(
            f"  ! To recover: restore the raw key into {ENV_LOCAL} as "
            f"{_key_var(slug)}=<key>, or delete the org via direct DB "
            "access and re-run.",
            file=sys.stderr,
        )
        return

    # Brand-new provision.
    print(f"  · creating org on {api_url} (with_baa={with_baa})...")
    try:
        _, raw_key = register_org(spec, api_url=api_url, with_baa=with_baa)
    except Exception as exc:  # noqa: BLE001
        print(f"  ! registration failed: {exc}", file=sys.stderr)
        return
    write_key_to_env_local(slug, raw_key)
    print(f"  · wrote {_key_var(slug)} to .env.local")
    if install_policies:
        _maybe_register_policies(slug, raw_key, api_url)


def main_for_tests(
    *,
    only: Optional[list[str]] = None,
    with_baa: bool = True,
    install_policies: bool = False,
    api_url: Optional[str] = None,
) -> int:
    """Programmatic entry point for unit tests — bypasses argparse.

    Mirrors ``main()`` but skips ``sys.argv`` parsing so test code can
    stub HTTP and invoke the bootstrap loop directly.
    """
    api_url = (api_url or _vera_url()).rstrip("/")
    targets = only or list(CUSTOMERS.keys())
    for slug in targets:
        if slug not in CUSTOMERS:
            print(f"  ! skipping unknown slug: {slug}", file=sys.stderr)
            continue
        _handle_slug(
            CUSTOMERS[slug],
            api_url=api_url,
            with_baa=with_baa,
            install_policies=install_policies,
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bootstrap Vera dev orgs for the simulator's mock customers. "
            "Uses POST /v1/dev/orgs (requires ENVIRONMENT=development on "
            "the backend)."
        ),
    )
    parser.add_argument(
        "--only",
        action="append",
        default=None,
        help="Only bootstrap these slugs. Repeatable.",
    )
    parser.add_argument(
        "--policies",
        action="store_true",
        help=(
            "Also register each customer's compliance policies after "
            "registration."
        ),
    )
    parser.add_argument(
        "--no-baa",
        dest="with_baa",
        action="store_false",
        default=True,
        help=(
            "Skip the active-BAA seed (useful for Scenario 3 stale-BAA "
            "Gate 3 tests). Default seeds an active BAA + wildcard scope."
        ),
    )
    parser.add_argument(
        "--api-url",
        default=None,
        help="Vera API URL. Defaults to VERA_API_URL env var.",
    )
    args = parser.parse_args()

    api_url = (args.api_url or _vera_url()).rstrip("/")
    targets = args.only or list(CUSTOMERS.keys())

    print(f"Vera API URL: {api_url}")
    print(f"Will bootstrap {len(targets)} customer(s): {targets}")
    print(f"Keys will be written to: {ENV_LOCAL}")
    print(f"with_baa: {args.with_baa}\n")

    for slug in targets:
        if slug not in CUSTOMERS:
            print(f"  ! skipping unknown slug: {slug}", file=sys.stderr)
            continue
        _handle_slug(
            CUSTOMERS[slug],
            api_url=api_url,
            with_baa=args.with_baa,
            install_policies=args.policies,
        )
        print()

    print("Done. Run `python -m simulator.modes.demo <slug>` to exercise a customer.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
