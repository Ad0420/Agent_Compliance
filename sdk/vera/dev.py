"""Dev mode: prints audit records to stderr as JSON instead of POSTing.

Use for local development without a Vera API key, OR for unit tests that
want to assert on audit-record shape without spinning up a mock HTTP server.

Activated three ways:

* :func:`vera.init(dev=True)` — explicit kwarg.
* ``VERA_DEV=1`` env var picked up by :func:`vera.init` when no ``dev=`` is
  passed.
* :meth:`vera.client.VeraClient.dev` classmethod — ergonomic shortcut that
  matches the Sentry/Datadog pattern.

Dev mode bypasses the network entirely: records flow through
:meth:`vera.client.VeraClient._build_payload` and the redactor (if set),
then land in :class:`_StderrSink.records` for assertion. ``echo=True``
(default) also writes a ``[vera-dev] {...}`` JSON line to ``sys.stderr`` so
records are visible in CLI output.

Safety rails (CRITICAL fixes on PR #170):

* Dev mode FORCE-DISABLES the durable spool, including ignoring
  ``VERA_SPOOL_PATH``. Inheriting the parent's spool would rehydrate queued
  PHI from prior production runs and print it to stderr — a HIPAA leak path.
* Dev mode emits a loud WARN + stderr banner on construction so a customer
  who accidentally ships ``VERA_DEV=1`` to prod sees the signal in their
  logs immediately.
* Dev mode refuses to construct when ``api_key`` looks like a production
  key (``al_live_*``) unless ``VERA_DEV_CONFIRM=1`` is also set. This stops
  the silent-audit-loss failure mode where a dev mode flag escapes from
  staging to prod.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

from .client import _NO_SPOOL_SENTINEL, VeraClient
from .errors import VeraError

logger = logging.getLogger("vera.dev")


def _is_production_looking_key(api_key: str | None) -> bool:
    """Best-effort heuristic for distinguishing live keys from dev/test keys.

    Currently flags only the ``al_live_`` prefix. The check is intentionally
    narrow — a false positive blocks a legitimate dev workflow, and the
    ``VERA_DEV_CONFIRM=1`` escape hatch exists for that case.
    """
    return bool(api_key) and api_key.startswith("al_live_")


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name, "").strip().lower()
    if not val:
        return default
    return val in {"1", "true", "yes", "on"}


class _StderrSink:
    """Captures enqueued records and (optionally) prints them to stderr.

    The captured list is kept on ``records`` for assertions in tests. ``echo``
    controls whether each record is also written to ``sys.stderr`` as
    ``[vera-dev] <json>``. The pytest fixture defaults to ``echo=False`` so
    test output stays clean; CLI dev mode (:func:`vera.init(dev=True)`)
    defaults to ``echo=True`` so engineers see records during a run.
    """

    def __init__(self, *, echo: bool = True):
        self.records: list[dict] = []
        self._echo = echo

    def record(self, payload: dict) -> None:
        """Add a payload to ``records`` and (optionally) echo to stderr.

        ``json.dumps`` uses ``default=str`` so dev-mode never blows up on
        objects that aren't natively JSON-serializable (datetimes, UUIDs,
        pydantic models, etc.) — the on-wire path would have run the same
        coercion via :class:`vera.redaction.Redactor`.
        """
        self.records.append(payload)
        if self._echo:
            try:
                serialized = json.dumps(payload, default=str)
            except Exception:  # pragma: no cover — defensive
                serialized = repr(payload)
            print(
                f"[vera-dev] {serialized}",
                file=sys.stderr,
                flush=True,
            )

    def reset(self) -> None:
        """Clear ``records`` without affecting the echo setting."""
        self.records.clear()


class DevClient(VeraClient):
    """Drop-in :class:`VeraClient` for dev mode.

    Overrides :meth:`record_action` and :meth:`enqueue_action` to route
    records through an in-memory :class:`_StderrSink` instead of POSTing to
    the Vera API. Every other public method on :class:`VeraClient` is
    inherited unchanged — so the ``@audit`` decorator path, the redactor,
    and the build-payload logic are exercised identically. Tests that
    assert on payload shape are testing the same production codepath.

    See module docstring for the safety rails (no spool, prod-key guard,
    loud startup banner).
    """

    def __init__(self, *, sink: _StderrSink | None = None, **kwargs: Any):
        # Refuse dev mode on a production-looking key unless explicitly
        # confirmed. Otherwise an accidental VERA_DEV=1 in production turns
        # the audit log off silently — the worst failure mode for a
        # compliance product.
        explicit_api_key = kwargs.get("api_key")
        effective_api_key = (
            explicit_api_key
            if explicit_api_key is not None
            else os.environ.get("VERA_API_KEY")
        )
        if _is_production_looking_key(effective_api_key) and not _env_bool(
            "VERA_DEV_CONFIRM", default=False
        ):
            raise VeraError(
                "vera-dev-002: Refusing to enable DEV mode with a "
                "production-looking API key (prefix 'al_live_'). DEV mode "
                "would silently disable real audit logging — a HIPAA / "
                "compliance failure mode in production. Set "
                "VERA_DEV_CONFIRM=1 to bypass (use with extreme caution)."
            )

        # Dev mode doesn't need real network config. Stub both fields so the
        # parent's __init__ doesn't WARN about missing api_key.
        kwargs.setdefault("api_url", "http://dev.local")
        kwargs.setdefault("api_key", "dev")

        # Force-disable spool in dev mode. Inheriting VeraClient's spool
        # logic is a HIPAA leak path: VERA_SPOOL_PATH from env could
        # rehydrate queued PHI from a prior production process into our
        # stderr sink. Pop any explicit kwarg AND inject the sentinel so the
        # parent constructor SKIPS the env-var fallback entirely.
        kwargs.pop("persistent_buffer_path", None)
        kwargs["persistent_buffer_path"] = _NO_SPOOL_SENTINEL

        super().__init__(**kwargs)
        self.sink = sink or _StderrSink()

        # Loud one-time signal that dev mode is active. WARN level so it
        # shows up in production logging without needing a debug-level
        # logger config. Goes to stderr too so a CLI run is visibly marked.
        logger.warning(
            "[vera-dev-001] DEV MODE ACTIVE — records will NOT be sent to "
            "the Vera audit service. Set VERA_DEV=0 or remove `dev=True` to "
            "enable real audit logging."
        )
        print(
            "\n  [Vera DEV mode] Records are printed to stderr only. "
            "NOT a compliance-grade audit trail.\n",
            file=sys.stderr,
            flush=True,
        )

    def record_action(self, **kwargs: Any) -> dict:  # type: ignore[override]
        payload = self._build_payload(**kwargs)
        payload = self._redact_payload_fields(payload)
        self.sink.record(payload)
        seq = len(self.sink.records)
        # Match the production return shape so customer code that pulls
        # ``sequence_number`` / ``recorded_at`` doesn't KeyError only in
        # dev. The ``mode`` key is the one dev-only marker — explicit, not
        # surprising.
        return {
            "status": "success",
            "mode": "dev",
            "record_id": f"dev-{seq}",
            "sequence_number": seq,
            "recorded_at": datetime.now(timezone.utc).isoformat().replace(
                "+00:00", "Z"
            ),
        }

    def enqueue_action(self, **kwargs: Any) -> None:
        payload = self._build_payload(**kwargs)
        payload = self._redact_payload_fields(payload)
        self.sink.record(payload)

    def close(self) -> None:
        """No-op in dev mode — no background worker or HTTP client to drain."""
        return None


def build_dev_client(
    *,
    agent_name: str | None = None,
    sink: _StderrSink | None = None,
    echo: bool = True,
    **kwargs: Any,
) -> DevClient:
    """Construct a :class:`DevClient` with sensible dev defaults.

    Args:
        agent_name: Identity stamped onto every captured record. Defaults to
            ``"dev-agent"``.
        sink: Pre-constructed sink. When ``None``, a fresh sink with the
            given ``echo`` setting is created.
        echo: Whether the sink writes a ``[vera-dev] {...}`` JSON line to
            stderr for each record. Defaults to ``True`` (CLI dev mode);
            the pytest fixture overrides to ``False``.
        **kwargs: Passed through to :class:`DevClient`.

    Returns:
        A configured :class:`DevClient` registered with the supplied sink.
    """
    return DevClient(
        sink=sink or _StderrSink(echo=echo),
        agent_name=agent_name or "dev-agent",
        **kwargs,
    )
