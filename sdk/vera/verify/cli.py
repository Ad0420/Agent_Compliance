"""``vera verify`` Click wiring.

Two modes:

* ``vera verify`` (no ``--offline``) — preserves the existing
  ``ping``-like online check: hits ``/v1/verify`` to confirm the chain
  is reachable. Backwards-compat for any user who was running
  ``vera verify`` before this wave.
* ``vera verify --offline <bundle_path>`` — Wave 3C.1 offline pipeline.
  Reads the bundle from disk, prints a structured summary, exits 0 on
  full verification, 1 on any failed record / checkpoint signature,
  2 on a structural ``BundleError`` (broken bundle).

The actual verification logic lives in
:mod:`vera.verify.offline` — this module is just argparse plumbing +
output formatting.

Exit codes (deliberately distinct so CI scripts can branch):

* 0 — all records verified.
* 1 — at least one record / checkpoint failed.
* 2 — bundle is structurally broken (couldn't read manifest, missing
  records/ directory, malformed JSON).
* 3 — unexpected error (caught at the top level).
"""

from __future__ import annotations

import sys
import time

import click

from ..client import VeraClient
from ..errors import (
    VeraAuthError,
    VeraError,
    VeraNetworkError,
    VeraServerError,
    VeraTimeoutError,
)
from .offline import (
    BundleError,
    RecordVerification,
    VerifyResult,
    run_offline_verify,
)


EXIT_OK = 0
EXIT_VERIFICATION_FAILED = 1
EXIT_BUNDLE_ERROR = 2
EXIT_UNEXPECTED = 3


# ── Output formatting ────────────────────────────────────────────────


def _format_record_row(r: RecordVerification) -> str:
    status_marker = {
        "verified": "OK   ",
        "unverified": "WARN ",
        "failed": "FAIL ",
    }.get(r.status, "?    ")
    cp = (r.checkpoint_id or "-")[:12]
    rid = (r.action_record_id or "-")[:36]
    reason = r.reasons[0] if r.reasons else ""
    return f"  {status_marker} {rid:<36}  cp={cp:<12}  {reason}"


def _print_summary(result: VerifyResult) -> None:
    """Print a human-readable summary to stdout.

    Format intentionally non-fancy: no colour codes (the brief calls
    this out for an OCR investigator's terminal — colour codes look
    like garbage in copy-pasted regulator emails).
    """
    click.echo("")
    click.echo("Vera offline verify")
    click.echo(f"  bundle vera_version : {result.manifest.vera_version}")
    click.echo(f"  bundle exported_at  : {result.manifest.exported_at}")
    click.echo(
        f"  checkpoints in bundle: {len(result.checkpoints)} "
        f"(manifest claims {result.manifest.checkpoint_count})"
    )
    click.echo(
        f"  records in bundle    : {len(result.records)} "
        f"(manifest claims {result.manifest.record_count})"
    )

    if result.bundle_issues:
        click.echo("")
        click.echo("Bundle issues:")
        for issue in result.bundle_issues:
            click.echo(f"  - {issue}")

    click.echo("")
    click.echo("Checkpoints:")
    for c in result.checkpoints:
        sig_marker = "OK  " if c.signature_ok else "FAIL"
        chain_marker = (
            "OK  "
            if c.chain_link_ok is True
            else ("-" if c.chain_link_ok is None else "FAIL")
        )
        click.echo(
            f"  {sig_marker} signature  "
            f"{chain_marker} chain     "
            f"{(c.checkpoint_id or '')[:36]}"
            + (f"  ({c.signature_reason})" if not c.signature_ok else "")
        )

    click.echo("")
    click.echo("Records:")
    if not result.records:
        click.echo("  (none)")
    for r in result.records:
        click.echo(_format_record_row(r))

    click.echo("")
    verified = sum(1 for r in result.records if r.status == "verified")
    unverified = sum(1 for r in result.records if r.status == "unverified")
    failed = sum(1 for r in result.records if r.status == "failed")
    click.echo(
        f"Totals: verified={verified}  unverified={unverified}  failed={failed}"
    )

    if result.ok:
        click.echo("Result: OK — bundle verified.")
    else:
        click.echo("Result: FAIL — bundle did NOT verify.")


# ── Online verify path (backwards-compat) ────────────────────────────


def _run_online_verify(timeout: float) -> int:
    """``vera verify`` (no ``--offline``): online chain-reachability check.

    Mirrors the existing ``vera ping`` behaviour so users who scripted
    ``vera verify`` before this wave keep working. Internally hits
    ``GET /v1/verify`` via :meth:`VeraClient.verify_chain`.
    """
    try:
        client = VeraClient(timeout=timeout)
        start = time.perf_counter()
        result = client.verify_chain()
        elapsed_ms = (time.perf_counter() - start) * 1000
        click.echo(
            f"OK Chain reachable at {client.api_url} in {elapsed_ms:.1f}ms"
        )
        if isinstance(result, dict):
            if "status" in result:
                click.echo(f"  status: {result['status']}")
            if "chain_length" in result:
                click.echo(f"  chain_length: {result['chain_length']}")
        try:
            client.close()
        except Exception:
            pass
        return EXIT_OK
    except VeraAuthError as e:
        click.echo(f"FAIL Authentication failed: {e}", err=True)
        return EXIT_VERIFICATION_FAILED
    except VeraTimeoutError as e:
        click.echo(f"FAIL Timeout: {e}", err=True)
        return EXIT_VERIFICATION_FAILED
    except VeraNetworkError as e:
        click.echo(f"FAIL Network error: {e}", err=True)
        return EXIT_VERIFICATION_FAILED
    except VeraServerError as e:
        click.echo(f"FAIL Server error: {e}", err=True)
        return EXIT_VERIFICATION_FAILED
    except VeraError as e:
        click.echo(f"FAIL Vera error: {e}", err=True)
        return EXIT_VERIFICATION_FAILED


# ── Click command ────────────────────────────────────────────────────


@click.command(name="verify")
@click.option(
    "--offline",
    "offline_bundle",
    type=click.Path(exists=False, dir_okay=True, file_okay=True, resolve_path=True),
    default=None,
    help=(
        "Path to an evidence bundle (directory or tarball) to verify "
        "offline. NO network calls are made — only the bundle on disk "
        "is read. Required for true offline operation."
    ),
)
@click.option(
    "--timeout",
    type=float,
    default=5.0,
    help="Request timeout in seconds (online mode only).",
)
def verify_cmd(offline_bundle: str | None, timeout: float) -> None:
    """Verify Vera's evidence chain.

    Without flags: online chain-reachability check (legacy behaviour).
    With ``--offline <bundle>``: verifies a previously-exported
    evidence bundle on disk. The offline path makes NO network calls
    and works with Vera's API firewalled — the Phase 3 acceptance
    gate.
    """
    if offline_bundle is None:
        sys.exit(_run_online_verify(timeout))

    try:
        result = run_offline_verify(offline_bundle)
    except BundleError as exc:
        click.echo(f"FAIL Bundle error: {exc}", err=True)
        sys.exit(EXIT_BUNDLE_ERROR)
    except Exception as exc:  # noqa: BLE001 — top-level CLI catch-all
        click.echo(f"FAIL Unexpected error: {exc}", err=True)
        sys.exit(EXIT_UNEXPECTED)

    _print_summary(result)
    sys.exit(EXIT_OK if result.ok else EXIT_VERIFICATION_FAILED)


def register_verify_commands(cli_group: click.Group) -> None:
    """Attach the ``verify`` command to ``cli_group``.

    Called from :mod:`vera.cli` after the top-level ``cli`` group is
    created. Lives here so the command + helpers stay in the verify
    subpackage; ``vera.cli`` stays focused on the legacy commands.
    """
    cli_group.add_command(verify_cmd)
