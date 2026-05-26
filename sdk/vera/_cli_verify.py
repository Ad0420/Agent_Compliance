"""``vera verify --merkle-proof`` + ``vera evidence-export`` CLI surface.

Lives in its own module to keep ``cli.py`` from growing unbounded and to
avoid clashing with Wave 3C.1's parallel refactor of the ``verify``
subpackage. The Click decorators register against the top-level ``cli``
group at import time (see :mod:`vera.cli`).

Exit-code contract (both commands share):

* ``0`` — operation succeeded.
* ``1`` — verification failed (tamper detected, signature invalid,
  bundle malformed) OR an expected non-recoverable runtime error
  (record/checkpoint not found).
* ``2`` — auth, network, or other transport-level failure.
"""

from __future__ import annotations

import datetime as _dt
import io
import json
import os
import re
import sys
import tarfile
import time
from pathlib import Path
from typing import Optional

import click
import httpx

from .verify.proof_payload import (
    REASON_MERKLE_PATH_MISMATCH,
    REASON_SIGNATURE_ALGORITHM_UNSUPPORTED,
    REASON_SIGNATURE_INVALID,
    verify_proof_payload,
)


# Default API URL — kept in sync with cli.py's _DEFAULT_API_URL via the
# env var lookup chain.
_DEFAULT_API_URL = "https://api.usevera.xyz"

# Bundle layout version. Bumped if the bundle shape changes in a way
# that a 3C.1 ``vera verify --offline`` consumer would notice. Wave
# 3C.1 reads this from manifest.json.
_BUNDLE_VERSION = "1"

# ISO-8601 calendar-date regex, used to validate --since / --until.
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# UUID regex (case-insensitive hex + dashes, exactly 36 chars). Every
# action_record_id and checkpoint_id minted by Vera is a uuid4 — see
# ``backend/app/models/action_record.py`` (``String(36)`` PK,
# ``default=lambda: str(uuid.uuid4())``). Server-supplied strings are
# matched against this regex before being joined into evidence-bundle
# file paths so a compromised/misbehaving server cannot drive a
# directory-traversal write outside ``bundle_root`` (e.g. by returning
# ``id="../etc/passwd"``).
_UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")


def _truncate_for_error(value: str, *, limit: int = 80) -> str:
    """Truncate ``value`` for inclusion in a user-facing error message.

    Caps length and escapes non-printable bytes via ``repr`` so a
    crafted server response can't smuggle ANSI control codes or
    newlines into operator log output (log-injection mitigation).
    """
    if value is None:
        return "<none>"
    s = str(value)
    if len(s) > limit:
        s = s[:limit] + "..."
    return repr(s)


def _require_safe_record_id(rid: str) -> None:
    """Reject any record id that doesn't match the UUID regex.

    Aborts the export with a ``click.ClickException`` carrying the
    truncated offending value so the operator can diagnose without the
    error itself becoming an attack surface.
    """
    if not isinstance(rid, str) or not _UUID_RE.match(rid):
        raise click.ClickException(
            "evidence-export aborted: server returned a record id that "
            "does not match the expected UUID format "
            f"(offending value={_truncate_for_error(rid)}). The bundle "
            "is suspect; refusing to write."
        )


def _require_safe_date(date_iso: str) -> None:
    """Reject any date string that doesn't match the ISO-8601 calendar
    date regex.

    Same threat model as :func:`_require_safe_record_id` — applied to
    the checkpoint filename component to harden a future refactor that
    might route a server-supplied date here.
    """
    if not isinstance(date_iso, str) or not _DATE_RE.match(date_iso):
        raise click.ClickException(
            "evidence-export aborted: a checkpoint date does not match "
            "the expected YYYY-MM-DD format "
            f"(offending value={_truncate_for_error(date_iso)}). The "
            "bundle is suspect; refusing to write."
        )


def _resolve_api_url() -> str:
    """``VERA_API_URL`` or the default, rstrip'd of trailing slash."""
    return (
        os.environ.get("VERA_API_URL", "").strip() or _DEFAULT_API_URL
    ).rstrip("/")


def _build_headers() -> dict[str, str]:
    """Build the auth + targeting headers for a CLI call.

    ``VERA_API_KEY`` is mandatory. ``VERA_TARGET_ORG_ID`` is opt-in and
    only meaningful for STAFF-tier callers (the server enforces this);
    we pass it through transparently so customer-tier keys aren't
    rejected for sending it.
    """
    api_key = os.environ.get("VERA_API_KEY", "").strip()
    if not api_key:
        raise click.ClickException(
            "No VERA_API_KEY configured. Set it in your environment "
            "before running this command."
        )
    headers = {"Authorization": f"Bearer {api_key}"}
    target_org = os.environ.get("VERA_TARGET_ORG_ID", "").strip()
    if target_org:
        headers["X-Org-Id"] = target_org
    return headers


def _format_signed_at(raw: str) -> str:
    """Render an ISO timestamp as ``YYYY-MM-DD HH:MM UTC`` for humans.

    Falls back to the raw string if parsing fails — we never want a
    cosmetic format error to take down the verifier.
    """
    try:
        dt = _dt.datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            return dt.strftime("%Y-%m-%d %H:%M UTC")
        return dt.astimezone(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return raw


def _short_hash(hex_str: str) -> str:
    """Truncate a hex digest for display (``0x4f3a...e2b1``)."""
    if not hex_str:
        return "(none)"
    if len(hex_str) < 12:
        return hex_str
    return f"0x{hex_str[:4]}...{hex_str[-4:]}"


# ── vera verify --merkle-proof ──────────────────────────────────────────


def verify_merkle_proof_for_record(
    record_id: str,
    *,
    api_url: Optional[str] = None,
    headers: Optional[dict[str, str]] = None,
    timeout: float = 30.0,
    hmac_secret: Optional[bytes] = None,
) -> tuple[int, str]:
    """Fetch the proof for ``record_id`` and verify it offline.

    Returns ``(exit_code, message)``. Centralised so tests can drive the
    verifier with a stubbed httpx transport (via Click's ``CliRunner``
    we already get isolated env vars; injecting a transport gives us
    pristine integration coverage of the wire-shape contract).

    Wave 3C.1 may absorb this into a unified ``verify`` flow when it
    rebases; the signature is kept narrow so the rebase is clean.
    """
    api_url = api_url or _resolve_api_url()
    headers = headers if headers is not None else _build_headers()
    url = f"{api_url}/v1/records/{record_id}/merkle-proof"

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url, headers=headers)
    except httpx.TimeoutException as exc:
        return 2, f"FAIL Timeout fetching proof: {exc}"
    except httpx.HTTPError as exc:
        return 2, f"FAIL Network error: {exc}"

    if resp.status_code == 401 or resp.status_code == 403:
        return 2, f"FAIL Authentication failed ({resp.status_code}): {resp.text}"
    if resp.status_code == 404:
        return 1, f"FAIL Record {record_id} not found (or not in your org)."
    if resp.status_code == 409:
        return 1, (
            f"FAIL Record {record_id} is in the tail window — no "
            "checkpoint has sealed it yet. Try again after the next "
            "checkpoint cadence tick."
        )
    if resp.status_code >= 400:
        return 2, f"FAIL Server returned {resp.status_code}: {resp.text}"

    try:
        payload = resp.json()
    except Exception as exc:
        return 2, f"FAIL Server returned non-JSON body: {exc}"

    result = verify_proof_payload(payload, hmac_secret=hmac_secret)
    if not result.ok:
        if result.reason == REASON_MERKLE_PATH_MISMATCH:
            reason_human = (
                "Merkle path verification failed — leaf, sibling, or "
                "root has been tampered with."
            )
        elif result.reason == REASON_SIGNATURE_INVALID:
            reason_human = "KMS signature did not validate."
        elif result.reason == REASON_SIGNATURE_ALGORITHM_UNSUPPORTED:
            reason_human = (
                "Signature algorithm not supported by this SDK build."
            )
        else:
            reason_human = result.reason
        return 1, (
            f"FAIL Record {record_id}: {reason_human} "
            f"(reason={result.reason})"
        )

    # Pretty-print the success summary.
    checkpoint_id = payload.get("checkpoint_id", "?")
    signed_at = _format_signed_at(payload.get("checkpoint_signed_at", ""))
    root = _short_hash(payload.get("merkle_root", ""))
    kms_key = payload.get("kms_key_id", "?") or "(unset — legacy)"
    kms_algo = payload.get("kms_algorithm", "?") or "(unset — legacy)"
    msg_lines = [
        f"OK Record {record_id} verified against checkpoint "
        f"{checkpoint_id} (signed {signed_at})",
        f"   Merkle root: {root}",
        f"   KMS key: {kms_key} ({kms_algo})",
    ]
    if result.signature_warning:
        msg_lines.append(
            "   WARNING unverified (no HMAC secret) — Merkle path "
            "validates but KMS signature is over an HMAC key whose "
            "shared secret was not supplied to this verifier."
        )
    return 0, "\n".join(msg_lines)


@click.command(name="verify")
@click.option(
    "--merkle-proof",
    "merkle_proof_record_id",
    type=str,
    default=None,
    help=(
        "Verify the Merkle inclusion proof for an action_record_id. "
        "Fetches GET /v1/records/{id}/merkle-proof, re-validates the "
        "proof locally, and prints the result. Exit 0 on success."
    ),
)
@click.option(
    "--offline",
    "offline_bundle",
    type=click.Path(exists=False, dir_okay=True, file_okay=True, resolve_path=True),
    default=None,
    help=(
        "Path to an evidence bundle (directory or tarball) to verify "
        "offline. NO network calls are made — only the bundle on disk "
        "is read. Required for the Phase 3 acceptance gate (Vera API "
        "firewalled). Routes through vera.verify.offline.run_offline_verify."
    ),
)
@click.option(
    "--timeout",
    type=float,
    default=30.0,
    show_default=True,
    help="Request timeout in seconds (online modes only).",
)
@click.option(
    "--hmac-secret-env",
    type=str,
    default=None,
    help=(
        "Env var to read an HMAC shared secret from (UTF-8). Only "
        "needed when the checkpoint was signed with HMAC and you want "
        "to verify the signature offline. Without this, HMAC-signed "
        "proofs print a 'unverified (no HMAC secret)' warning but "
        "still exit 0 if the Merkle path validates."
    ),
)
def verify_cmd(
    merkle_proof_record_id: Optional[str],
    offline_bundle: Optional[str],
    timeout: float,
    hmac_secret_env: Optional[str],
) -> None:
    """Verify Vera-issued evidence.

    Three supported modes (Wave 3C.1 + 3C.2 merged):

    * ``--merkle-proof <action_record_id>`` (3C.2): download the proof
      from Vera and re-validate it locally.
    * ``--offline <bundle_path>`` (3C.1): verify a previously-exported
      evidence bundle on disk. NO network calls.
    * No flags: online chain-reachability check via /v1/verify.
    """
    # ── --offline routes to 3C.1's pipeline ─────────────────────────
    if offline_bundle is not None:
        if merkle_proof_record_id is not None:
            click.echo(
                "vera verify: --merkle-proof and --offline are mutually "
                "exclusive.",
                err=True,
            )
            sys.exit(2)
        from .verify.cli import (
            EXIT_BUNDLE_ERROR,
            EXIT_OK,
            EXIT_UNEXPECTED,
            EXIT_VERIFICATION_FAILED,
            _print_summary,
        )
        from .verify.offline import BundleError, run_offline_verify

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

    # ── No flags routes to 3C.1's online chain check ─────────────────
    if merkle_proof_record_id is None:
        from .verify.cli import _run_online_verify
        sys.exit(_run_online_verify(timeout))

    # ── --merkle-proof routes to 3C.2's per-record verifier ──────────
    hmac_secret: Optional[bytes] = None
    if hmac_secret_env:
        raw = os.environ.get(hmac_secret_env, "")
        if not raw:
            click.echo(
                f"FAIL --hmac-secret-env {hmac_secret_env!r} is unset "
                "or empty.",
                err=True,
            )
            sys.exit(2)
        hmac_secret = raw.encode("utf-8")

    exit_code, message = verify_merkle_proof_for_record(
        merkle_proof_record_id,
        timeout=timeout,
        hmac_secret=hmac_secret,
    )
    if exit_code == 0:
        click.echo(message)
    else:
        click.echo(message, err=True)
    sys.exit(exit_code)


# ── vera evidence-export ────────────────────────────────────────────────


def _iter_date_range(since: str, until: str):
    """Yield ISO date strings from ``since`` through ``until`` inclusive."""
    start = _dt.date.fromisoformat(since)
    end = _dt.date.fromisoformat(until)
    if end < start:
        raise click.ClickException("--until must be >= --since")
    current = start
    while current <= end:
        yield current.isoformat()
        current = current + _dt.timedelta(days=1)


def _http_get_json(
    client: httpx.Client,
    url: str,
    headers: dict[str, str],
) -> tuple[Optional[dict], int, str]:
    """GET ``url`` and return ``(json_or_none, status_code, raw_text)``.

    ``json_or_none`` is None for non-200 or non-JSON responses. We keep
    the raw text around so the caller can surface a useful error.
    """
    try:
        resp = client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise click.ClickException(f"network error fetching {url}: {exc}")
    if resp.status_code != 200:
        return None, resp.status_code, resp.text
    try:
        return resp.json(), 200, resp.text
    except Exception:
        return None, 200, resp.text


_ACTIONS_PAGE_LIMIT_MAX = 200  # Server caps ``limit`` at 200 (le=200).


def _enumerate_record_ids_in_window(
    client: httpx.Client,
    api_url: str,
    headers: dict[str, str],
    *,
    prior_sequence: int,
    upper_sequence: int,
    customer_tenant_id: Optional[str],
    page_limit: int = _ACTIONS_PAGE_LIMIT_MAX,
) -> list[str]:
    """List record IDs in ``(prior_sequence, upper_sequence]``.

    Uses ``GET /v1/actions`` with **offset-based pagination** — the
    backend route at ``backend/app/routes/actions.py::list_actions``
    supports ``limit``/``offset`` only (no ``since_sequence_number``
    filter; that's a future enhancement). Records are returned in
    ``sequence_number DESC`` order. We walk pages until either:

    1. We see a record whose ``sequence_number`` is at or below
       ``prior_sequence`` (we've walked past our window — stop), or
    2. The page is shorter than ``page_limit`` (no more rows).

    Server-side filters by ``tenant_id`` when ``customer_tenant_id`` is
    set — the same filter the customer dashboard uses, so the
    "selective disclosure" guarantee is enforced by the same code path
    (no chance the SDK leaks rows the server wouldn't have).

    Cross-org STAFF callers go through this same path; the server's
    Wave 3B.3 IAM enforcement constrains the result set to the
    ``X-Org-Id``-resolved org. STAFF tier cannot pass ``tenant_id``
    (the server returns 403 ``staff_phi_filter_forbidden``) — that
    surfaces in the CLI as a transport error, which is the correct
    behaviour: staff sessions cannot run customer-scoped evidence
    exports today.
    """
    page_limit = min(page_limit, _ACTIONS_PAGE_LIMIT_MAX)
    ids: list[str] = []
    offset = 0
    while True:
        params: dict[str, str] = {
            "limit": str(page_limit),
            "offset": str(offset),
        }
        if customer_tenant_id:
            params["tenant_id"] = customer_tenant_id
        query = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{api_url}/v1/actions?{query}"
        body, status, raw = _http_get_json(client, url, headers)
        if status != 200 or body is None:
            raise click.ClickException(
                f"failed to list actions at {url}: "
                f"status={status} body={raw[:200]}"
            )
        # ``/v1/actions`` returns an ``ActionRecordListResponse`` with a
        # ``records: list[...]`` field. Defensive ``isinstance(body,
        # list)`` branch covers a bare-list shape we don't currently
        # emit, but a forward-compat consumer may want to keep working
        # against either shape.
        if isinstance(body, list):
            records = body
        else:
            records = body.get("records") or []
        if not records:
            break
        # Records are sorted ``sequence_number DESC``. Stop walking as
        # soon as we pass below ``prior_sequence``.
        saw_below_window = False
        for r in records:
            seq = r.get("sequence_number")
            rid = r.get("id")
            if seq is None or rid is None:
                continue
            if seq <= prior_sequence:
                saw_below_window = True
                break
            if seq > upper_sequence:
                # Window is half-open above; should be rare since the
                # checkpoint sealed at ``upper_sequence`` is the latest
                # by definition, but skip defensively.
                continue
            ids.append(rid)
        offset += page_limit
        if saw_below_window or len(records) < page_limit:
            break
    return ids


def _write_bundle_file(
    bundle_root: Path, relative: str, content: bytes
) -> None:
    """Write a file under ``bundle_root`` with parent dir creation.

    File mode 0644, directory mode 0755 — these are evidence artifacts
    auditors hand-copy; restrictive perms would hurt usability without
    adding meaningful security (the bundle's value is in the signatures
    on each row, not in the file-perm bits).
    """
    out_path = bundle_root / relative
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(content)


def _build_tarball_from_dir(src: Path, dest: Path) -> None:
    """Create a deterministic gzipped tarball at ``dest`` from ``src/``.

    Determinism rules — auditors will diff:

    * Sort entries lexicographically by archive name.
    * Zero out mtime / uid / gid / uname / gname.
    * Use fixed mode bits (0644 files, 0755 dirs).
    * Use a zero-mtime + ``mtime=0`` gzip header (``GzipFile(mtime=0)``).

    See :mod:`tarfile` docs — these are the standard knobs the Python
    reproducible-builds community settled on.
    """
    import gzip

    entries: list[Path] = sorted(src.rglob("*"))
    # Build the tar in-memory first so we can hand the gzip layer a
    # zero-mtime header. ``tarfile.open(mode="w:gz")`` doesn't expose
    # that option directly.
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tf:
        for entry in entries:
            arcname = str(entry.relative_to(src))
            ti = tarfile.TarInfo(name=arcname)
            ti.mtime = 0
            ti.uid = 0
            ti.gid = 0
            ti.uname = ""
            ti.gname = ""
            if entry.is_dir():
                ti.type = tarfile.DIRTYPE
                ti.mode = 0o755
                tf.addfile(ti)
            else:
                data = entry.read_bytes()
                ti.type = tarfile.REGTYPE
                ti.mode = 0o644
                ti.size = len(data)
                tf.addfile(ti, io.BytesIO(data))
    # Zero-mtime gzip header. ``GzipFile(mtime=0)`` is documented in
    # python-3.6+; older runtimes are unsupported by vera-sdk anyway.
    with open(dest, "wb") as f_out:
        with gzip.GzipFile(
            filename="", mode="wb", fileobj=f_out, mtime=0
        ) as gz:
            gz.write(raw.getvalue())


@click.command(name="evidence-export")
@click.option(
    "--customer",
    "customer_tenant_id",
    type=str,
    default=None,
    help=(
        "Customer tenant_id to scope the export to. When set, the "
        "bundle contains ONLY this customer's records + their "
        "Merkle proofs. Required for selective-disclosure exports."
    ),
)
@click.option(
    "--since",
    type=str,
    required=True,
    help="Inclusive lower bound, ISO-8601 calendar date (YYYY-MM-DD).",
)
@click.option(
    "--until",
    type=str,
    default=None,
    help=(
        "Inclusive upper bound, ISO-8601 calendar date (YYYY-MM-DD). "
        "Defaults to today (UTC)."
    ),
)
@click.option(
    "--out",
    "out_path",
    type=click.Path(dir_okay=True, file_okay=True, path_type=Path),
    required=True,
    help=(
        "Output path. If it ends in ``.tar.gz`` a deterministic "
        "gzipped tarball is written; otherwise a directory at that "
        "path is created with the bundle layout."
    ),
)
@click.option(
    "--timeout",
    type=float,
    default=30.0,
    show_default=True,
    help="Per-request HTTP timeout in seconds.",
)
def evidence_export_cmd(
    customer_tenant_id: Optional[str],
    since: str,
    until: Optional[str],
    out_path: Path,
    timeout: float,
) -> None:
    """Export a self-contained evidence bundle for an audit window.

    Layout:

    \b
        bundle/
          manifest.json
          checkpoints/<date>.json
          records/<id>.json

    ``manifest.json`` carries ``vera_version``, ``exported_at``,
    ``customer_id``, the date window, and counts. Each per-checkpoint
    file is the byte-stable body returned by
    ``GET /v1/checkpoints/{date}``. Each per-record file is the body
    returned by ``GET /v1/records/{id}/merkle-proof`` — i.e. enough
    material for an offline verifier to re-validate the proof against
    the KMS public key embedded in the same file.

    Selective-disclosure rule (per Wave 3C.2 brief): when
    ``--customer <tenant_id>`` is set, the bundle contains ONLY that
    tenant's records. Other customers' rows are NOT included. The
    verifier can only see sibling hashes (Merkle path neighbours) of
    foreign records — never the leaves themselves. Hashes carry no
    PHI and reveal neither count nor identity of foreign records.
    """
    # ── Validate dates ───────────────────────────────────────────────
    if not _DATE_RE.match(since):
        raise click.ClickException(
            f"--since must be YYYY-MM-DD, got {since!r}"
        )
    if until is None:
        until = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    if not _DATE_RE.match(until):
        raise click.ClickException(
            f"--until must be YYYY-MM-DD, got {until!r}"
        )

    api_url = _resolve_api_url()
    headers = _build_headers()

    # ── Choose output mode (dir vs tarball) ──────────────────────────
    tarball_mode = str(out_path).endswith(".tar.gz")
    if tarball_mode:
        if out_path.exists() and not out_path.is_file():
            raise click.ClickException(
                f"--out path {out_path} exists but is not a file."
            )
        # We assemble into a temp dir first, then tar+gz.
        import tempfile

        scratch = Path(tempfile.mkdtemp(prefix="vera-evidence-"))
        bundle_root = scratch / "bundle"
    else:
        bundle_root = out_path
        bundle_root.mkdir(parents=True, exist_ok=True)

    checkpoint_count = 0
    record_count = 0
    record_ids_seen: set[str] = set()
    # Track records that we enumerated but could not fetch a proof for.
    # 404 → record_not_found (deleted server-side after action list
    # fetched, or an org/auth-scope filter changed mid-export). 409 →
    # checkpoint_pending (tail-window race: record exists but its
    # checkpoint hasn't sealed yet). Surface these to stderr + manifest
    # so the omission is auditable — silent skips break regulator-ready
    # evidence claims.
    skipped_records: list[dict[str, str]] = []

    # ── Per-day loop ─────────────────────────────────────────────────
    with httpx.Client(timeout=timeout) as client:
        # Cache the prior_seq for each checkpoint so we can enumerate
        # records in its window. We process days in order so each
        # checkpoint's prior_seq is naturally available.
        prior_sequence = 0
        for date_iso in _iter_date_range(since, until):
            cp_url = f"{api_url}/v1/checkpoints/{date_iso}"
            body, status, raw = _http_get_json(client, cp_url, headers)
            if status == 404 or status == 409:
                # No checkpoint that day — skip silently. (409 means
                # today's hasn't sealed yet — same outcome for export.)
                continue
            if status == 401 or status == 403:
                raise click.ClickException(
                    f"auth failed for {cp_url}: {raw[:200]}"
                )
            if status != 200 or body is None:
                raise click.ClickException(
                    f"failed to fetch checkpoint for {date_iso}: "
                    f"status={status} body={raw[:200]}"
                )

            cp_body_bytes = json.dumps(
                body, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            # Defense-in-depth: ``date_iso`` is locally generated by
            # ``_iter_date_range`` from validated user input, but the
            # guard is cheap and protects against a future refactor
            # that might thread a server-supplied date through here.
            _require_safe_date(date_iso)
            _write_bundle_file(
                bundle_root, f"checkpoints/{date_iso}.json", cp_body_bytes
            )
            checkpoint_count += 1

            upper_sequence = int(body.get("sequence_at_checkpoint") or 0)
            this_prior = (
                int(body.get("prior_sequence_at_checkpoint") or 0)
                if "prior_sequence_at_checkpoint" in body
                else prior_sequence
            )
            # Some servers don't echo prior_sequence_at_checkpoint —
            # fall back to the running prior_sequence. The 3B.1 body
            # carries ``prior_checkpoint_id`` but not the prior
            # sequence; we infer it from the previous-day's upper
            # bound, which is correct as long as we walk days in
            # order.
            if upper_sequence <= 0:
                # Empty checkpoint window — nothing to enumerate.
                prior_sequence = max(prior_sequence, upper_sequence)
                continue

            # ── Enumerate records and fetch their proofs ──────────
            record_ids = _enumerate_record_ids_in_window(
                client,
                api_url,
                headers,
                prior_sequence=this_prior,
                upper_sequence=upper_sequence,
                customer_tenant_id=customer_tenant_id,
            )
            for rid in record_ids:
                if rid in record_ids_seen:
                    continue
                # Hard-fail the export if the server hands us a record id
                # that doesn't look like a uuid4. Bundle integrity is
                # suspect once this happens — we abort rather than skip
                # the row, because partial success on a tampered server
                # response is worse than no bundle at all (an auditor
                # would not know rows were silently dropped).
                _require_safe_record_id(rid)
                proof_url = (
                    f"{api_url}/v1/records/{rid}/merkle-proof"
                )
                proof_body, p_status, p_raw = _http_get_json(
                    client, proof_url, headers
                )
                if p_status == 404 or p_status == 409:
                    # Skip records we can't currently prove. 409 = tail.
                    # Record the skip so we can surface it to the
                    # operator (stderr) and to post-hoc auditors
                    # (manifest.json::skipped_records). Without this
                    # the omission is invisible and the bundle's
                    # ``record_count`` silently undercounts.
                    reason = (
                        "checkpoint_pending"
                        if p_status == 409
                        else "record_not_found"
                    )
                    skipped_records.append({"id": rid, "reason": reason})
                    record_ids_seen.add(rid)
                    continue
                if p_status != 200 or proof_body is None:
                    raise click.ClickException(
                        f"failed to fetch proof for {rid}: "
                        f"status={p_status} body={p_raw[:200]}"
                    )
                proof_bytes = json.dumps(
                    proof_body, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
                _write_bundle_file(
                    bundle_root, f"records/{rid}.json", proof_bytes
                )
                record_count += 1
                record_ids_seen.add(rid)

            prior_sequence = max(prior_sequence, upper_sequence)

    # ── Manifest ─────────────────────────────────────────────────────
    # ``exported_at`` is wall-clock UTC. We zero it out when running
    # under the deterministic-tarball test hook so two invocations
    # produce byte-identical artifacts. Hook: env var
    # ``VERA_EVIDENCE_EXPORT_FAKE_NOW`` (ISO-8601 timestamp) lets the
    # determinism test set a fixed clock without monkeypatching
    # ``datetime``.
    fake_now = os.environ.get("VERA_EVIDENCE_EXPORT_FAKE_NOW", "").strip()
    if fake_now:
        exported_at = fake_now
    else:
        exported_at = _dt.datetime.now(_dt.timezone.utc).isoformat()

    try:
        from importlib.metadata import (
            PackageNotFoundError,
            version as _pkg_version,
        )

        try:
            vera_version = _pkg_version("vera-sdk")
        except PackageNotFoundError:
            vera_version = "unknown"
    except Exception:
        vera_version = "unknown"

    manifest = {
        "bundle_version": _BUNDLE_VERSION,
        "vera_version": vera_version,
        "exported_at": exported_at,
        "customer_id": customer_tenant_id,
        "since": since,
        "until": until,
        "checkpoint_count": checkpoint_count,
        "record_count": record_count,
        # Always include the field (empty list on a clean run) so
        # downstream consumers can presence-check without branching
        # on key existence. The field is stable across bundle
        # versions; new reason codes may appear but the shape will
        # not change.
        "skipped_records": skipped_records,
    }
    manifest_bytes = json.dumps(
        manifest, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    _write_bundle_file(bundle_root, "manifest.json", manifest_bytes)

    # ── Tarball mode: pack the bundle deterministically ──────────────
    if tarball_mode:
        _build_tarball_from_dir(bundle_root, out_path)
        # Clean up the scratch dir.
        import shutil

        shutil.rmtree(bundle_root.parent, ignore_errors=True)

    # ── Surface skipped records to stderr ────────────────────────────
    # Auditors and operators need to know when the bundle is missing
    # records that were enumerated but couldn't be proven. The warning
    # is informational (exit 0 — tail-window skips are expected
    # routine in a streaming system), but it is loud and structured so
    # it can't be missed in a CI log or terminal session.
    if skipped_records:
        click.echo(
            f"WARN  {len(skipped_records)} records skipped from this "
            "bundle:",
            err=True,
        )
        cap = 50
        for entry in skipped_records[:cap]:
            click.echo(
                f"  - {entry['id']}  reason={entry['reason']}",
                err=True,
            )
        if len(skipped_records) > cap:
            click.echo(
                f"  (and {len(skipped_records) - cap} more — see "
                "manifest.json::skipped_records)",
                err=True,
            )
        click.echo(
            "These records may have been written too recently to be "
            "sealed into a",
            err=True,
        )
        click.echo(
            "checkpoint (try re-running --since one cadence period "
            "earlier), or",
            err=True,
        )
        click.echo(
            "were deleted server-side after the action list was "
            "fetched.",
            err=True,
        )

    click.echo(
        f"Exported {record_count} records across {checkpoint_count} "
        f"checkpoints to {out_path}"
    )
    sys.exit(0)
