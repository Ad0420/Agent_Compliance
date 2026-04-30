"""TriageGuard's compliance policies, registered against its Vera org.

Vera's policy engine fires after-the-fact (when a record is written or
a chain is verified) and emits flag/email actions. Hard gating of agent
actions happens at the SDK layer via `request_approval` — see
`workflows/session.py`.

Run `python -m simulator.customers.triageguard.policies --slug triageguard`
to install these against a Vera org. Idempotent: existing policies with
the same name are skipped.
"""

from __future__ import annotations

import argparse
import sys

import httpx

from simulator.shared.vera_setup import _vera_url, get_api_key


TRIAGEGUARD_POLICIES = [
    {
        "name": "TriageGuard: Unknown agent activity",
        "description": (
            "Flag any action recorded by an agent we did not register. "
            "Catches rogue scripts hitting the org's API key."
        ),
        "condition_type": "unknown_agent",
        "condition_params": {
            "known_agents": [
                "triageguard-triage-classifier",
                "triageguard-red-flag-detector",
                "triageguard-routing-committer",
            ]
        },
        "action": "flag",
        "severity": "high",
    },
    {
        "name": "TriageGuard: Missing reasoning trace",
        "description": (
            "FINRA-style supervision rule for medtech: every agent action "
            "must carry reasoning. Flag any record without it."
        ),
        "condition_type": "missing_reasoning",
        "condition_params": {},
        "action": "flag",
        "severity": "medium",
    },
    {
        "name": "TriageGuard: Burst of failed red-flag detections",
        "description": (
            "Three consecutive failed red-flag detections suggests the "
            "model regressed or upstream input changed shape — block "
            "auto-routing until investigated."
        ),
        "condition_type": "consecutive_failures",
        "condition_params": {
            "threshold": 3,
            "agent_name": "triageguard-red-flag-detector",
        },
        "action": "email",
        "severity": "high",
    },
]


def register_policies(api_url: str, api_key: str) -> list[dict]:
    """Idempotently install TriageGuard's policies against a Vera org."""
    headers = {"Authorization": f"Bearer {api_key}"}

    existing = httpx.get(f"{api_url}/v1/policies", headers=headers, timeout=30.0)
    existing.raise_for_status()
    existing_names = {p["name"] for p in existing.json().get("policies", [])}

    created = []
    for policy in TRIAGEGUARD_POLICIES:
        if policy["name"] in existing_names:
            print(f"  · skip (exists): {policy['name']}")
            continue
        resp = httpx.post(
            f"{api_url}/v1/policies", json=policy, headers=headers, timeout=30.0
        )
        resp.raise_for_status()
        created.append(resp.json())
        print(f"  · created: {policy['name']}")
    return created


def _main() -> int:
    parser = argparse.ArgumentParser(description="Register TriageGuard policies on Vera.")
    parser.add_argument(
        "--slug",
        default="triageguard",
        help="Customer slug to look up the API key from .env.local.",
    )
    parser.add_argument(
        "--api-url",
        default=None,
        help="Vera API URL. Defaults to VERA_API_URL env var.",
    )
    args = parser.parse_args()

    api_key = get_api_key(args.slug)
    if not api_key:
        print(
            f"No API key for slug={args.slug!r}. "
            "Run `python -m simulator.scripts.bootstrap_orgs` first.",
            file=sys.stderr,
        )
        return 2

    api_url = args.api_url or _vera_url()
    print(f"Registering policies against {api_url} for org slug={args.slug!r}...")
    register_policies(api_url, api_key)
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
