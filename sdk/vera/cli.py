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
from collections import deque
from pathlib import Path
from typing import Any

import click

from .client import VeraClient
from .codemod import MigrationOptions, migrate_source
from .codemod.audit_to_gate import iter_python_files, make_diff
from .errors import (
    VeraAuthError,
    VeraError,
    VeraNetworkError,
    VeraServerError,
    VeraTimeoutError,
    VeraValidationError,
)

# Cap on the in-memory ``seen_ids`` cache used by ``vera tail --follow`` so
# long-running sessions don't grow unbounded.
SEEN_BOUND = 10000


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


def _mask_api_key(api_key: str) -> str:
    """Mask an API key for display.

    Returns ``(unset)`` for an empty key, ``***`` for keys shorter than 12
    characters (typos, fixture values — last 4 chars too revealing), and
    ``...<last4>`` otherwise. Real Vera API keys are ``al_live_`` (8 chars)
    plus 32 random chars = 40 chars total, well above the 12-char floor.
    """
    if not api_key:
        return "(unset)"
    if len(api_key) < 12:
        return "***"
    return "..." + api_key[-4:]


@config.command("show")
@click.option(
    "--reveal-secrets",
    is_flag=True,
    help="Show full api_key (default: masked).",
)
def config_show(reveal_secrets: bool) -> None:
    """Print the effective Vera configuration (env vars + defaults).

    Does not attempt to construct a :class:`VeraClient` — purely env-var
    introspection. Use ``vera ping`` to verify the config actually works
    (constructor + auth round-trip).

    Useful for verifying that ``VERA_*`` env vars are picked up correctly
    in your deployment environment (Lambda, ECS, Railway, etc.) even when
    the constructor would reject the current values.
    """
    api_key = os.environ.get("VERA_API_KEY", "")
    api_url = os.environ.get("VERA_API_URL", "") or "https://api.usevera.xyz"
    agent_name = os.environ.get("VERA_AGENT_NAME", "") or "default-agent"
    agent_version = os.environ.get("VERA_AGENT_VERSION", "")
    model_id = os.environ.get("VERA_MODEL_ID", "")
    framework = os.environ.get("VERA_FRAMEWORK", "")
    spool_path = os.environ.get("VERA_SPOOL_PATH", "")
    dev_mode = _env_truthy("VERA_DEV")

    masked_key = api_key if reveal_secrets else _mask_api_key(api_key)

    rows = [
        ("api_url", api_url),
        ("api_key", masked_key),
        ("agent_name", agent_name),
        ("agent_version", agent_version or "(unset)"),
        ("model_id", model_id or "(unset)"),
        ("framework", framework or "(unset)"),
        ("persistent_buffer_path", spool_path or "(off)"),
        ("dev_mode", "on" if dev_mode else "off"),
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


@cli.command()
@click.option(
    "--timeout", type=float, default=5.0, help="Request timeout in seconds."
)
def ping(timeout: float) -> None:
    """Verify the API key authenticates against Vera.

    Exits 0 on success (200 from /v1/verify), 1 on auth/timeout/network/Vera
    failures, 2 on unexpected exceptions.
    """
    api_url = os.environ.get("VERA_API_URL", "") or "https://api.usevera.xyz"
    click.echo(f"Connecting to {api_url}…", err=True)
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
    except VeraServerError as e:
        click.echo(f"FAIL Server error: {e}", err=True)
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
    # Bounded seen-id cache. Without a cap, a long-running ``--follow``
    # session would leak ~50MB/day at moderate volume. The deque holds
    # insertion order and lets us evict the oldest entry once the cap is
    # hit; the set keeps O(1) membership lookups in sync.
    seen_ids_set: set[str] = set()
    seen_ids_order: deque[str] = deque(maxlen=SEEN_BOUND)

    def _mark_seen(rid: str) -> None:
        """Add ``rid`` to the bounded seen-set, evicting the oldest if full."""
        if rid in seen_ids_set:
            return
        if len(seen_ids_order) == SEEN_BOUND:
            # deque is at maxlen — its next append will silently drop the
            # leftmost entry. Mirror that eviction in the companion set.
            evicted = seen_ids_order[0]
            seen_ids_set.discard(evicted)
        seen_ids_order.append(rid)
        seen_ids_set.add(rid)

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
                    r for r in records if r.get("id") not in seen_ids_set
                ]
                for r in fresh:
                    rid = r.get("id")
                    if rid is not None:
                        _mark_seen(rid)
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
            except VeraAuthError as e:
                # Auth errors won't self-heal — retrying in --follow mode
                # would spin forever. Exit immediately regardless of follow.
                click.echo(f"FAIL Authentication failed: {e}", err=True)
                sys.exit(1)
            except VeraValidationError as e:
                # 4xx other than 401/429 — usually a programmer error in
                # our filters. Won't self-heal either.
                click.echo(f"FAIL {e}", err=True)
                sys.exit(1)
            except (
                VeraTimeoutError,
                VeraNetworkError,
                VeraServerError,
            ) as e:
                if not follow:
                    click.echo(
                        f"FAIL {type(e).__name__}: {e}", err=True
                    )
                    sys.exit(1)
                click.echo(
                    f"WARN Transient error: {e} "
                    f"(retrying in {interval}s)",
                    err=True,
                )
                time.sleep(interval)
            except VeraError as e:
                click.echo(f"FAIL {e}", err=True)
                if not follow:
                    sys.exit(1)
                # In follow mode, sleep + retry for unclassified errors.
                time.sleep(interval)
    finally:
        try:
            client.close()
        except Exception:
            pass


def _print_record(r: dict) -> None:
    # Coerce every field through ``str`` first so ``None`` values (or any
    # other non-string type the server might return) can't blow up width-
    # formatted f-strings with ``TypeError``.
    seq = r.get("sequence_number")
    seq_str = str(seq) if seq is not None else "?"
    ts = r.get("recorded_at") or "?"
    agent = r.get("agent_name") or "?"
    action = r.get("action_name") or "?"
    result = r.get("result") or "?"
    click.echo(
        f"[{seq_str:>6}] {ts}  {agent:<24}  {action:<32}  {result}"
    )


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@cli.group()
def codemod() -> None:
    """Mechanical source rewrites (Phase 1 PR 9 / Stream D8)."""


@codemod.command("audit-to-gate")
@click.argument(
    "path",
    type=click.Path(exists=True, file_okay=True, dir_okay=True, path_type=Path),
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print the unified diff for each changed file; do NOT write.",
)
@click.option(
    "--wrap-callsites",
    is_flag=True,
    help=(
        "Wrap call sites of @vera.gate-decorated functions in a "
        "try/except (vera.PendingReview, vera.PolicyBlock) skeleton. "
        "Off by default because it produces opinionated diffs."
    ),
)
@click.option(
    "--no-init-todo",
    is_flag=True,
    help=(
        "Skip inserting the agent_type= TODO comment on vera.init() "
        "calls that don't already pass agent_type=."
    ),
)
@click.option(
    "--check",
    is_flag=True,
    help=(
        "CI mode: exit 1 if any file would change. Implies --dry-run. "
        "Matches the convention of ``ruff format --check``."
    ),
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="Show per-file per-transform counter breakdown.",
)
def codemod_audit_to_gate(
    path: Path,
    dry_run: bool,
    wrap_callsites: bool,
    no_init_todo: bool,
    check: bool,
    verbose: bool,
) -> None:
    """Migrate @vera.audit usage to @vera.gate across PATH.

    PATH may be a single ``.py`` file or a directory (recurses into
    ``.py`` files, pruning ``__pycache__``, ``.git``, ``.venv``,
    ``node_modules``, ``dist``, ``build``, and ``*.egg-info``).

    Per-file opt-out: prefix the file with ``# noqa: VERA-CODEMOD`` to
    skip it entirely.

    See ``sdk/MIGRATION.md`` for the full migration narrative.
    """
    options = MigrationOptions(
        wrap_callsites=wrap_callsites,
        init_todo=not no_init_todo,
    )
    # ``--check`` implies dry-run (we never modify in check mode).
    effective_dry_run = dry_run or check

    migrated = 0
    skipped = 0
    unchanged = 0
    errors = 0
    files_seen = 0

    for file_path in iter_python_files(path):
        files_seen += 1
        try:
            # Read the source up front for the diff. ``migrate_file``
            # with ``write=False`` returns the rewritten source; we
            # diff against the original ourselves.
            try:
                original = file_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                click.echo(
                    f"SKIP {file_path}: read error: {exc}", err=True
                )
                skipped += 1
                continue

            result = migrate_source(original, options=options)

            if result.skipped_reason:
                if verbose:
                    click.echo(
                        f"SKIP {file_path}: {result.skipped_reason}",
                        err=True,
                    )
                skipped += 1
                continue

            if not result.changed:
                if verbose:
                    click.echo(f"UNCHANGED {file_path}")
                unchanged += 1
                continue

            migrated += 1
            if effective_dry_run:
                diff = make_diff(
                    original, result.new_source, path=str(file_path)
                )
                if diff:
                    click.echo(diff, nl=False)
            else:
                file_path.write_text(result.new_source, encoding="utf-8")

            if verbose:
                counters_str = ", ".join(
                    f"{k}={v}" for k, v in sorted(result.counters.items())
                )
                action = "WOULD MIGRATE" if effective_dry_run else "MIGRATED"
                click.echo(
                    f"{action} {file_path}: {counters_str}", err=True
                )
        except Exception as exc:  # noqa: BLE001 — never crash whole run
            click.echo(
                f"ERROR {file_path}: {type(exc).__name__}: {exc}",
                err=True,
            )
            errors += 1

    # Summary
    click.echo("", err=True)
    click.echo(
        f"summary: {migrated} migrated, {unchanged} unchanged, "
        f"{skipped} skipped, {errors} errors  "
        f"({files_seen} .py files scanned)",
        err=True,
    )

    if check and migrated > 0:
        sys.exit(1)
    if errors > 0 and not check:
        # Surface read/parse errors as exit 2 (distinct from --check's
        # "pending changes" exit 1, matching ``ruff``'s convention).
        sys.exit(2)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
