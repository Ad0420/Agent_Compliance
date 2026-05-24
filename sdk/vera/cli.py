"""Vera SDK command-line interface.

Subcommands for setup, ops, and dev verification:

* ``vera init`` — scaffold an ``.env`` and walk a developer through API-key
  creation (Phase 1 PR 11 / Stream E1).
* ``vera quickstart`` — generate a demo file, run it, open the dashboard
  (Phase 1 PR 11 / Stream E2).
* ``vera doctor`` — diagnostic checks against config, network, auth,
  tenant resolver, spool, and SDK version (Phase 1 PR 11 / Stream E3).
* ``vera review-status <review_id>`` — fetch a single approval with
  optional ``--watch`` polling and ``--json`` machine output
  (Wave 2B PR B3 / Phase 1 PR 11 / E4).
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

from . import _cli_format as _fmt
from .client import VeraClient
from .errors import (
    VeraAuthError,
    VeraError,
    VeraNetworkError,
    VeraRateLimitError,
    VeraServerError,
    VeraTimeoutError,
    VeraValidationError,
    WrongKeyTier,
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


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a ``KEY=value`` ``.env``-style file into a dict.

    Lightweight handling of common dotenv conventions — the SDK doesn't
    ship a ``python-dotenv`` dependency for this one helper:

    * Skip blank lines and lines starting with ``#``.
    * Strip wrapping single or double quotes from values
      (``KEY="value"`` → ``value``).
    * Strip inline ``# comment`` only when the ``#`` is preceded by
      whitespace, so legitimate ``#`` inside a value (rare, but possible
      e.g. for a quoted password) isn't truncated.
    * Lines without ``=`` are ignored (matching standard dotenv behavior).
    * Missing file returns an empty dict — callers test the file's
      existence separately when that distinction matters.
    """
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip inline comments only when preceded by whitespace, to avoid
        # truncating ``KEY=val#ue`` (no space before ``#``).
        m = re.search(r"\s+#", value)
        if m:
            value = value[: m.start()].rstrip()
        # Strip matching wrapping quotes (single or double).
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            result[key] = value
    return result


def _existing_config_summary(env_file: Path) -> str | None:
    """Return a one-line summary of existing config, or ``None`` if absent.

    Checks for a valid ``VERA_API_KEY`` in the ``.env`` file at
    ``env_file`` first, then in the process env. Returns ``None`` when
    neither is configured (i.e. ``vera init`` should proceed without
    prompting). An ``.env`` that exists but doesn't contain a non-empty
    ``VERA_API_KEY`` returns ``None`` — clobbering an empty/stub file
    is not actually destructive.
    """
    if env_file.exists():
        parsed = _parse_env_file(env_file)
        if parsed.get("VERA_API_KEY", "").strip():
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
    help=(
        "Skip the browser flow and use this API key directly. WARNING: "
        "the key is visible in `ps`/`ps aux` and gets recorded in shell "
        "history (`.bash_history`/`.zsh_history`) and CI logs. Prefer "
        "`VERA_API_KEY=... vera init` or `--key -` to read from stdin."
    ),
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
        if key_flag == "-":
            # ``--key -`` reads the key from stdin so it doesn't leak into
            # ps / shell history / CI logs. Use ``readline`` rather than
            # ``read`` so trailing input (e.g. an interactive shell
            # appending a newline) doesn't get folded into the key.
            raw = sys.stdin.readline()
            if not raw:
                raise click.ClickException(
                    "--key - was passed but stdin was empty"
                )
            api_key = raw.strip()
        else:
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


# Backoff schedule for ``_wait_for_tenant_ingest`` — exponential to ~10s
# so a slow backend doesn't kill the quickstart flow but a fast one only
# pays ~250ms.
_INGEST_POLL_DELAYS = (0.25, 0.5, 1.0, 2.0, 5.0)
_INGEST_POLL_HINT_AFTER = 2.0


def _wait_for_tenant_ingest(
    *,
    api_url: str,
    api_key: str,
    tenant: str,
) -> bool:
    """Poll ``GET /v1/customers/{tenant}`` until it returns 200 or budget runs out.

    Returns ``True`` on success, ``False`` if we gave up. The quickstart
    flow proceeds either way — a missed poll just means the operator
    will see an empty page until the backend catches up. We print a
    user-visible hint after ``_INGEST_POLL_HINT_AFTER`` seconds so
    operators on slow networks understand the wait.
    """
    import httpx

    url = f"{api_url}/v1/customers/{tenant}"
    headers = {"Authorization": f"Bearer {api_key}"}
    elapsed = 0.0
    hint_printed = False
    for delay in _INGEST_POLL_DELAYS:
        try:
            with httpx.Client(timeout=3.0) as client:
                resp = client.get(url, headers=headers)
            if resp.status_code == 200:
                return True
        except httpx.HTTPError:
            # Transient — keep polling.
            pass
        if not hint_printed and elapsed >= _INGEST_POLL_HINT_AFTER:
            click.echo("  Waiting for backend to ingest demo decisions...")
            hint_printed = True
        time.sleep(delay)
        elapsed += delay
    click.echo(
        "  warning: backend hasn't reported the tenant yet — "
        "the dashboard may show an empty page momentarily.",
        err=True,
    )
    return False


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
    if not api_key:
        api_key = _parse_env_file(Path(".env")).get("VERA_API_KEY", "").strip()

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
        api_key = _parse_env_file(Path(".env")).get("VERA_API_KEY", "").strip()
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

    # 3a. Demo-file path sanitization. We're about to ``write_text`` here
    # and then ``subprocess.run`` it; restrict the path to under CWD,
    # ``$HOME``, or the system temp dir so a typo like
    # ``--demo-file /etc/passwd`` errors with a clear message instead of
    # leaking a raw OSError. The OS would block the write anyway, but a
    # clean error is friendlier. ``$TMPDIR`` is allowed because CI and
    # pytest's ``tmp_path`` fixture frequently use it.
    import tempfile

    resolved_demo = demo_file.resolve()
    cwd = Path.cwd().resolve()
    home = Path.home().resolve()
    tmp_root = Path(tempfile.gettempdir()).resolve()
    if not (
        resolved_demo.is_relative_to(cwd)
        or resolved_demo.is_relative_to(home)
        or resolved_demo.is_relative_to(tmp_root)
    ):
        raise click.ClickException(
            f"--demo-file {demo_file} resolves to {resolved_demo}, "
            "which is outside the current directory, $HOME, and "
            "the system temp dir. Pass a path under one of those "
            "for safety."
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
        # Poll the backend until it's ingested the tenant, rather than a
        # brittle hardcoded sleep. Total budget ~10s with exponential
        # backoff; print a hint at ~2s so the operator knows we're
        # waiting on the backend (network may just be slow). If polling
        # never succeeds we still open the dashboard — the user can
        # refresh manually rather than us erroring out on a flaky link.
        api_url = (
            os.environ.get("VERA_API_URL", "").strip() or _DEFAULT_API_URL
        ).rstrip("/")
        _wait_for_tenant_ingest(
            api_url=api_url, api_key=api_key, tenant=tenant,
        )

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
            # Try to surface a branded error code. PR #201's
            # ``_flatten_dict_detail`` exception handler lifts dict-typed
            # ``HTTPException.detail`` to the TOP LEVEL of the response —
            # the wire shape is ``{"code": "baa_required", "fix_url": ...,
            # "detail": ...}``, NOT ``{"error": {"code": ...}}``. Read
            # ``code`` from the top level to match the contract.
            err_code = ""
            try:
                body = resp.json()
                if isinstance(body, dict):
                    err_code = body.get("code", "") or ""
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
    """Check 4: tenant resolver returns a value (INFO if None).

    Catches only :class:`TenantMissingOrInvalid` with ``reason='missing'``
    as INFO ("no tenant configured"). Malformed / PHI-shape values, plus
    any unrelated exception (import error, AttributeError) bubble up to
    the outer doctor handler at :func:`doctor_cmd` and classify as FAIL —
    a programming error masquerading as INFO would silently mask real
    breakage.
    """
    from . import _context
    from .errors import TENANT_REASON_MISSING, TenantMissingOrInvalid

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
            except TenantMissingOrInvalid as exc:
                return {
                    "name": "tenant",
                    "status": _DOCTOR_STATUS_FAIL,
                    "message": f"VERA_TENANT_ID rejected by resolver: {exc}",
                    "details": {
                        "tenant_id": env_tenant,
                        "reason": getattr(exc, "reason", None),
                    },
                }
        try:
            tenant_id, source = _context.resolve_tenant()
            return {
                "name": "tenant",
                "status": _DOCTOR_STATUS_PASS,
                "message": f"resolved to {tenant_id!r} (source={source})",
                "details": {"tenant_id": tenant_id, "source": source},
            }
        except TenantMissingOrInvalid as exc:
            if getattr(exc, "reason", None) == TENANT_REASON_MISSING:
                return {
                    "name": "tenant",
                    "status": _DOCTOR_STATUS_INFO,
                    "message": (
                        "no tenant configured — set VERA_TENANT_ID, "
                        "vera.init(default_tenant=...), or use vera.tenant()"
                    ),
                    "details": {},
                }
            # Malformed or PHI-shape is a real failure, not an INFO.
            return {
                "name": "tenant",
                "status": _DOCTOR_STATUS_FAIL,
                "message": f"tenant resolver rejected stored tenant: {exc}",
                "details": {"reason": getattr(exc, "reason", None)},
            }
        # Any other exception (programming error in the resolver, missing
        # import, AttributeError, ...) is deliberately NOT caught here —
        # the outer doctor handler classifies it as FAIL, which is the
        # honest answer.
    finally:
        _context.set_default_tenant(previous_default)


def _doctor_check_spool() -> dict[str, Any]:
    """Check 5: spool path writable + passphrase sentinel validates.

    If ``VERA_SPOOL_PATH`` is unset, returns INFO (spool is opt-in).
    Otherwise:

    1. Verify the parent dir exists / is writable. Fail fast if not.
    2. If ``VERA_SPOOL_KEY`` is set, instantiate :class:`vera.spool.Spool`.
       The constructor exercises ``_init_passphrase_sentinel`` — either
       writes a fresh sentinel (new spool) or decrypts the stored one
       (existing spool). A mismatched passphrase or corrupt sentinel
       raises :class:`vera.spool.SpoolPassphraseError`, surfaced as FAIL.
    3. If ``VERA_SPOOL_KEY`` is NOT set, fall back to the original
       fs-perms-only check and WARN that the sentinel can't be verified
       without a passphrase (the spool would fail-closed at SDK boot
       anyway, but the doctor flags it now so the operator sees it).
    """
    spool_path = os.environ.get("VERA_SPOOL_PATH", "").strip()
    if not spool_path:
        return {
            "name": "spool",
            "status": _DOCTOR_STATUS_INFO,
            "message": "spool not configured (VERA_SPOOL_PATH unset)",
            "details": {},
        }
    parent = Path(spool_path).parent
    if parent and not parent.exists():
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
    if parent and not os.access(parent, os.W_OK):
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

    passphrase = os.environ.get("VERA_SPOOL_KEY", "")
    if not passphrase:
        return {
            "name": "spool",
            "status": _DOCTOR_STATUS_WARN,
            "message": (
                f"spool path {spool_path} writable, but VERA_SPOOL_KEY "
                "is unset — sentinel cannot be verified and the spool "
                "will refuse to start at SDK boot"
            ),
            "details": {
                "path": spool_path,
                "exists": Path(spool_path).exists(),
            },
        }

    # Exercise the passphrase sentinel by constructing the Spool. The
    # constructor writes a fresh sentinel on first open and decrypts the
    # stored one on subsequent opens — a typo / rotated key surfaces here
    # as ``SpoolPassphraseError`` instead of waiting for the first
    # production write to crash.
    try:
        from .spool import Spool, SpoolPassphraseError
    except ImportError as exc:
        return {
            "name": "spool",
            "status": _DOCTOR_STATUS_FAIL,
            "message": (
                f"cannot import vera.spool: {exc} — install "
                "`vera-sdk[spool]` (cryptography)"
            ),
            "details": {"path": spool_path},
        }

    spool: Any = None
    try:
        spool = Spool(spool_path, passphrase=passphrase)
        return {
            "name": "spool",
            "status": _DOCTOR_STATUS_PASS,
            "message": f"spool path {spool_path} OK (sentinel verified)",
            "details": {
                "path": spool_path,
                "exists": True,
                "sentinel": "verified",
            },
        }
    except SpoolPassphraseError as exc:
        return {
            "name": "spool",
            "status": _DOCTOR_STATUS_FAIL,
            "message": (
                f"spool passphrase sentinel mismatch: {exc} — check "
                "VERA_SPOOL_KEY hasn't been rotated"
            ),
            "details": {"path": spool_path},
        }
    except Exception as exc:  # noqa: BLE001 — surface as FAIL, not crash
        return {
            "name": "spool",
            "status": _DOCTOR_STATUS_FAIL,
            "message": f"could not open spool {spool_path}: {exc}",
            "details": {"path": spool_path},
        }
    finally:
        if spool is not None:
            try:
                spool.close()
            except Exception:
                pass


def _doctor_check_sdk_version() -> dict[str, Any]:
    """Check 6: SDK version. WARN on 0.x, PASS on 1.0+.

    Cross-checks pip metadata against ``vera.__version__`` when the
    runtime module exposes one. A disagreement usually means a local
    ``vera/`` directory is shadowing the installed wheel (or vice
    versa) — a real footgun that the pip-only check misses entirely.
    Today ``vera/__init__.py`` does not expose ``__version__``, so the
    cross-check just no-ops; the moment we add one, this check starts
    catching shadow installs.
    """
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

    # Cross-check: does the imported ``vera`` module agree with pip?
    # A mismatch means there's a stale `vera/` directory shadowing the
    # installed wheel (common when developers `pip install -e .` then
    # later `pip install vera-sdk`).
    runtime_version: str | None = None
    try:
        import vera as _vera_mod

        runtime_version = getattr(_vera_mod, "__version__", None)
    except Exception:
        runtime_version = None
    if runtime_version and runtime_version != ver:
        return {
            "name": "sdk_version",
            "status": _DOCTOR_STATUS_FAIL,
            "message": (
                f"version mismatch: pip says {ver}, imported `vera` "
                f"module says {runtime_version}. A stale `vera/` "
                "directory is probably shadowing the installed wheel."
            ),
            "details": {
                "pip_version": ver,
                "runtime_version": runtime_version,
            },
        }

    # PEP-440 epoch versions (e.g. ``1!0.0``) would misclassify here
    # since ``"1!0".split(".")[0] == "1!0"``. Not worth pulling in the
    # ``packaging`` dep for an edge case we never plan to use — the
    # bare ``.split`` is fine for foreseeable versions.
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
        else:
            # Surface check-implementation bugs (typo in a new status
            # constant) rather than silently dropping the count.
            click.echo(
                f"warning: unknown doctor status: {r['status']!r} "
                f"(check={r.get('name', 'unknown')!r})",
                err=True,
            )

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
# vera review-status — Wave 2B PR B3.
# ---------------------------------------------------------------------------

# Exit codes for ``vera review-status``. Kept as a module-level constant
# so tests can reference them by name and shell pipelines have a stable
# contract documented in the README/help text.
#
#   0  — fetched (single-shot) or reached terminal state (watch)
#   1  — review not found (404)
#   2  — auth / wrong-tier / network / rate-limit / server / unexpected
#   3  — watch timeout (--timeout reached without terminal state)
#   130 — user pressed Ctrl-C (POSIX SIGINT convention)
REVIEW_STATUS_EXIT_OK = 0
REVIEW_STATUS_EXIT_NOT_FOUND = 1
REVIEW_STATUS_EXIT_TRANSPORT = 2
REVIEW_STATUS_EXIT_WATCH_TIMEOUT = 3
REVIEW_STATUS_EXIT_INTERRUPTED = 130


def _is_404(exc: Exception) -> bool:
    """Detect a 404 surfaced via the httpx wrapper's VeraValidationError.

    The wrapper currently maps any 4xx-other-than-{401,403,429} to
    :class:`VeraValidationError` with ``status_code`` carrying the HTTP
    code. Introducing a dedicated ``VeraNotFoundError`` belongs in a
    future error-discipline PR — for now we sniff the attribute.
    """
    return (
        isinstance(exc, VeraValidationError)
        and getattr(exc, "status_code", None) == 404
    )


def _fetch_with_one_retry(
    client: VeraClient, review_id: str, *, sleep=time.sleep
) -> dict:
    """Call ``client.get_approval`` with a single 1s retry on transient errors.

    Auth / validation / wrong-tier / rate-limit errors are NOT retried —
    they won't self-heal in 1 second. Only network/timeout/5xx, which
    can be a flaky DNS lookup or a brief upstream blip, get a retry.
    ``sleep`` is a parameter so tests can inject a fake.
    """
    try:
        return client.get_approval(review_id)
    except (VeraNetworkError, VeraTimeoutError, VeraServerError):
        sleep(1.0)
        return client.get_approval(review_id)


def _emit_review_status_error(exc: Exception) -> int:
    """Render an exception to stderr and return the matching exit code.

    Pure mapping function (apart from the stderr write) — keeps the
    error-handling block in the command body short and lets tests pin
    the message-vs-exit-code contract directly.
    """
    if _is_404(exc):
        click.echo(
            f"FAIL Review {getattr(exc, 'review_id', '')} not found. "
            "Check the ID or your tenant scope.".replace("  ", " "),
            err=True,
        )
        return REVIEW_STATUS_EXIT_NOT_FOUND
    if isinstance(exc, WrongKeyTier):
        # WrongKeyTier carries .key_kind / .required / .endpoint.
        click.echo(
            f"FAIL API key tier mismatch: your '{exc.key_kind}' key cannot "
            f"call '{exc.endpoint}' (requires '{exc.required}').",
            err=True,
        )
        click.echo(
            "  Rotate to the correct tier in the dashboard: "
            "https://app.usevera.xyz/settings/api-keys",
            err=True,
        )
        return REVIEW_STATUS_EXIT_TRANSPORT
    if isinstance(exc, VeraAuthError):
        sc = getattr(exc, "status_code", None)
        if sc == 403:
            click.echo(
                f"FAIL API key lacks 'read' permission for approvals: {exc}",
                err=True,
            )
            click.echo(
                "  Generate a read-capable key in the dashboard: "
                "https://app.usevera.xyz/settings/api-keys",
                err=True,
            )
        else:
            click.echo(f"FAIL Authentication failed: {exc}", err=True)
            click.echo(
                "  Run `vera config show` to inspect the current key, or "
                "`vera ping` to verify connectivity.",
                err=True,
            )
        return REVIEW_STATUS_EXIT_TRANSPORT
    if isinstance(exc, VeraRateLimitError):
        rid = getattr(exc, "request_id", "") or ""
        click.echo(
            f"FAIL Rate limited{(' (' + rid + ')') if rid else ''}: "
            f"{exc}. Retry shortly.",
            err=True,
        )
        return REVIEW_STATUS_EXIT_TRANSPORT
    if isinstance(exc, VeraServerError):
        click.echo(
            f"FAIL Vera service error: {exc}. "
            "Status: https://status.usevera.xyz",
            err=True,
        )
        return REVIEW_STATUS_EXIT_TRANSPORT
    if isinstance(exc, (VeraNetworkError, VeraTimeoutError)):
        click.echo(
            f"FAIL {type(exc).__name__}: {exc}. (Retried once.)", err=True
        )
        return REVIEW_STATUS_EXIT_TRANSPORT
    if isinstance(exc, VeraValidationError):
        click.echo(f"FAIL {exc}", err=True)
        return REVIEW_STATUS_EXIT_TRANSPORT
    if isinstance(exc, VeraError):
        click.echo(f"FAIL {type(exc).__name__}: {exc}", err=True)
        return REVIEW_STATUS_EXIT_TRANSPORT
    # Catch-all — unexpected exception. We surface the type and message
    # so a maintainer can triage without a re-run.
    click.echo(f"FAIL Unexpected error: {type(exc).__name__}: {exc}", err=True)
    return REVIEW_STATUS_EXIT_TRANSPORT


@cli.command(name="review-status")
@click.argument("review_id", type=str)
@click.option(
    "--watch",
    "-w",
    is_flag=True,
    default=False,
    help="Re-poll until the approval reaches a terminal state.",
)
@click.option(
    "--interval",
    type=click.FloatRange(min=0.5, max=60.0, clamp=False),
    default=5.0,
    show_default=True,
    help=(
        "Poll interval in seconds (only with --watch). Minimum 0.5s to "
        "avoid hammering the API."
    ),
)
@click.option(
    "--timeout",
    type=click.FloatRange(min=1.0, max=86400.0, clamp=False),
    default=None,
    help=(
        "Give up after this many seconds (only with --watch). No timeout "
        "by default. Exits with code 3 when the deadline is reached "
        "without a terminal state."
    ),
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help=(
        "Emit raw ApprovalResponse JSON instead of human-formatted output. "
        "With --watch, emits NDJSON (one object per line per poll)."
    ),
)
@click.option(
    "--no-color",
    is_flag=True,
    default=False,
    envvar="NO_COLOR",
    help=(
        "Disable ANSI colors (auto-disabled when stdout is not a TTY or "
        "TERM=dumb)."
    ),
)
def review_status_cmd(
    review_id: str,
    watch: bool,
    interval: float,
    timeout: float | None,
    as_json: bool,
    no_color: bool,
) -> None:
    """Fetch the status of a single approval review.

    Examples:

    \b
        vera review-status app_01H7XKCRJF8
        vera review-status app_01H7XKCRJF8 --watch --interval 3
        vera review-status app_01H7XKCRJF8 --json | jq .status

    Exit codes:

    \b
        0   approval fetched (or reached terminal state under --watch)
        1   approval not found (404)
        2   auth, wrong-tier, network, rate-limit, or server failure
        3   --watch --timeout reached before terminal state
        130 user pressed Ctrl-C

    Times are always rendered in UTC. Relative phrases ("3m ago",
    "in 7m") are computed from your local clock.
    """
    # Cross-flag warnings — emit on stderr so JSON pipelines aren't
    # polluted. These don't fail the command; they just nudge.
    if (interval != 5.0) and not watch:
        click.echo(
            "WARN --interval has no effect without --watch", err=True
        )
    if (timeout is not None) and not watch:
        click.echo(
            "WARN --timeout has no effect without --watch", err=True
        )

    # Lightweight pre-flight: no API key → fail fast with a hint. The
    # constructor would just warn and continue; we want a clear error
    # before any network round-trip.
    if not os.environ.get("VERA_API_KEY", "").strip():
        click.echo("FAIL No VERA_API_KEY configured.", err=True)
        click.echo("", err=True)
        click.echo(
            "  Set it: export VERA_API_KEY=al_live_...", err=True
        )
        click.echo(
            "  Or run: vera config show     # to inspect current state",
            err=True,
        )
        click.echo(
            "  Or:     vera ping             # to verify connectivity",
            err=True,
        )
        click.echo("", err=True)
        click.echo(
            "  Generate a key at https://app.usevera.xyz/settings/api-keys",
            err=True,
        )
        sys.exit(REVIEW_STATUS_EXIT_TRANSPORT)

    color_enabled = _fmt.should_use_color(no_color)
    headless = not color_enabled  # color disabled === headless for layout

    try:
        client = VeraClient()
    except Exception as e:  # noqa: BLE001 — construct can raise various shapes
        sys.exit(_emit_review_status_error(e))

    start = time.monotonic()

    try:
        while True:
            try:
                approval = _fetch_with_one_retry(client, review_id)
            except Exception as exc:  # noqa: BLE001 — single sink
                # Attach the review_id so the 404 message can include it.
                try:
                    setattr(exc, "review_id", review_id)
                except Exception:
                    pass
                sys.exit(_emit_review_status_error(exc))

            status = approval.get("status")
            terminal = status in _fmt.TERMINAL_STATES
            elapsed = time.monotonic() - start

            if as_json:
                if watch:
                    click.echo(
                        _fmt.render_status_ndjson(approval), nl=False
                    )
                else:
                    click.echo(_fmt.render_status_json(approval), nl=False)
                # Force flush so downstream `jq -c` / `tee` sees each
                # poll immediately, not at process exit.
                try:
                    sys.stdout.flush()
                except Exception:
                    pass
            else:
                if watch and not headless:
                    # Clear screen + scrollback so each frame replaces
                    # the previous one cleanly.
                    click.echo(_fmt.TERMINAL_CLEAR, nl=False)
                elif watch and headless:
                    # Headless: print a divider so successive frames
                    # are visually separable in a log file.
                    click.echo(_fmt.HEADLESS_FRAME_DIVIDER, nl=False)
                footer = (
                    _fmt.render_watch_footer(interval, elapsed)
                    if watch
                    else None
                )
                click.echo(
                    _fmt.render_status_human(
                        approval,
                        color=color_enabled,
                        watch_footer=footer,
                    ),
                    nl=False,
                )

            if not watch or terminal:
                break

            if timeout is not None and elapsed >= timeout:
                click.echo(
                    f"FAIL Watch timeout: {review_id} did not resolve "
                    f"within {timeout:g}s "
                    f"(last status: {status or 'unknown'}).",
                    err=True,
                )
                sys.exit(REVIEW_STATUS_EXIT_WATCH_TIMEOUT)

            time.sleep(interval)
    except KeyboardInterrupt:
        click.echo("", err=True)
        click.echo("(interrupted)", err=True)
        sys.exit(REVIEW_STATUS_EXIT_INTERRUPTED)
    finally:
        try:
            client.close()
        except Exception:
            pass

    sys.exit(REVIEW_STATUS_EXIT_OK)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
