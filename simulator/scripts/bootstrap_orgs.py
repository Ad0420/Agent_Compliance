"""Bootstrap a Vera production org for every mock customer.

One-time setup. Idempotent at the env-var level — if `.env.local` already
holds a key for a given customer slug, that slug is skipped.

Each successful registration:
  1. Calls POST /v1/register on Vera (no auth required).
  2. Persists the resulting raw key to `.env.local` as
     `VERA_API_KEY_<SLUG>=...`.
  3. Optionally registers the customer's compliance policies (--policies).

Usage:
    python -m simulator.scripts.bootstrap_orgs
    python -m simulator.scripts.bootstrap_orgs --only scribemd
    python -m simulator.scripts.bootstrap_orgs --policies
"""

from __future__ import annotations

import argparse
import sys

from simulator.shared.vera_setup import (
    CUSTOMERS,
    ENV_LOCAL,
    _vera_url,
    get_api_key,
    register_org,
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bootstrap Vera production orgs for the simulator's mock customers."
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
        help="Also register each customer's compliance policies after registration.",
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
    print(f"Keys will be written to: {ENV_LOCAL}\n")

    for slug in targets:
        if slug not in CUSTOMERS:
            print(f"  ! skipping unknown slug: {slug}", file=sys.stderr)
            continue
        spec = CUSTOMERS[slug]
        existing = get_api_key(slug)
        if existing:
            print(f"[{slug}] {spec.display_name} — already bootstrapped (key in .env.local)")
            if args.policies:
                _maybe_register_policies(slug, existing, api_url)
            continue
        print(f"[{slug}] {spec.display_name} — registering org on {api_url}...")
        try:
            raw_key = register_org(spec, api_url=api_url)
        except Exception as e:  # noqa: BLE001
            print(f"  ! registration failed: {e}", file=sys.stderr)
            continue
        write_key_to_env_local(slug, raw_key)
        print(f"  · wrote VERA_API_KEY_{slug.upper()} to .env.local")
        if args.policies:
            _maybe_register_policies(slug, raw_key, api_url)

    print("\nDone. Run `python -m simulator.modes.demo <slug>` to exercise a customer.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
