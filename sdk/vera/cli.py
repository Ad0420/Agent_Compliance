"""Vera SDK command-line interface.

Subcommands for setup, ops, and dev verification:

* ``vera init`` — scaffold an ``.env`` and walk a developer through API-key
  creation (Phase 1 PR 11 / Stream E1).
* ``vera quickstart`` — generate a demo file, run it, open the dashboard
  (Phase 1 PR 11 / Stream E2).
* ``vera doctor`` — diagnostic checks against config, network, auth,
  tenant resolver, spool, and SDK version (Phase 1 PR 11 / Stream E3).
* ``vera review-status <review_id>`` — Phase 2 stub (Phase 1 PR 11 / E4).
* ``vera config show`` — print resolved configuration (env vars + defaults).
* ``vera ping`` — verify the API key authenticates against Vera.
* ``vera tail`` — tail recent records for the org.
* ``vera codemod audit-to-gate`` — migrate ``@vera.audit`` to ``@vera.gate``
  (Phase 1 PR 9 / Stream D8).

Run ``vera --help`` for all options. Each subcommand has its own ``--help``.

Designed to be safe in production: no destructive operations, no record
writes, only authenticated reads + config introspection.
"""

from __future__ import annotations

import getpass
import json as _json
import os
import re
import subprocess
import sys
import time
import webbrowser
from collections import deque
from pathlib import Path
from typing import Any

import click

from .client import VeraClient
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
    # Lazy import — keeps libcst optional. Users who install
    # ``vera-sdk`` (no extras) get a friendly error pointing at the
    # extras_require knob instead of an ImportError at CLI startup.
    try:
        from .codemod import (
            MigrationOptions,
            iter_python_files,
            make_diff,
            migrate_source,
        )
    except ImportError as exc:
        click.echo(
            f"ERROR: vera codemod requires libcst (missing: {exc.name}).\n"
            "Install with: pip install 'vera-sdk[codemod]'",
            err=True,
        )
        sys.exit(2)

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
                # Read errors are real errors (the file exists, we
                # found it via the walker, but couldn't open / decode
                # it). Surface as exit code 2 in the rollup. Syntax
                # errors and per-file opt-outs are still "skipped"
                # since they're expected forms of "this file can't be
                # processed but the run is fine".
                click.echo(
                    f"ERROR {file_path}: read error: {exc}", err=True
                )
                errors += 1
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

    # Exit codes (matching ``ruff``'s convention):
    #   2 — read/parse errors during the run (always, regardless of --check)
    #   1 — --check mode and at least one file would change
    #   0 — clean run
    # Errors take precedence: a partial failure that also surfaced a
    # pending change should still exit 2 so CI doesn't conflate a real
    # bug with a yet-to-be-applied migration.
    if errors > 0:
        sys.exit(2)
    if check and migrated > 0:
        sys.exit(1)
    sys.exit(0)


# ---------------------------------------------------------------------------
# Phase 1 PR 11 / Stream E — onboarding commands.
# ---------------------------------------------------------------------------

# API-key shape: ``al_test_`` or ``al_live_`` prefix + at least 16 chars of
# entropy (real keys are 32, but smaller test fixtures should still pass the
# shape check without being mistaken for a typo).
_API_KEY_RE = re.compile(r"^al_(test|live)_[A-Za-z0-9_\-]{16,}$")

# Default dashboard URL for ``vera init`` / ``vera quickstart``. Customisable
# via ``--dashboard-url`` flag or ``VERA_DASHBOARD_URL`` env var so internal
# / staging environments can point at non-prod URLs without a code change.
_DEFAULT_DASHBOARD_URL = "https://app.usevera.xyz"
_DEFAULT_API_URL = "https://api.usevera.xyz"

# Tenant ID for the auto-generated quickstart demo. Re-uses the same regex
# the SDK enforces in :func:`vera._context._validate_tenant_id`.
_TENANT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

# Matches any ASCII control character (incl. newline / carriage return /
# vertical tab) plus DEL. Used to reject URL flags before they get
# interpolated into the .env file or handed to webbrowser.open.
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


def _validate_url(value: str, *, kind: str) -> str:
    """Reject URLs with non-http(s) schemes or control characters.

    ``kind`` is a label for the error message (e.g. "api-url",
    "dashboard-url"). Returns ``value`` unchanged when it passes — callers
    can write ``url = _validate_url(url, kind="api-url")`` inline.

    Rejecting control chars closes a ``.env``-line-injection vector where
    ``--api-url $'http://api.example.com\\nADMIN_PASSWORD=x'`` would
    interpolate a second key=value line into the generated file. Rejecting
    non-http(s) schemes blocks ``javascript:`` / ``file:`` payloads that
    could fire when we hand the URL to ``webbrowser.open``.
    """
    from urllib.parse import urlparse

    if _CONTROL_CHAR_RE.search(value):
        raise click.ClickException(
            f"--{kind} contains control characters; refusing to use it"
        )
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https"):
        raise click.ClickException(
            f"--{kind} must be http(s); got {parsed.scheme or '(no scheme)'}"
        )
    if not parsed.netloc:
        raise click.ClickException(
            f"--{kind} has no host: {value!r}"
        )
    return value


def _is_headless() -> bool:
    """Detect headless environments where ``webbrowser.open`` would fail.

    Returns ``True`` when we should NOT attempt to launch a browser:
    no DISPLAY/WAYLAND_DISPLAY on Linux, an active SSH session, or a CI
    flag. The fallback for headless is to print the URL instead.
    """
    if os.environ.get("CI", "").strip():
        return True
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_CLIENT"):
        return True
    # On macOS / Windows ``webbrowser.open`` works without DISPLAY. The
    # DISPLAY/WAYLAND check is Linux-specific.
    if sys.platform.startswith("linux"):
        if not (
            os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
        ):
            return True
    return False


def _open_browser_or_print(url: str, *, headless_hint: str = "") -> None:
    """Open ``url`` in the default browser, or print it if headless.

    ``headless_hint`` is appended to the printed URL line when we couldn't
    open the browser, e.g. "Visit the URL above to create your API key."
    """
    if _is_headless():
        click.echo(f"  (headless — open in your browser): {url}")
        if headless_hint:
            click.echo(f"  {headless_hint}")
        return
    try:
        opened = webbrowser.open(url, new=2)
    except Exception:  # noqa: BLE001 — webbrowser implementations vary
        opened = False
    if not opened:
        click.echo(f"  (could not open browser — visit): {url}")
        if headless_hint:
            click.echo(f"  {headless_hint}")


def _existing_config_summary(env_file: Path) -> str | None:
    """Return a one-line summary of existing config, or ``None`` if absent.

    Checks the ``.env`` file at ``env_file`` first, then ``VERA_API_KEY``
    in the process env. Returns ``None`` when neither is configured (i.e.
    ``vera init`` should proceed without prompting).
    """
    if env_file.exists():
        return f".env at {env_file} (API key already configured)"
    if os.environ.get("VERA_API_KEY", "").strip():
        return "VERA_API_KEY env var already set"
    return None


def _validate_api_key_shape(key: str) -> bool:
    """Return ``True`` iff ``key`` matches the ``al_test_*`` / ``al_live_*`` shape."""
    return bool(_API_KEY_RE.match(key.strip()))


def _write_env_file(
    env_file: Path,
    *,
    api_key: str,
    api_url: str,
    tenant_id: str = "",
    force: bool = False,
) -> None:
    """Write a minimal ``.env`` with the three Vera variables.

    File mode is set to ``0600`` so the API key isn't world-readable on
    multi-user systems. Parent directory is created with ``0700`` if missing.

    Defense-in-depth: reject control characters in ``api_key`` / ``api_url``
    / ``tenant_id`` before interpolating so a future caller that bypasses
    the CLI flag validators can't inject extra ``KEY=value`` lines into the
    .env. Callers should still validate URL shape via :func:`_validate_url`
    upstream; this is a last-line guard.

    Set ``force=True`` to overwrite an existing file. Without it, an
    existing file raises ``FileExistsError`` so misuse from a non-CLI
    caller can't silently clobber a real config.
    """
    for field_name, field_value in (
        ("api_key", api_key),
        ("api_url", api_url),
        ("tenant_id", tenant_id),
    ):
        if _CONTROL_CHAR_RE.search(field_value):
            raise click.ClickException(
                f"{field_name} contains control characters; refusing to "
                "write .env (would enable line injection)"
            )

    if env_file.exists() and not force:
        raise FileExistsError(
            f"{env_file} already exists — pass force=True to overwrite"
        )

    parent = env_file.parent
    if parent and not parent.exists():
        parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    contents = (
        "# Vera SDK configuration — generated by `vera init`.\n"
        "# Do not commit this file (add `.env` to .gitignore).\n"
        f"VERA_API_KEY={api_key}\n"
        f"VERA_API_URL={api_url}\n"
        f"VERA_TENANT_ID={tenant_id}\n"
    )
    # Open with 0600 from the start so an attacker can't read between
    # creation and a follow-up chmod. (threading-unsafe — fine for CLI.)
    old_umask = os.umask(0o077)
    try:
        env_file.write_text(contents, encoding="utf-8")
        try:
            os.chmod(env_file, 0o600)
        except OSError:
            # Best-effort chmod — Windows / ACL filesystems may refuse.
            pass
    finally:
        os.umask(old_umask)


def _prompt_api_key_with_retries(*, max_attempts: int = 3) -> str:
    """Prompt the user to paste an API key, retrying on shape-mismatch.

    Uses :func:`getpass.getpass` so the key doesn't echo to the terminal.
    Returns the validated key on success; raises ``click.ClickException``
    on the ``max_attempts``-th failure so the CLI exits non-zero.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            key = getpass.getpass(
                "  Paste the new API key (al_test_... or al_live_...) "
                "and press Enter: "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            raise click.ClickException(
                "no API key provided (stdin closed or interrupted)"
            )
        if _validate_api_key_shape(key):
            return key
        remaining = max_attempts - attempt
        if remaining > 0:
            click.echo(
                f"  Key doesn't look right (expected `al_test_...` or "
                f"`al_live_...` with ≥16 chars of entropy). "
                f"{remaining} attempt(s) left.",
                err=True,
            )
    raise click.ClickException(
        f"API key shape invalid after {max_attempts} attempts. "
        "Aborting — re-run `vera init` to try again."
    )


@cli.command(name="init")
@click.option(
    "--dashboard-url",
    type=str,
    default=None,
    help=(
        "Dashboard URL (default: $VERA_DASHBOARD_URL or "
        f"{_DEFAULT_DASHBOARD_URL})."
    ),
)
@click.option(
    "--key",
    "key_flag",
    type=str,
    default=None,
    help="Skip the browser flow and use this API key directly.",
)
@click.option(
    "--env-file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path(".env"),
    show_default=True,
    help="Path to write the .env file.",
)
@click.option(
    "--api-url",
    type=str,
    default=None,
    help=(
        f"Backend API URL written to .env (default: {_DEFAULT_API_URL})."
    ),
)
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite an existing .env or API-key configuration without prompting.",
)
def init_cmd(
    dashboard_url: str | None,
    key_flag: str | None,
    env_file: Path,
    api_url: str | None,
    force: bool,
) -> None:
    """Scaffold a local ``.env`` and walk through API-key creation.

    The default flow opens the dashboard's ``/api-keys`` page, lets the
    user create a key, then asks them to paste it back into the terminal.
    Pass ``--key`` to skip the browser flow (useful in scripts).

    Existing config (a ``.env`` in the target path OR a ``VERA_API_KEY``
    env var) is detected; without ``--force`` we exit 0 with a friendly
    summary instead of clobbering.
    """
    existing = _existing_config_summary(env_file)
    if existing and not force:
        click.echo(f"Vera already configured: {existing}")
        click.echo("  Run `vera doctor` to verify, or re-run with `--force` to overwrite.")
        sys.exit(0)

    effective_api_url = (
        api_url or os.environ.get("VERA_API_URL") or _DEFAULT_API_URL
    )
    effective_dashboard_url = (
        dashboard_url
        or os.environ.get("VERA_DASHBOARD_URL")
        or _DEFAULT_DASHBOARD_URL
    ).rstrip("/")

    # Validate BEFORE we open a browser or write .env so a malicious
    # --api-url / --dashboard-url can't inject extra lines into the file
    # or hand a javascript: / file: payload to webbrowser.open.
    effective_api_url = _validate_url(effective_api_url, kind="api-url")
    effective_dashboard_url = _validate_url(
        effective_dashboard_url, kind="dashboard-url"
    )

    if key_flag is not None:
        api_key = key_flag.strip()
        if not _validate_api_key_shape(api_key):
            raise click.ClickException(
                "--key value doesn't look like a Vera API key "
                "(expected `al_test_...` or `al_live_...` with ≥16 chars)."
            )
    else:
        create_url = f"{effective_dashboard_url}/api-keys?create=1"
        click.echo("Opening the dashboard so you can create an API key…")
        _open_browser_or_print(
            create_url,
            headless_hint="Create a key, then paste it below.",
        )
        api_key = _prompt_api_key_with_retries(max_attempts=3)

    try:
        # ``force=True`` is safe here because we already short-circuited
        # at line 744 if the file existed and ``--force`` wasn't passed.
        _write_env_file(
            env_file,
            api_key=api_key,
            api_url=effective_api_url,
            tenant_id="",
            force=True,
        )
    except OSError as exc:
        raise click.ClickException(
            f"could not write {env_file}: {exc} "
            "(check directory permissions, or pass `--env-file PATH`)"
        )

    key_kind = "live" if api_key.startswith("al_live_") else "test"
    click.echo("")
    click.echo(f"OK Wrote {env_file} (mode 0600, {key_kind} key).")
    click.echo("")
    click.echo("Decorator example:")
    click.echo("")
    click.echo("    import vera")
    click.echo("")
    click.echo("    vera.init(")
    click.echo('        api_key=os.environ["VERA_API_KEY"],')
    click.echo('        default_tenant=os.environ.get("VERA_TENANT_ID", "demo"),')
    click.echo('        agent_type="my_agent",')
    click.echo("    )")
    click.echo("")
    click.echo('    @vera.gate("loans.approve")')
    click.echo("    def approve_loan(applicant_id: str, amount: int) -> bool:")
    click.echo("        ...")
    click.echo("")
    click.echo("Next steps:")
    click.echo("  • `vera doctor` — verify your setup end-to-end")
    click.echo("  • `vera quickstart` — generate + run a 5-minute demo")
    sys.exit(0)


# ---------------------------------------------------------------------------
# vera quickstart — Stream E2.
# ---------------------------------------------------------------------------

_QUICKSTART_DEMO_TEMPLATE = '''"""Vera quickstart demo — auto-generated by `vera quickstart`.

Runs 5 @vera.gate-decorated actions against the configured backend so the
auto-discovery pipeline registers them under the demo tenant.
"""

from __future__ import annotations

import os

import vera

vera.init(
    api_key=os.environ["VERA_API_KEY"],
    default_tenant=os.environ.get("VERA_TENANT_ID", "quickstart_demo"),
    agent_type="quickstart_demo_agent",
)


@vera.gate("demo.greet")
def greet(name: str) -> str:
    return f"Hello, {name}!"


@vera.gate("demo.calculate")
def calculate(x: int, y: int) -> int:
    return x + y


if __name__ == "__main__":
    for i in range(5):
        result = greet(f"World {i}")
        total = calculate(i, i + 1)
        print(f"[{i}] {result} (sum={total})")
    print("")
    print("Demo complete. Open the dashboard to see your decisions.")
'''


def _random_tenant_suffix() -> str:
    """Return a short, URL-safe random suffix for the quickstart tenant.

    8 bytes of randomness (~13 chars of base32) is enough to avoid
    collisions across concurrent quickstart runs on the same org.
    """
    import secrets

    return secrets.token_hex(4)  # 8 chars, hex-safe for the tenant regex


@cli.command(name="quickstart")
@click.option(
    "--demo-file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path("vera_quickstart_demo.py"),
    show_default=True,
    help="Path to write the generated demo file.",
)
@click.option(
    "--tenant",
    type=str,
    default=None,
    help=(
        "Tenant ID for this quickstart run "
        "(default: `quickstart_<random>`)."
    ),
)
@click.option(
    "--dashboard-url",
    type=str,
    default=None,
    help=f"Dashboard URL (default: ${{VERA_DASHBOARD_URL}} or {_DEFAULT_DASHBOARD_URL}).",
)
@click.option(
    "--no-open",
    is_flag=True,
    help="Don't open the dashboard at the end (useful in CI).",
)
@click.option(
    "--non-interactive",
    is_flag=True,
    help=(
        "If no .env / API key is configured, exit 1 with a hint "
        "instead of dropping into `vera init`."
    ),
)
@click.option(
    "--skip-run",
    is_flag=True,
    help="Generate the demo file but don't execute it (useful in tests).",
)
def quickstart_cmd(
    demo_file: Path,
    tenant: str | None,
    dashboard_url: str | None,
    no_open: bool,
    non_interactive: bool,
    skip_run: bool,
) -> None:
    """Generate a demo file, run it, and open the dashboard.

    The 5-minute zero-to-record path: confirms the SDK is importable,
    confirms config is present (offers to run ``vera init`` if not),
    writes a small demo with two ``@vera.gate`` actions, runs them
    against the configured backend, then opens the dashboard so the
    user can see their first records land.
    """
    # 1. Pip sanity. ``import vera`` is implicit since we're running from
    # the CLI module, but we double-check ``__version__`` lines up with
    # the wheel pip actually installed (catches stale shadow installs).
    try:
        from importlib.metadata import PackageNotFoundError, version as _pkg_version

        try:
            pkg_ver = _pkg_version("vera-sdk")
        except PackageNotFoundError:
            pkg_ver = "unknown"
    except Exception:  # pragma: no cover — defensive
        pkg_ver = "unknown"
    click.echo(f"vera SDK {pkg_ver} installed.")

    # 2. Config check.
    api_key = os.environ.get("VERA_API_KEY", "").strip()
    if not api_key and Path(".env").exists():
        # Try to read .env line-by-line — we don't depend on python-dotenv
        # for this path because the SDK doesn't ship it. The subprocess we
        # run later inherits this dict so the demo sees the key.
        for line in Path(".env").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("VERA_API_KEY="):
                api_key = line.split("=", 1)[1].strip()
                break

    if not api_key:
        if non_interactive:
            raise click.ClickException(
                "no VERA_API_KEY found. Run `vera init` first, "
                "or re-run without `--non-interactive`."
            )
        click.echo("No Vera config found — running `vera init` first.")
        # Hand off to init's flow. We import the callback directly so we
        # don't have to fork a subprocess and re-prompt the user twice.
        ctx = click.get_current_context()
        ctx.invoke(init_cmd, dashboard_url=dashboard_url, key_flag=None,
                   env_file=Path(".env"), api_url=None, force=False)
        # Reload after init wrote the file.
        api_key = ""
        if Path(".env").exists():
            for line in Path(".env").read_text(encoding="utf-8").splitlines():
                if line.startswith("VERA_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
                    break
        if not api_key:
            raise click.ClickException(
                "still no API key after `vera init` — aborting quickstart."
            )

    # 3. Tenant.
    if tenant is None:
        tenant = f"quickstart_{_random_tenant_suffix()}"
    if not _TENANT_ID_RE.match(tenant):
        raise click.ClickException(
            f"invalid --tenant value {tenant!r} "
            "(must match `^[a-zA-Z0-9_-]{1,64}$`)."
        )

    # 4. Generate demo file.
    try:
        demo_file.write_text(_QUICKSTART_DEMO_TEMPLATE, encoding="utf-8")
    except OSError as exc:
        raise click.ClickException(
            f"could not write {demo_file}: {exc}"
        )
    click.echo(f"Wrote demo file: {demo_file}")

    # 5. Run the demo (unless --skip-run).
    if not skip_run:
        click.echo(f"Running demo (tenant={tenant})…")
        sub_env = os.environ.copy()
        sub_env["VERA_API_KEY"] = api_key
        sub_env["VERA_TENANT_ID"] = tenant
        # Use the same interpreter we're running on so the demo picks up
        # the same vera install.
        proc = subprocess.run(
            [sys.executable, str(demo_file)],
            env=sub_env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.stdout:
            for line in proc.stdout.rstrip().splitlines():
                click.echo(f"  {line}")
        if proc.returncode != 0:
            if proc.stderr:
                click.echo(proc.stderr, err=True)
            raise click.ClickException(
                f"demo exited with code {proc.returncode} — "
                "see stderr above. Try `vera doctor` to diagnose."
            )
        # Give the backend a beat to ingest before we open the dashboard.
        time.sleep(1.5)

    # 6. Open dashboard.
    effective_dashboard_url = (
        dashboard_url
        or os.environ.get("VERA_DASHBOARD_URL")
        or _DEFAULT_DASHBOARD_URL
    ).rstrip("/")
    # Validate BEFORE we hand the URL to webbrowser.open — blocks
    # javascript: / file: schemes and control-char injection.
    effective_dashboard_url = _validate_url(
        effective_dashboard_url, kind="dashboard-url"
    )
    dashboard_link = f"{effective_dashboard_url}/customers/{tenant}"
    click.echo("")
    click.echo("Quickstart complete.")
    click.echo(f"  Demo file: {demo_file}")
    click.echo(f"  Dashboard: {dashboard_link}")
    if not no_open:
        _open_browser_or_print(
            dashboard_link,
            headless_hint="Open the URL above to see your demo records.",
        )
    sys.exit(0)


# ---------------------------------------------------------------------------
# vera doctor — Stream E3.
# ---------------------------------------------------------------------------

_DOCTOR_STATUS_PASS = "PASS"
_DOCTOR_STATUS_FAIL = "FAIL"
_DOCTOR_STATUS_WARN = "WARN"
_DOCTOR_STATUS_INFO = "INFO"


def _doctor_check_config() -> dict[str, Any]:
    """Check 1: VERA_API_KEY shape, VERA_API_URL, VERA_TENANT_ID."""
    api_key = os.environ.get("VERA_API_KEY", "").strip()
    api_url = (
        os.environ.get("VERA_API_URL", "").strip() or _DEFAULT_API_URL
    )
    tenant_id = os.environ.get("VERA_TENANT_ID", "").strip()

    if not api_key:
        return {
            "name": "config",
            "status": _DOCTOR_STATUS_FAIL,
            "message": "VERA_API_KEY is not set",
            "details": {
                "api_url": api_url,
                "tenant_id": tenant_id or "(unset)",
            },
        }
    if not _validate_api_key_shape(api_key):
        return {
            "name": "config",
            "status": _DOCTOR_STATUS_FAIL,
            "message": (
                "VERA_API_KEY doesn't match expected shape "
                "(`al_test_...` or `al_live_...`)"
            ),
            "details": {
                "api_key": _mask_api_key(api_key),
                "api_url": api_url,
                "tenant_id": tenant_id or "(unset)",
            },
        }
    key_kind = "live" if api_key.startswith("al_live_") else "test"
    return {
        "name": "config",
        "status": _DOCTOR_STATUS_PASS,
        "message": f"API key present ({key_kind}), API URL configured",
        "details": {
            "api_key": _mask_api_key(api_key),
            "api_key_kind": key_kind,
            "api_url": api_url,
            "tenant_id": tenant_id or "(unset — using per-call tenant or default)",
        },
    }


def _doctor_check_connectivity() -> dict[str, Any]:
    """Check 2: GET /health on the configured API URL."""
    import httpx

    api_url = (
        os.environ.get("VERA_API_URL", "").strip() or _DEFAULT_API_URL
    ).rstrip("/")
    url = f"{api_url}/health"
    start = time.perf_counter()
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(url)
        elapsed_ms = (time.perf_counter() - start) * 1000
        if 200 <= resp.status_code < 300:
            return {
                "name": "connectivity",
                "status": _DOCTOR_STATUS_PASS,
                "message": f"{resp.status_code} from {url} ({elapsed_ms:.0f}ms)",
                "details": {"url": url, "status_code": resp.status_code, "latency_ms": round(elapsed_ms, 1)},
            }
        return {
            "name": "connectivity",
            "status": _DOCTOR_STATUS_FAIL,
            "message": f"{resp.status_code} from {url}",
            "details": {"url": url, "status_code": resp.status_code},
        }
    except httpx.TimeoutException as exc:
        return {
            "name": "connectivity",
            "status": _DOCTOR_STATUS_FAIL,
            "message": f"timeout connecting to {url}: {exc}",
            "details": {"url": url},
        }
    except httpx.HTTPError as exc:
        return {
            "name": "connectivity",
            "status": _DOCTOR_STATUS_FAIL,
            "message": f"network error connecting to {url}: {exc}",
            "details": {"url": url},
        }


def _doctor_check_auth() -> dict[str, Any]:
    """Check 3: GET /v1/organizations/me with the API key."""
    import httpx

    api_key = os.environ.get("VERA_API_KEY", "").strip()
    api_url = (
        os.environ.get("VERA_API_URL", "").strip() or _DEFAULT_API_URL
    ).rstrip("/")
    if not api_key:
        return {
            "name": "auth",
            "status": _DOCTOR_STATUS_FAIL,
            "message": "no API key — skipping auth check",
            "details": {},
        }
    url = f"{api_url}/v1/organizations/me"
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(
                url, headers={"Authorization": f"Bearer {api_key}"}
            )
        if resp.status_code == 200:
            try:
                body = resp.json()
            except Exception:
                body = {}
            org_id = body.get("id") or body.get("org_id") or "(unknown)"
            org_id_masked = (
                f"{org_id[:4]}…{org_id[-4:]}"
                if isinstance(org_id, str) and len(org_id) > 10
                else org_id
            )
            return {
                "name": "auth",
                "status": _DOCTOR_STATUS_PASS,
                "message": f"authenticated as org {org_id_masked}",
                "details": {"org_id": org_id_masked, "url": url},
            }
        if resp.status_code in (401, 403):
            # Try to surface a branded error code (PR #201's envelope).
            err_code = ""
            try:
                err_code = (resp.json().get("error") or {}).get("code", "")
            except Exception:
                err_code = ""
            hint = ""
            if err_code in {"baa_required", "baa_expired"}:
                hint = " (BAA gate blocked this live key — see dashboard)"
            elif err_code:
                hint = f" (code: {err_code})"
            return {
                "name": "auth",
                "status": _DOCTOR_STATUS_FAIL,
                "message": (
                    f"{resp.status_code} from {url}: "
                    f"API key rejected{hint}"
                ),
                "details": {"status_code": resp.status_code, "error_code": err_code},
            }
        return {
            "name": "auth",
            "status": _DOCTOR_STATUS_FAIL,
            "message": f"{resp.status_code} from {url}",
            "details": {"status_code": resp.status_code, "url": url},
        }
    except httpx.HTTPError as exc:
        return {
            "name": "auth",
            "status": _DOCTOR_STATUS_FAIL,
            "message": f"network error during auth check: {exc}",
            "details": {"url": url},
        }


def _doctor_check_tenant() -> dict[str, Any]:
    """Check 4: tenant resolver returns a value (INFO if None)."""
    from . import _context

    # Read env var; the resolver doesn't consult env directly, so we
    # register the env-derived tenant as the process default for this
    # check. We restore the previous default afterwards so the doctor
    # call is side-effect-free for callers that imported vera first.
    env_tenant = os.environ.get("VERA_TENANT_ID", "").strip()
    previous_default = _context.get_default_tenant()
    try:
        if env_tenant:
            try:
                _context.set_default_tenant(env_tenant)
            except Exception as exc:
                return {
                    "name": "tenant",
                    "status": _DOCTOR_STATUS_FAIL,
                    "message": f"VERA_TENANT_ID rejected by resolver: {exc}",
                    "details": {"tenant_id": env_tenant},
                }
        try:
            tenant_id, source = _context.resolve_tenant()
            return {
                "name": "tenant",
                "status": _DOCTOR_STATUS_PASS,
                "message": f"resolved to {tenant_id!r} (source={source})",
                "details": {"tenant_id": tenant_id, "source": source},
            }
        except Exception:
            return {
                "name": "tenant",
                "status": _DOCTOR_STATUS_INFO,
                "message": (
                    "no tenant configured — set VERA_TENANT_ID, "
                    "vera.init(default_tenant=...), or use vera.tenant()"
                ),
                "details": {},
            }
    finally:
        _context.set_default_tenant(previous_default)


def _doctor_check_spool() -> dict[str, Any]:
    """Check 5: spool path writable + sentinel readable (if used)."""
    spool_path = os.environ.get("VERA_SPOOL_PATH", "").strip()
    if not spool_path:
        return {
            "name": "spool",
            "status": _DOCTOR_STATUS_INFO,
            "message": "spool not configured (VERA_SPOOL_PATH unset)",
            "details": {},
        }
    parent = Path(spool_path).parent
    if not parent.exists():
        # Try to create — failure means we can't even initialize the spool.
        try:
            parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        except OSError as exc:
            return {
                "name": "spool",
                "status": _DOCTOR_STATUS_FAIL,
                "message": f"cannot create spool parent {parent}: {exc}",
                "details": {"path": spool_path},
            }
    if not os.access(parent, os.W_OK):
        return {
            "name": "spool",
            "status": _DOCTOR_STATUS_FAIL,
            "message": f"spool parent {parent} is not writable",
            "details": {"path": spool_path},
        }
    if Path(spool_path).exists() and not os.access(spool_path, os.R_OK):
        return {
            "name": "spool",
            "status": _DOCTOR_STATUS_FAIL,
            "message": f"spool file {spool_path} is not readable",
            "details": {"path": spool_path},
        }
    return {
        "name": "spool",
        "status": _DOCTOR_STATUS_PASS,
        "message": f"spool path {spool_path} OK",
        "details": {"path": spool_path, "exists": Path(spool_path).exists()},
    }


def _doctor_check_sdk_version() -> dict[str, Any]:
    """Check 6: SDK version. WARN on 0.x, PASS on 1.0+."""
    try:
        from importlib.metadata import PackageNotFoundError, version as _pkg_version

        try:
            ver = _pkg_version("vera-sdk")
        except PackageNotFoundError:
            return {
                "name": "sdk_version",
                "status": _DOCTOR_STATUS_WARN,
                "message": "vera-sdk not installed via pip (dev install?)",
                "details": {"version": "unknown"},
            }
    except Exception:
        return {
            "name": "sdk_version",
            "status": _DOCTOR_STATUS_WARN,
            "message": "could not read SDK version",
            "details": {"version": "unknown"},
        }
    major = ver.split(".")[0]
    try:
        major_int = int(major)
    except ValueError:
        major_int = 0
    if major_int >= 1:
        return {
            "name": "sdk_version",
            "status": _DOCTOR_STATUS_PASS,
            "message": f"vera-sdk {ver}",
            "details": {"version": ver},
        }
    return {
        "name": "sdk_version",
        "status": _DOCTOR_STATUS_WARN,
        "message": (
            f"vera-sdk {ver} is pre-1.0 — upgrade with "
            "`pip install --upgrade vera-sdk`"
        ),
        "details": {"version": ver},
    }


def _doctor_check_codemod() -> dict[str, Any]:
    """Check 7: libcst available for codemod feature."""
    try:
        import libcst  # noqa: F401

        return {
            "name": "codemod",
            "status": _DOCTOR_STATUS_PASS,
            "message": "libcst available (codemod feature ready)",
            "details": {},
        }
    except ImportError:
        return {
            "name": "codemod",
            "status": _DOCTOR_STATUS_INFO,
            "message": (
                "libcst not installed — run "
                "`pip install 'vera-sdk[codemod]'` to enable `vera codemod`"
            ),
            "details": {},
        }


_DOCTOR_CHECKS = (
    _doctor_check_config,
    _doctor_check_connectivity,
    _doctor_check_auth,
    _doctor_check_tenant,
    _doctor_check_spool,
    _doctor_check_sdk_version,
    _doctor_check_codemod,
)


_STATUS_SYMBOLS = {
    _DOCTOR_STATUS_PASS: "[PASS]",
    _DOCTOR_STATUS_FAIL: "[FAIL]",
    _DOCTOR_STATUS_WARN: "[WARN]",
    _DOCTOR_STATUS_INFO: "[INFO]",
}


@cli.command(name="doctor")
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Emit structured JSON for CI consumption.",
)
def doctor_cmd(as_json: bool) -> None:
    """Run diagnostic checks against your Vera configuration.

    Independent checks for config, connectivity, auth, tenant resolver,
    spool path, SDK version, and codemod availability. Exits 0 if no
    check failed; 1 if any check FAILed (WARN/INFO don't fail the run).

    Scope: SDK-side checks only. Middleware-wiring detection and
    customer-webhook URL probes require runtime context the CLI doesn't
    have — deferred to a future doctor expansion.
    """
    results: list[dict[str, Any]] = []
    for check in _DOCTOR_CHECKS:
        try:
            results.append(check())
        except Exception as exc:  # noqa: BLE001 — never crash the doctor
            results.append(
                {
                    "name": getattr(check, "__name__", "unknown").replace(
                        "_doctor_check_", ""
                    ),
                    "status": _DOCTOR_STATUS_FAIL,
                    "message": f"check raised unexpectedly: {exc}",
                    "details": {},
                }
            )

    summary = {"pass": 0, "fail": 0, "warn": 0, "info": 0}
    for r in results:
        key = r["status"].lower()
        if key in summary:
            summary[key] += 1

    if as_json:
        click.echo(_json.dumps({"checks": results, "summary": summary}))
    else:
        # Compute name column width once so the table aligns.
        name_w = max(len(r["name"]) for r in results)
        for r in results:
            sym = _STATUS_SYMBOLS.get(r["status"], r["status"])
            click.echo(f"  {sym} {r['name'].ljust(name_w)}  {r['message']}")
        click.echo("")
        click.echo(
            f"summary: {summary['pass']} pass, {summary['fail']} fail, "
            f"{summary['warn']} warn, {summary['info']} info"
        )

    sys.exit(1 if summary["fail"] > 0 else 0)


# ---------------------------------------------------------------------------
# vera review-status — Stream E4 (Phase 2 stub).
# ---------------------------------------------------------------------------


@cli.command(name="review-status")
@click.argument("review_id", type=str)
def review_status_cmd(review_id: str) -> None:
    """Look up the status of a pending review (Phase 2 feature).

    Placeholder for Phase 2: the gate-evaluation backend will expose
    ``GET /v1/reviews/<review_id>`` once HITL routing ships. The CLI
    surface exists today so callers can wire it into scripts; the body
    is filled in alongside the backend without changing the CLI shape.
    """
    click.echo(f"vera review-status {review_id}")
    click.echo(
        "  → Phase 2 feature — review-status lookup ships with the "
        "gate-evaluation backend."
    )
    click.echo(
        "    For Phase 1, pending reviews appear in the dashboard at "
        "/compliance/reviews (when populated)."
    )
    sys.exit(0)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
