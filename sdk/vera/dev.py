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
"""

from __future__ import annotations

import json
import sys
from typing import Any

from .client import VeraClient


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
    """

    def __init__(self, *, sink: _StderrSink | None = None, **kwargs: Any):
        # Dev mode doesn't need real network config. Stub both fields so the
        # parent's __init__ doesn't WARN about missing api_key.
        kwargs.setdefault("api_url", "http://dev.local")
        kwargs.setdefault("api_key", "dev")
        super().__init__(**kwargs)
        self.sink = sink or _StderrSink()

    def record_action(self, **kwargs: Any) -> dict:  # type: ignore[override]
        payload = self._build_payload(**kwargs)
        payload = self._redact_payload_fields(payload)
        self.sink.record(payload)
        return {"status": "dev", "record_id": f"dev-{len(self.sink.records)}"}

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
