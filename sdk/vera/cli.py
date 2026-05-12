"""Vera SDK command-line interface.

Three subcommands for ops + dev verification:

* ``vera config show`` — print resolved configuration (env vars + defaults)
* ``vera ping`` — verify the API key authenticates against Vera
* ``vera tail`` — tail recent records for the org

Run ``vera --help`` for all options. Each subcommand has its own ``--help``.

Designed to be safe in production: no destructive operations, no record
writes, only authenticated reads + config introspection.
"""

from __future__ import annotations

import json as _json
import os
import sys
import time
from typing import Any

import click

from .client import VeraClient
from .errors import VeraAuthError, VeraError, VeraNetworkError, VeraTimeoutError

try:  # ``vera-sdk`` ships without a runtime __version__ attribute today.
    from importlib.metadata import PackageNotFoundError, version as _pkg_version

    try:
        _SDK_VERSION = _pkg_version("vera-sdk")
    except PackageNotFoundError:  # pragma: no cover — dev install edge case
        _SDK_VERSION = "unknown"
except Exception:  # pragma: no cover — defensive
    _SDK_VERSION = "unknown"


@click.group()
@click.version_option(_SDK_VERSION, package_name="vera-sdk")
def cli() -> None:
    """Vera SDK command-line interface."""


@cli.group()
def config() -> None:
    """Configuration introspection."""


@config.command("show")
@click.option(
    "--reveal-secrets",
    is_flag=True,
    help="Show full api_key (default: masked).",
)
def config_show(reveal_secrets: bool) -> None:
    """Print the effective Vera configuration (env vars + defaults).

    Useful for verifying that VERA_* env vars are picked up correctly in
    your deployment environment (Lambda, ECS, Railway, etc.)
    """
    client = VeraClient()  # constructor reads env vars via DX-E
    api_key = os.environ.get("VERA_API_KEY", "")
    if not reveal_secrets and api_key:
        # Mask all but last 4 chars
        masked = "..." + api_key[-4:] if len(api_key) > 8 else "***"
    else:
        masked = api_key or "(unset)"

    rows = [
        ("api_url", client.api_url),
        ("api_key", masked),
        ("agent_name", client.agent_name),
        ("agent_version", client.agent_version or "(unset)"),
        ("model_id", client.model_id or "(unset)"),
        ("framework", client.framework or "(unset)"),
        (
            "persistent_buffer_path",
            getattr(client, "_persistent_buffer_path", None) or "(off)",
        ),
        ("dev_mode", "on" if _env_truthy("VERA_DEV") else "off"),
    ]
    width = max(len(k) for k, _ in rows)
    for k, v in rows:
        click.echo(f"  {k.ljust(width)}  {v}")

    if not reveal_secrets and api_key:
        click.echo("", err=True)
        click.echo(
            "(api_key shown masked — pass --reveal-secrets to print in full)",
            err=True,
        )

    try:
        client.close()
    except Exception:
        pass


@cli.command()
@click.option(
    "--timeout", type=float, default=5.0, help="Request timeout in seconds."
)
def ping(timeout: float) -> None:
    """Verify the API key authenticates against Vera.

    Exits 0 on success (200 from /v1/verify), 1 on auth/timeout/network/Vera
    failures, 2 on unexpected exceptions.
    """
    try:
        client = VeraClient(timeout=timeout)
        start = time.perf_counter()
        result = client.verify_chain()  # uses /v1/verify endpoint
        elapsed_ms = (time.perf_counter() - start) * 1000
        click.echo(
            f"OK Authenticated to {client.api_url} in {elapsed_ms:.1f}ms"
        )
        if isinstance(result, dict):
            click.echo(f"  status: {result.get('status', 'ok')}")
            if "chain_length" in result:
                click.echo(f"  chain_length: {result['chain_length']}")
        try:
            client.close()
        except Exception:
            pass
        sys.exit(0)
    except VeraAuthError as e:
        click.echo(f"FAIL Authentication failed: {e}", err=True)
        sys.exit(1)
    except VeraTimeoutError as e:
        click.echo(f"FAIL Timeout after {timeout}s: {e}", err=True)
        sys.exit(1)
    except VeraNetworkError as e:
        click.echo(f"FAIL Network error: {e}", err=True)
        sys.exit(1)
    except VeraError as e:
        click.echo(f"FAIL Vera error: {e}", err=True)
        sys.exit(1)
    except Exception as e:  # noqa: BLE001 — top-level CLI catch-all
        click.echo(f"FAIL Unexpected error: {e}", err=True)
        sys.exit(2)


@cli.command()
@click.option(
    "--limit", type=int, default=50, help="How many records to fetch (max 500)."
)
@click.option("--agent", type=str, default=None, help="Filter by agent_name.")
@click.option(
    "--result",
    type=click.Choice(["success", "failure", "blocked"]),
    default=None,
)
@click.option(
    "--follow",
    "-f",
    is_flag=True,
    help="Continuously poll for new records.",
)
@click.option(
    "--interval",
    type=float,
    default=2.0,
    help="Poll interval in seconds (with --follow).",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Output JSON lines instead of formatted text.",
)
def tail(
    limit: int,
    agent: str | None,
    result: str | None,
    follow: bool,
    interval: float,
    as_json: bool,
) -> None:
    """Tail recent records for this org.

    Uses GET /v1/actions (the query_actions API). Without --follow, prints
    the most recent N records and exits. With --follow, polls every
    --interval seconds and prints new records as they arrive.
    """
    limit = max(1, min(500, limit))
    client = VeraClient()

    last_seq = 0
    seen_ids: set[str] = set()

    try:
        while True:
            try:
                filters: dict[str, Any] = {"limit": limit}
                if agent:
                    filters["agent_name"] = agent
                if result:
                    filters["result"] = result
                if follow and last_seq > 0:
                    filters["since_sequence_number"] = last_seq
                resp = client.query_actions(**filters)
                records = (
                    resp.get("records") if isinstance(resp, dict) else resp
                )
                records = records or []

                # Filter dupes within a session.
                fresh = [
                    r for r in records if r.get("id") not in seen_ids
                ]
                for r in fresh:
                    rid = r.get("id")
                    if rid is not None:
                        seen_ids.add(rid)
                    if as_json:
                        click.echo(_json.dumps(r, default=str))
                    else:
                        _print_record(r)
                    seq = r.get("sequence_number")
                    if isinstance(seq, int) and seq > last_seq:
                        last_seq = seq

                if not follow:
                    break
                time.sleep(interval)
            except KeyboardInterrupt:
                click.echo("\n(interrupted)", err=True)
                break
            except VeraError as e:
                click.echo(f"FAIL {e}", err=True)
                if not follow:
                    sys.exit(1)
                # In follow mode, sleep + retry.
                time.sleep(interval)
    finally:
        try:
            client.close()
        except Exception:
            pass


def _print_record(r: dict) -> None:
    seq = r.get("sequence_number", "?")
    ts = r.get("recorded_at", "?")
    agent = r.get("agent_name", "?")
    action = r.get("action_name", "?")
    result = r.get("result", "?")
    click.echo(
        f"[{seq:>6}] {ts}  {agent:<24}  {action:<32}  {result}"
    )


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
