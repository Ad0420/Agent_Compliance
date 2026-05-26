"""``@vera.gate`` decorator (Phase 1 PR 8 / Stream D5).

The ``@vera.gate`` decorator is the v1 primitive for wrapping an agent
action: it POSTs ``/v1/gates/evaluate`` to ask the backend whether the
action is permitted, routes the resulting :class:`Ruling`, and (on
ALLOW) captures the function call as an action record exactly the way
the legacy ``@vera.audit`` decorator did.

Ruling routing
--------------

* ``effect == "ALLOW"`` — invoke the wrapped function, capture the
  call as an :class:`ActionRecord`, return the result.
* ``effect == "REQUIRE_HITL"`` — invoke the wrapped function for a
  draft, capture the call as an :class:`ActionRecord`, then raise
  :class:`vera.errors.PendingReview` so the caller's exception handler
  can decide what to do with the draft. The audit-trail capture happens
  BEFORE the raise — losing the draft on the raise path would defeat
  the purpose of the gate.
* ``effect == "BLOCK"`` — do NOT invoke the wrapped function, raise
  :class:`vera.errors.PolicyBlock` immediately.

Phase 1 vs Phase 2
------------------

The backend ``/v1/gates/evaluate`` endpoint lands in Phase 2. For Phase
1 the decorator ships today and auto-activates when the backend lands:

* If the endpoint returns ``404`` we fall back to legacy ``@vera.audit``
  semantics (invoke + capture) with a single ``UserWarning`` per process.
* If the endpoint returns any other status, we surface the branded error
  the existing httpx wrapper produces (``VeraAuthError``,
  ``VeraNetworkError``, ``PolicyBlock``, ``PendingReview``, ...).

Realtime mode (Wave 2C PR B2)
-----------------------------

``@vera.gate(realtime=True)`` changes how ``REQUIRE_HITL`` rulings are
routed at the call site. The default ``PendingReview`` exception
forces a "block and wait" pattern that is unacceptable in some
domains — e.g. a clinical scribe responding to a doctor's voice in
real time cannot block waiting for an attending physician to sign
off. ``realtime=True`` routes the same ruling to a distinct
:class:`vera.errors.RequiresDeferredReview` exception so customer
code can implement a "queue and continue" pattern: queue the action
into a customer-side deferred-execution store, return a placeholder
to the user immediately, resume once the ``review.completed`` webhook
fires.

``ALLOW`` and ``BLOCK`` rulings are unchanged when ``realtime=True``
— BLOCK is always immediate; ALLOW is always invoke+capture.

Testing
-------

The :func:`vera.testing.bypass_gates` fixture flips a ContextVar that
this module checks before doing any HTTP work. With the fixture active
the decorator skips the backend call, treats the ruling as ALLOW, and
still captures the ActionRecord (audit-trail invariant). Useful for
pilot test suites that don't want to wire up an httpx ``MockTransport``
for every gate.
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
import inspect
import logging
import time
import traceback
import warnings
from typing import Any, Callable, Optional

from ._context import resolve_agent_type, resolve_tenant
from .errors import (
    PendingReview,
    PolicyBlock,
    RequiresDeferredReview,
    TenantMissingOrInvalid,
    VeraClientError,
    VeraError,
)
from .redaction import Redactor


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Bypass machinery (Phase 1 PR 8 / Stream D10).
# ---------------------------------------------------------------------------

# When True, ``@vera.gate`` skips the backend call entirely and routes
# every ruling as ALLOW. Used by the :func:`vera.testing.bypass_gates`
# pytest fixture so pilot test suites don't have to mock
# ``/v1/gates/evaluate``. ContextVar (rather than a module-level bool)
# so concurrent asyncio tasks / threads can have different bypass states
# without interfering with each other — matching the tenant resolver's
# isolation model (Codex F4).
_bypass_gates_var: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "vera_bypass_gates", default=False
)


def is_bypassing_gates() -> bool:
    """Return True when ``@vera.gate`` should skip the backend call.

    Read by :func:`gate` / :func:`async_gate` before doing any HTTP
    work. Public so the testing fixture (and curious users) can
    introspect the current bypass state.
    """
    return _bypass_gates_var.get()


def _set_bypass(value: bool) -> contextvars.Token:
    """Set the bypass flag, returning a token for restoration.

    Used by :func:`vera.testing.bypass_gates`. Not part of the public
    API — callers should use the fixture / context manager.
    """
    return _bypass_gates_var.set(value)


def _reset_bypass(token: contextvars.Token) -> None:
    """Restore the bypass flag to its previous value."""
    _bypass_gates_var.reset(token)


# ---------------------------------------------------------------------------
# 404 fallback once-per-process warning.
# ---------------------------------------------------------------------------

# Tracks whether the once-per-process "evaluate endpoint missing" WARN
# has fired. The 404 fallback exists so the decorator ships today and
# auto-graduates to full gate semantics when Phase 2 lands the backend
# endpoint — without an SDK release.
_evaluate_404_warned: bool = False

_EVALUATE_404_WARNING = (
    "vera.gate: POST /v1/gates/evaluate returned 404. Falling back to "
    "audit-only capture (no policy enforcement). The decorator will "
    "graduate to full gate semantics automatically when the Phase 2 "
    "backend endpoint lands; no SDK release required."
)


def _warn_evaluate_404_once() -> None:
    """Emit a single ``UserWarning`` per process for the 404 fallback path."""
    global _evaluate_404_warned
    if _evaluate_404_warned:
        return
    _evaluate_404_warned = True
    warnings.warn(_EVALUATE_404_WARNING, UserWarning, stacklevel=3)
    logger.warning(_EVALUATE_404_WARNING)


def _reset_evaluate_404_warning() -> None:
    """Reset the once-per-process flag. Intended for tests."""
    global _evaluate_404_warned
    _evaluate_404_warned = False


# ---------------------------------------------------------------------------
# Evaluate endpoint constants.
# ---------------------------------------------------------------------------

GATE_EVALUATE_PATH = "/v1/gates/evaluate"

# Ruling effects the SDK knows how to route. Anything else falls through
# to ALLOW with a once-per-process WARN (defensive — don't crash on a
# backend that ships a new ruling type ahead of an SDK update).
_RULING_ALLOW = "ALLOW"
_RULING_REQUIRE_HITL = "REQUIRE_HITL"
_RULING_BLOCK = "BLOCK"
_RULING_REQUIRE_DEFERRED_REVIEW = "REQUIRE_DEFERRED_REVIEW"
_KNOWN_RULINGS = {
    _RULING_ALLOW,
    _RULING_REQUIRE_HITL,
    _RULING_BLOCK,
    _RULING_REQUIRE_DEFERRED_REVIEW,
}

# Wire-level ``result`` enum the backend accepts on ``POST /v1/actions(/batch)``.
# Must stay in sync with ``backend/app/schemas/action.py::_CLIENT_RESULT_VALUES``.
# ``blocked`` is intentionally NOT in this set: the backend reserves it for the
# policy engine, which assigns it inside ``build_and_insert_record`` when a
# block-action policy fires. Clients self-attesting ``blocked`` would let
# callers claim "policy fired" without one actually firing — see the comment
# block above ``_CLIENT_RESULT_VALUES`` in the backend schema for details.
_WIRE_RESULT_VALUES = {"success", "failure", "partial", "pending"}

# Gate-effect-derived results we emit at call sites — these are the SDK's
# semantic vocabulary for what happened at the gate. They MUST be normalised
# to a wire-acceptable value before reaching the backend; the original is
# preserved in ``metadata.gate_result`` so downstream audit can distinguish
# "the engine blocked us" from "we tried and the wrapped function errored".
#
# Mapping rationale:
#   "blocked"         → "failure": the call did not succeed; the gate refused.
#                       Pair with ``metadata.ruling_effect="BLOCK"`` (already
#                       stamped) for the unambiguous audit signal.
#   "pending_review"  → "pending": the record exists; a human is on the hook
#                       to resolve it. ``metadata.ruling_effect`` carries
#                       REQUIRE_HITL vs REQUIRE_DEFERRED_REVIEW; ``review_id``
#                       links to the materialised approval/review row.
_GATE_RESULT_TO_WIRE_RESULT = {
    "blocked": "failure",
    "pending_review": "pending",
}


def _normalize_result_for_wire(result: str) -> tuple[str, Optional[str]]:
    """Map a gate-emitted ``result`` to a backend-acceptable value.

    Returns ``(wire_result, original_or_None)``. ``original_or_None`` is
    ``None`` when the caller already used a wire-acceptable value (no
    rewrite happened) and the original string when we rewrote it — so
    ``_capture_action`` can stash the original in ``metadata.gate_result``.

    Anything outside the known gate-effect vocabulary AND the wire-accepted
    set falls through unchanged; the backend's validator will surface the
    422 in that case (which is the right outcome — silently rewriting
    arbitrary inputs would hide bugs in new call sites).
    """
    if result in _WIRE_RESULT_VALUES:
        return result, None
    mapped = _GATE_RESULT_TO_WIRE_RESULT.get(result)
    if mapped is not None:
        return mapped, result
    return result, None

_unknown_ruling_warned: set[str] = set()


def _warn_unknown_ruling_once(effect: str) -> None:
    if effect in _unknown_ruling_warned:
        return
    _unknown_ruling_warned.add(effect)
    warnings.warn(
        f"vera.gate: backend returned unknown effect {effect!r}; "
        f"treating as ALLOW. Update the SDK to consume the new ruling.",
        UserWarning,
        stacklevel=3,
    )


def _reset_unknown_ruling_warnings() -> None:
    """Reset the once-per-process dedupe set. Intended for tests."""
    _unknown_ruling_warned.clear()


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _resolve_client(explicit_client: Any, *, async_preferred: bool = False) -> Any:
    """Return the client to use, falling back to the module-level default.

    Sync wrappers (``async_preferred=False``) consult the sync default
    registered via ``vera.init`` / ``vera.set_default_client``.

    Async wrappers (``async_preferred=True``) consult the async default
    FIRST (registered via ``vera.init_async`` /
    ``vera.set_default_async_client``) and only fall back to the sync
    default if no async client is registered. This mirrors the legacy
    ``@async_audit`` resolution order so async-only customers don't
    have to register two clients.

    Imported lazily to avoid a circular import at module load —
    :mod:`vera.decorator` is imported by :mod:`vera.__init__` and
    we need to not pull it in until first call.
    """
    if explicit_client is not None:
        return explicit_client
    if async_preferred:
        from . import async_decorator as _async_decorator_mod
        from . import decorator as _decorator_mod

        return (
            _async_decorator_mod._default_async_client
            or _decorator_mod._default_client
        )
    from . import decorator as _decorator_mod

    return _decorator_mod._default_client


def _short_key_hint(api_key: Optional[str]) -> str:
    """Stable, non-secret hint derived from the API key for ``authorized_by``.

    The backend ``GateEvaluateRequest.authorized_by`` is a free-form
    string used to identify the principal who authorised the action.
    We want it correlatable across requests (so the audit ledger groups
    calls by API key) but the full key MUST NEVER leave the SDK
    process — that's the threat model the key tier prefix (``al_test_``
    / ``al_live_``) exists to support.

    Format: ``api_key:<first 8 chars>…`` so the tier prefix survives
    while the secret bulk doesn't, and downstream consumers can tell
    the principal kind (``api_key:...`` vs. a future ``oauth:...`` /
    ``service_account:...``). Falls back to ``"sdk"`` when no key is
    configured (matches the existing client warning that auth-less
    operation degrades gracefully). Wave 2B PR B1.
    """
    if not api_key:
        return "sdk"
    return f"api_key:{api_key[:8]}…"


def _client_api_key(client: Any) -> Optional[str]:
    """Recover the configured API key from a ``VeraClient`` for ``authorized_by``.

    The client stores the bearer token in
    ``client._client.headers["Authorization"]`` (set at
    ``VeraClient.__init__``) rather than as an attribute, so the key
    never appears in ``dir(client)`` / repr output. Strip the
    ``"Bearer "`` prefix and return what's left.

    Returns ``None`` when the header is absent or empty so the caller
    can fall back to the ``"sdk"`` sentinel.
    """
    try:
        headers = client._client.headers
    except AttributeError:
        return None
    auth = headers.get("Authorization", "") if headers is not None else ""
    if not auth:
        return None
    if auth.startswith("Bearer "):
        return auth[len("Bearer "):] or None
    return auth or None


def _safe_reason_detail(raw: Optional[str]) -> Optional[str]:
    """Defensive PHI redaction on ``reason_detail`` before exception surfaces.

    The backend ``Ruling.reason_detail`` contract (PR #212) forbids PHI
    in the field, but the SDK is the last hop into customer process
    memory + their structured-log aggregator. If the backend ever
    leaked a PHI-shaped string (a bug we want to detect at the
    boundary, not propagate), the SDK redacts it before stamping onto
    the raised exception so it doesn't reach the customer's
    ``except`` handler / log line.

    Reuses the same heuristic the tenant resolver applies
    (``errors._looks_like_phi`` for SSN/DOB shapes,
    ``errors._is_likely_phi`` for whitespace+digit combos). Leans
    toward false-positive — losing a diagnostic string is vastly
    cheaper than echoing PHI into a stack trace surfaced in a log
    pipeline. Wave 2B PR B1.
    """
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw:
        return raw
    # Lazy import to avoid pulling errors module helpers on hot paths
    # that don't go through a HITL / BLOCK ruling.
    from .errors import _is_likely_phi, _looks_like_phi

    if _looks_like_phi(raw) or _is_likely_phi(raw):
        return "(redacted: reason_detail matched PHI-shape heuristic)"
    return raw


def _build_evaluate_request(
    *,
    action_class: str,
    action_type: str,
    tenant_id: str,
    tenant_source: str,
    agent_name: str,
    agent_id: Optional[str],
    agent_type: Optional[str],
    authorized_by: str,
    input_data: Any,
    data_subject_id: Optional[str] = None,
    target_system: Optional[str] = None,
    target_resource: Optional[str] = None,
    action_description: Optional[str] = None,
) -> dict:
    """Build the JSON body for ``POST /v1/gates/evaluate``.

    Wire shape matches the backend ``GateEvaluateRequest`` pydantic
    schema (``backend/app/schemas/gate.py``, shipped in Wave 2A
    PR #212). Required fields (``agent_name``, ``action_type``,
    ``action_name``, ``authorized_by``) are always populated; optional
    fields are emitted only when the caller supplied a value (skipped
    when ``None`` to avoid ``null`` clutter and let the server's
    defaults take over).

    The legacy ``agent_type`` taxonomy survives in ``metadata`` (the
    server schema does not have a top-level ``agent_type`` and would
    drop it under ``extra="ignore"`` if we tried) — keeps the existing
    observability shape carrying the field while the wire body stays
    spec-compliant. Wave 2B PR B1.
    """
    if not agent_name:
        # The backend schema marks ``agent_name`` as required with
        # ``min_length=1`` — a missing client.agent_name would 422 at
        # the gate boundary. Raise client-side with an actionable
        # message instead so the customer sees the root cause without
        # round-tripping the validation envelope.
        raise VeraClientError(
            "vera.gate requires client.agent_name to be set; pass "
            "agent_name= to vera.init() or set VERA_AGENT_NAME.",
            user_facing_reason=(
                "Vera could not evaluate this action — agent_name is required."
            ),
            developer_reason=(
                "client.agent_name is empty/None; backend GateEvaluateRequest "
                "requires agent_name >= 1 char."
            ),
        )
    body: dict[str, Any] = {
        "agent_name": agent_name,
        "action_type": action_type,
        "action_name": action_class,
        "authorized_by": authorized_by,
        # Nested under metadata for the same reason as
        # ``_build_payload`` in client.py: pydantic v2 ``extra="ignore"``
        # would otherwise silently drop the provenance field.
        "metadata": {"tenant_source": tenant_source},
        "input_data": input_data,
    }
    body["tenant_id"] = tenant_id

    # Optional top-level fields — only emit when caller provided.
    if agent_id is not None:
        body["agent_id"] = agent_id
    if action_description is not None:
        body["action_description"] = action_description
    if data_subject_id is not None:
        body["data_subject_id"] = data_subject_id
    if target_system is not None:
        body["target_system"] = target_system
    if target_resource is not None:
        body["target_resource"] = target_resource

    # Legacy ``agent_type`` rides in metadata (backend schema has no
    # top-level slot for it).
    if agent_type is not None:
        body["metadata"]["agent_type"] = agent_type

    return body


def _capture_action(
    client: Any,
    *,
    action_name: str,
    action_type: str,
    result: str,
    input_data: Any,
    outcome: Any,
    duration_ms: int,
    error_message: Optional[str],
    tenant_id: str,
    agent_type: Optional[str],
    review_id: Optional[str] = None,
    ruling_effect: Optional[str] = None,
) -> None:
    """Capture the action via the client's background queue.

    All decorator paths funnel through here so the ActionRecord shape
    is identical whether the ruling was ALLOW / REQUIRE_HITL or we
    fell through the 404-fallback / bypass paths. Vera-side failures
    are swallowed and logged at WARN — they MUST NEVER mask the
    customer's exception (mirrors the legacy ``@vera.audit`` contract).
    """
    # W1.3 (audit-batch-422) — normalise gate-vocabulary ``result`` values
    # to the backend's accepted enum before they hit the wire. Without this,
    # every HITL / BLOCK capture 422'd at ``POST /v1/actions/batch`` and the
    # SDK's worker dropped the record (see ``client._handle_flush_failure``'s
    # "permanent failure" branch). The audit chain was silently incomplete.
    #
    # The original gate-emitted value is preserved in ``metadata.gate_result``
    # so the dashboard / regulator-PDF surface can still tell "the gate
    # blocked us" apart from "the wrapped function raised". ``ruling_effect``
    # already carries the gate's verdict in machine-readable form; this is
    # belt-and-suspenders so a reader who only looks at ``result`` doesn't
    # silently conflate the two.
    wire_result, original_result = _normalize_result_for_wire(result)

    record_kwargs: dict[str, Any] = dict(
        action_name=action_name,
        action_type=action_type,
        result=wire_result,
        input_data=input_data,
        outcome=outcome,
        duration_ms=duration_ms,
        error_message=error_message,
        tenant=tenant_id,
    )
    # Stamp agent_type / review_id / ruling_effect into metadata so the
    # audit trail carries them even when ``extra="ignore"`` is set on
    # the backend's pydantic schema. ``tenant_source`` is stamped by
    # ``client._build_payload`` based on the resolver — we don't need
    # to forward it here.
    metadata: dict[str, Any] = {}
    if agent_type is not None:
        metadata["agent_type"] = agent_type
    if review_id is not None:
        metadata["review_id"] = review_id
    if ruling_effect is not None:
        metadata["ruling_effect"] = ruling_effect
    if original_result is not None:
        metadata["gate_result"] = original_result
    if metadata:
        record_kwargs["metadata"] = metadata
    try:
        client.enqueue_action(**record_kwargs)
    except Exception as audit_exc:  # noqa: BLE001
        logger.warning(
            "vera.gate: failed to capture action record for %s: %s",
            action_name,
            audit_exc,
        )


def _parse_ruling(body: dict) -> dict:
    """Coerce the backend ``Ruling`` envelope into the dict the decorator routes on.

    Contract per backend ``app/schemas/gate.py::Ruling`` (Wave 2A PR #212):
      * ``effect``        — ``"allow" | "require_hitl" | "block"`` (lowercase)
      * ``reason``        — machine-readable reason code
      * ``reason_detail`` — human-readable explanation, NEVER PHI
                            (SDK defensively redacts via ``_safe_reason_detail``)
      * ``citation``      — optional regulatory citation
      * ``gate_name``     — identifier of the gate that produced the ruling
      * ``review_id``     — present iff ``effect == "require_hitl"``
      * ``fix_url``       — dashboard URL for remediation / review
      * ``required_role`` — reviewer role required (HITL paths)
      * ``retryable``     — defaults False on the wire

    Legacy compatibility: tests + the legacy #201 envelope sent
    ``effect: "ALLOW"`` (uppercase); #212 sends ``effect: "allow"``
    (lowercase per the new schema). The SDK normalises by upper-casing
    once on entry so the dispatch table stays case-stable across both
    shapes. Forward-compat: extras are preserved as ``_raw`` for
    logging / future routing (B2's ``REQUIRE_DEFERRED_REVIEW`` will
    consume the same envelope).
    """
    effect = str(body.get("effect") or "").upper()
    return {
        "effect": effect,
        "reason": body.get("reason") or "",
        "reason_detail": body.get("reason_detail") or None,
        "citation": body.get("citation") or "",
        "gate_name": body.get("gate_name") or "",
        "review_id": body.get("review_id"),
        "fix_url": body.get("fix_url"),
        "required_role": body.get("required_role"),
        "expected_resolution": body.get("expected_resolution"),
        "webhook_url": body.get("webhook_url"),
        "retryable": bool(body.get("retryable", False)),
        "_raw": body,
    }


def _is_pydantic_validation_envelope(body: Any) -> bool:
    """Return True when the response body looks like FastAPI's default 422.

    FastAPI's auto-generated 422 carries
    ``{"detail": [{"loc": [...], "msg": ..., "type": ...}, ...]}``.
    The backend's domain errors (the Phase 1 ``code``-tagged 422s) wrap
    differently — they emit ``{"code": "tenant_malformed", "detail": ...}``
    with a string detail. We only want to surface the version-skew
    error when the body looks like the pydantic envelope AND there's
    no recognised ``code`` to dispatch on. Wave 2B PR B1.
    """
    if not isinstance(body, dict):
        return False
    detail = body.get("detail")
    if not isinstance(detail, list) or not detail:
        return False
    first = detail[0]
    if not isinstance(first, dict):
        return False
    # FastAPI's validation entries always carry ``loc`` + ``msg``.
    return "loc" in first and "msg" in first


def _raise_wire_shape_mismatch_422(resp: Any, body: Any) -> None:
    """Raise an actionable ``VeraClientError`` on a 422 wire-shape mismatch.

    Hits when a pydantic validation failure on ``GateEvaluateRequest``
    surfaces with no recognised ``code`` — i.e. the SDK shipped a body
    the backend doesn't accept. The default ``VeraValidationError`` copy
    ("Server returned 4xx") is too generic for the SDK/backend version
    skew case, which is the one operationally common cause. Point the
    operator at the SDK version pin / backend upgrade path explicitly.
    Wave 2B PR B1.
    """
    rid = None
    try:
        rid = resp.headers.get("X-Request-ID") or resp.headers.get("x-request-id")
    except Exception:
        pass
    detail_repr = repr(body.get("detail") if isinstance(body, dict) else body)[:500]
    raise VeraClientError(
        message=(
            f"POST {GATE_EVALUATE_PATH} returned 422 (request shape rejected). "
            "Likely SDK / backend version skew — the SDK is sending the new "
            "GateEvaluateRequest body shape but the backend rejected one or "
            "more fields. Upgrade the backend to the release that shipped "
            "the Wave 2A gate-evaluate contract (PR #212), or pin the SDK "
            "to the last pre-1.0.1 release if a backend upgrade is not "
            "possible. See "
            "https://docs.usevera.xyz/sdk/version-compat for the compatibility "
            "matrix."
        ),
        status_code=422,
        request_id=rid,
        user_facing_reason=(
            "Vera could not evaluate this action because the request did not "
            "match the server's expected shape. Please contact support if "
            "this persists."
        ),
        developer_reason=(
            f"422 from {GATE_EVALUATE_PATH}; pydantic detail: {detail_repr}"
        ),
        fix_url="https://docs.usevera.xyz/sdk/version-compat",
    )


def _maybe_raise_version_skew(resp: Any) -> None:
    """If the 422 is a pydantic envelope without a known ``code``, raise version-skew."""
    try:
        body = resp.json()
    except ValueError:
        return  # non-JSON 422 — let wrap_httpx_error handle it generically.
    # If the body has a ``code`` mapped to a branded SDK error, defer
    # to wrap_httpx_error so domain exceptions keep their behaviour
    # (TenantMissingOrInvalid, PolicyBlock, etc.).
    if isinstance(body, dict) and isinstance(body.get("code"), str):
        from .errors import CODE_TO_ERROR_CLASS

        if body["code"] in CODE_TO_ERROR_CLASS:
            return
    if _is_pydantic_validation_envelope(body):
        _raise_wire_shape_mismatch_422(resp, body)


def _call_evaluate_sync(client: Any, body: dict) -> Optional[dict]:
    """POST ``/v1/gates/evaluate``. Returns parsed ruling, or ``None`` for 404.

    Raises whatever ``wrap_httpx_error`` produces on non-404 failures
    (``PolicyBlock`` / ``PendingReview`` / ``VeraAuthError`` / etc) so
    backend-emitted error envelopes surface as branded exceptions per
    the existing transport-layer contract. 422 responses that look
    like a pydantic validation failure with no recognised ``code``
    take a dedicated B1 path: they raise a ``VeraClientError`` with
    actionable version-skew copy instead of the generic validation
    error.

    The 404 fallback is the Phase 1 / Phase 2 bridge: the backend
    endpoint doesn't exist yet, so the SDK ships with the decorator
    auto-degrading to audit-only capture. When Phase 2 lands the
    endpoint, this branch stops firing without an SDK release.
    """
    import httpx

    from .client import wrap_httpx_error

    try:
        resp = client._client.post(GATE_EVALUATE_PATH, json=body)
    except httpx.HTTPError as exc:
        wrapped = wrap_httpx_error(exc)
        if isinstance(wrapped, Exception) and wrapped is not exc:
            raise wrapped from exc
        raise

    if resp.status_code == 404:
        return None
    if resp.status_code == 422:
        # Inspect the body BEFORE handing off to wrap_httpx_error so
        # we can surface the version-skew message when the 422 is a
        # pydantic envelope without a known code. Raises on match.
        _maybe_raise_version_skew(resp)
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        wrapped = wrap_httpx_error(exc)
        if isinstance(wrapped, Exception) and wrapped is not exc:
            raise wrapped from exc
        raise
    try:
        return _parse_ruling(resp.json())
    except ValueError:
        # Server returned non-JSON 200 — treat as ALLOW with WARN so
        # the customer's action isn't blocked by a malformed backend.
        logger.warning(
            "vera.gate: %s returned non-JSON body; treating as ALLOW.",
            GATE_EVALUATE_PATH,
        )
        return {"effect": _RULING_ALLOW, "_raw": {}}


async def _call_evaluate_async(client: Any, body: dict) -> Optional[dict]:
    """Async variant of :func:`_call_evaluate_sync`.

    Works against either :class:`AsyncVeraClient` or the sync
    :class:`VeraClient` (the latter via ``asyncio.to_thread`` so we
    don't block the event loop on a sync httpx call inside an async
    decorator). Detected by checking for an ``async``-shaped post on
    the inner httpx client.
    """
    import httpx

    from .client import wrap_httpx_error

    inner = getattr(client, "_client", None)
    post = getattr(inner, "post", None) if inner is not None else None

    if inspect.iscoroutinefunction(post):
        try:
            resp = await post(GATE_EVALUATE_PATH, json=body)
        except httpx.HTTPError as exc:
            wrapped = wrap_httpx_error(exc)
            if isinstance(wrapped, Exception) and wrapped is not exc:
                raise wrapped from exc
            raise
    else:
        # Sync client inside an async decorator — push the blocking
        # call onto a worker thread so we don't stall the event loop.
        try:
            resp = await asyncio.to_thread(
                inner.post, GATE_EVALUATE_PATH, json=body
            )
        except httpx.HTTPError as exc:
            wrapped = wrap_httpx_error(exc)
            if isinstance(wrapped, Exception) and wrapped is not exc:
                raise wrapped from exc
            raise

    if resp.status_code == 404:
        return None
    if resp.status_code == 422:
        _maybe_raise_version_skew(resp)
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        wrapped = wrap_httpx_error(exc)
        if isinstance(wrapped, Exception) and wrapped is not exc:
            raise wrapped from exc
        raise
    try:
        return _parse_ruling(resp.json())
    except ValueError:
        logger.warning(
            "vera.gate: %s returned non-JSON body; treating as ALLOW.",
            GATE_EVALUATE_PATH,
        )
        return {"effect": _RULING_ALLOW, "_raw": {}}


def _build_pending_review(ruling: dict) -> PendingReview:
    """Construct a :class:`PendingReview` from a parsed REQUIRE_HITL ruling.

    The new B1 attributes (``gate_name``, ``reason``, ``reason_detail``,
    ``citation``) are populated from the Ruling envelope. ``reason_detail``
    runs through :func:`_safe_reason_detail` first so any PHI-shaped
    string the backend ever leaked is replaced with a sentinel before
    reaching the customer's ``except`` handler.
    """
    return PendingReview(
        review_id=ruling.get("review_id") or "",
        expected_resolution=ruling.get("expected_resolution"),
        webhook_url=ruling.get("webhook_url"),
        required_role=ruling.get("required_role"),
        fix_url=ruling.get("fix_url"),
        gate_name=ruling.get("gate_name") or "",
        reason=ruling.get("reason") or "",
        reason_detail=_safe_reason_detail(ruling.get("reason_detail")),
        citation=ruling.get("citation") or None,
    )


def _build_requires_deferred_review(ruling: dict) -> RequiresDeferredReview:
    """Construct a :class:`RequiresDeferredReview` from a parsed ruling.

    Used by the ``realtime=True`` routing branch (REQUIRE_HITL on a
    realtime call site) and by the forward-compat
    ``REQUIRE_DEFERRED_REVIEW`` wire-effect path. Surfaces the same
    Ruling metadata as :class:`PendingReview` so customer code can
    route uniformly on either exception. ``reason_detail`` runs
    through :func:`_safe_reason_detail` first so any PHI-shaped
    string is redacted at the boundary. Wave 2C PR B2.
    """
    return RequiresDeferredReview(
        review_id=ruling.get("review_id") or "",
        fix_url=ruling.get("fix_url"),
        required_role=ruling.get("required_role"),
        gate_name=ruling.get("gate_name") or "",
        reason=ruling.get("reason") or "",
        reason_detail=_safe_reason_detail(ruling.get("reason_detail")),
        citation=ruling.get("citation") or None,
        expected_resolution=ruling.get("expected_resolution"),
        webhook_url=ruling.get("webhook_url"),
    )


def _build_policy_block(ruling: dict) -> PolicyBlock:
    """Construct a :class:`PolicyBlock` from a parsed BLOCK ruling.

    The new B1 attributes (``gate_name``, ``reason_detail``,
    ``required_role``) are populated from the Ruling envelope.
    ``reason_detail`` runs through :func:`_safe_reason_detail` first
    so any PHI-shaped string is redacted at the boundary.
    """
    return PolicyBlock(
        reason=ruling.get("reason") or "Gate evaluation returned BLOCK.",
        citation=ruling.get("citation") or "",
        fix_url=ruling.get("fix_url"),
        retryable=ruling.get("retryable", False),
        gate_name=ruling.get("gate_name") or "",
        reason_detail=_safe_reason_detail(ruling.get("reason_detail")),
        required_role=ruling.get("required_role"),
    )


# ---------------------------------------------------------------------------
# Sync wrapper internals.
# ---------------------------------------------------------------------------


def _sync_call(
    func: Callable[..., Any],
    args: tuple,
    kwargs: dict,
    *,
    action_class: str,
    action_type: str,
    tenant: Optional[str],
    agent_type: Optional[str],
    redactor: Optional[Redactor],
    realtime: bool,
    client: Any,
    # Wave 2B PR B1 — optional GateEvaluateRequest passthroughs.
    agent_id: Optional[str] = None,
    action_description: Optional[str] = None,
    data_subject_id: Optional[str] = None,
    target_system: Optional[str] = None,
    target_resource: Optional[str] = None,
) -> Any:
    """Shared sync invocation path used by :func:`gate`.

    Resolves tenant + agent_type, calls evaluate (unless bypassed or
    no client), routes the ruling, captures the action, raises the
    appropriate domain error. Same flow used by the async wrapper
    after it does its own ``await`` of the evaluate POST.

    ``realtime=True`` (Wave 2C PR B2) changes the routing of
    ``REQUIRE_HITL`` rulings only:

    * default — invoke the wrapped function for a draft, capture as
      ``pending_review``, raise :class:`PendingReview` ("block and
      wait" pattern; caller surfaces the draft and polls).
    * ``realtime=True`` — do NOT invoke the wrapped function, capture
      as ``pending_review`` with ``realtime=True`` stamped onto the
      metadata, raise :class:`RequiresDeferredReview` ("queue and
      continue" pattern; caller queues the action into a customer-side
      deferred-execution store and resumes on the ``review.completed``
      webhook).

    ``ALLOW`` and ``BLOCK`` rulings are unchanged regardless of the
    ``realtime`` flag — BLOCK is always immediate, and ALLOW is always
    invoke+capture.
    """
    from .decorator import (
        _default_redactor,
        _warn_empty_client_once,
    )

    effective_client = _resolve_client(client)
    if effective_client is None:
        # No client configured — exactly mirror the legacy ``@vera.audit``
        # contract: warn once and run the function. We intentionally do
        # NOT raise here even though gate semantics theoretically can't
        # be enforced — the customer's code must continue to work when
        # observability isn't configured (this is the same invariant
        # the legacy decorator established).
        _warn_empty_client_once()
        return func(*args, **kwargs)

    effective_redactor = redactor if redactor is not None else _default_redactor
    resolved_action_name = action_class or func.__name__
    input_data = effective_redactor.serialize_args(args, kwargs)

    # Resolve tenant — explicit kwarg > context manager > middleware >
    # default. Malformed explicit kwarg raises TenantMissingOrInvalid
    # (programmer error). Missing-everywhere raises the same — gate
    # semantics REQUIRE a tenant because the backend's policy lookup
    # is tenant-scoped.
    tenant_id, tenant_source = resolve_tenant(explicit=tenant)
    resolved_agent_type = resolve_agent_type(explicit=agent_type)

    start = time.perf_counter()

    # Bypass path: skip the backend, treat as ALLOW. Still capture so
    # the audit trail records the call (matters for tests that inspect
    # captured records).
    if is_bypassing_gates():
        return _invoke_and_capture_allow(
            func,
            args,
            kwargs,
            effective_client=effective_client,
            effective_redactor=effective_redactor,
            resolved_action_name=resolved_action_name,
            action_type=action_type,
            input_data=input_data,
            tenant_id=tenant_id,
            agent_type=resolved_agent_type,
            start=start,
            ruling_effect=_RULING_ALLOW,
        )

    body = _build_evaluate_request(
        action_class=resolved_action_name,
        action_type=action_type,
        tenant_id=tenant_id,
        tenant_source=tenant_source,
        agent_name=getattr(effective_client, "agent_name", "") or "",
        agent_id=agent_id,
        agent_type=resolved_agent_type,
        authorized_by=_short_key_hint(_client_api_key(effective_client)),
        input_data=input_data,
        data_subject_id=data_subject_id,
        target_system=target_system,
        target_resource=target_resource,
        action_description=action_description,
    )
    ruling = _call_evaluate_sync(effective_client, body)

    # 404 fallback — backend doesn't ship /v1/gates/evaluate yet. Warn
    # once and degrade to audit-only capture (legacy ``@vera.audit``
    # semantics). Auto-graduates to full gate semantics when Phase 2
    # backend lands.
    if ruling is None:
        _warn_evaluate_404_once()
        return _invoke_and_capture_allow(
            func,
            args,
            kwargs,
            effective_client=effective_client,
            effective_redactor=effective_redactor,
            resolved_action_name=resolved_action_name,
            action_type=action_type,
            input_data=input_data,
            tenant_id=tenant_id,
            agent_type=resolved_agent_type,
            start=start,
            ruling_effect=None,
        )

    effect = ruling["effect"]

    if effect == _RULING_BLOCK:
        # Do NOT invoke the wrapped function. The capture still happens
        # so the audit trail records that the call was attempted +
        # blocked (compliance invariant: "no silent denials").
        _capture_action(
            effective_client,
            action_name=resolved_action_name,
            action_type=action_type,
            result="blocked",
            input_data=input_data,
            outcome={"ruling": ruling.get("_raw") or {}},
            duration_ms=int((time.perf_counter() - start) * 1000),
            error_message=ruling.get("reason") or "",
            tenant_id=tenant_id,
            agent_type=resolved_agent_type,
            ruling_effect=_RULING_BLOCK,
        )
        raise _build_policy_block(ruling)

    if effect == _RULING_REQUIRE_HITL:
        if realtime:
            # B2 — "queue and continue" semantics. Do NOT invoke the
            # wrapped function; the customer's deferred-execution store
            # will execute it once the review.completed webhook fires.
            # Capturing the attempt is still mandatory (the audit trail
            # MUST record that a HITL gate fired on this call site, with
            # the realtime=True provenance so it's distinguishable from
            # the default sync-PendingReview path in the ledger).
            _capture_action(
                effective_client,
                action_name=resolved_action_name,
                action_type=action_type,
                result="pending_review",
                input_data=input_data,
                outcome={
                    "ruling": ruling.get("_raw") or {},
                    "realtime": True,
                },
                duration_ms=int((time.perf_counter() - start) * 1000),
                error_message=None,
                tenant_id=tenant_id,
                agent_type=resolved_agent_type,
                review_id=ruling.get("review_id"),
                ruling_effect=_RULING_REQUIRE_HITL,
            )
            raise _build_requires_deferred_review(ruling)

        # Default (realtime=False) — invoke for draft, capture, then
        # raise. The capture MUST happen before the raise so a caller
        # whose handler swallows PendingReview still has the draft in
        # the audit trail.
        try:
            result_value = func(*args, **kwargs)
        except Exception as exc:
            _capture_failure(
                effective_client,
                effective_redactor,
                resolved_action_name=resolved_action_name,
                action_type=action_type,
                input_data=input_data,
                exc=exc,
                duration_ms=int((time.perf_counter() - start) * 1000),
                tenant_id=tenant_id,
                agent_type=resolved_agent_type,
                ruling_effect=_RULING_REQUIRE_HITL,
            )
            raise
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        _capture_action(
            effective_client,
            action_name=resolved_action_name,
            action_type=action_type,
            result="pending_review",
            input_data=input_data,
            outcome={"return_value": effective_redactor.serialize(result_value)},
            duration_ms=elapsed_ms,
            error_message=None,
            tenant_id=tenant_id,
            agent_type=resolved_agent_type,
            review_id=ruling.get("review_id"),
            ruling_effect=_RULING_REQUIRE_HITL,
        )
        raise _build_pending_review(ruling)

    if effect == _RULING_REQUIRE_DEFERRED_REVIEW:
        # Wire-level ``REQUIRE_DEFERRED_REVIEW`` effect — always a
        # "queue and continue" decision regardless of the call site's
        # ``realtime`` flag (the backend is asserting that this gate's
        # policy is deferred-review by design, not the caller's choice).
        # Do NOT invoke the wrapped function; raise
        # RequiresDeferredReview so the customer's deferred-execution
        # store can handle it.
        _capture_action(
            effective_client,
            action_name=resolved_action_name,
            action_type=action_type,
            result="pending_review",
            input_data=input_data,
            outcome={
                "ruling": ruling.get("_raw") or {},
                "deferred_review_wire_effect": True,
            },
            duration_ms=int((time.perf_counter() - start) * 1000),
            error_message=None,
            tenant_id=tenant_id,
            agent_type=resolved_agent_type,
            review_id=ruling.get("review_id"),
            ruling_effect=_RULING_REQUIRE_DEFERRED_REVIEW,
        )
        raise _build_requires_deferred_review(ruling)

    if effect not in _KNOWN_RULINGS:
        _warn_unknown_ruling_once(effect)
    # ALLOW path (and unknown-ruling fall-through).
    return _invoke_and_capture_allow(
        func,
        args,
        kwargs,
        effective_client=effective_client,
        effective_redactor=effective_redactor,
        resolved_action_name=resolved_action_name,
        action_type=action_type,
        input_data=input_data,
        tenant_id=tenant_id,
        agent_type=resolved_agent_type,
        start=start,
        ruling_effect=effect or _RULING_ALLOW,
    )


def _invoke_and_capture_allow(
    func: Callable[..., Any],
    args: tuple,
    kwargs: dict,
    *,
    effective_client: Any,
    effective_redactor: Redactor,
    resolved_action_name: str,
    action_type: str,
    input_data: Any,
    tenant_id: str,
    agent_type: Optional[str],
    start: float,
    ruling_effect: Optional[str],
) -> Any:
    """Invoke the wrapped function for ALLOW / bypass / 404-fallback paths.

    Mirrors the legacy ``@vera.audit`` success/failure capture exactly
    so the on-wire shape is identical between the alias and the new
    decorator.
    """
    try:
        result_value = func(*args, **kwargs)
    except Exception as exc:
        _capture_failure(
            effective_client,
            effective_redactor,
            resolved_action_name=resolved_action_name,
            action_type=action_type,
            input_data=input_data,
            exc=exc,
            duration_ms=int((time.perf_counter() - start) * 1000),
            tenant_id=tenant_id,
            agent_type=agent_type,
            ruling_effect=ruling_effect,
        )
        raise
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    _capture_action(
        effective_client,
        action_name=resolved_action_name,
        action_type=action_type,
        result="success",
        input_data=input_data,
        outcome={"return_value": effective_redactor.serialize(result_value)},
        duration_ms=elapsed_ms,
        error_message=None,
        tenant_id=tenant_id,
        agent_type=agent_type,
        ruling_effect=ruling_effect,
    )
    return result_value


def _capture_failure(
    client: Any,
    redactor: Redactor,
    *,
    resolved_action_name: str,
    action_type: str,
    input_data: Any,
    exc: BaseException,
    duration_ms: int,
    tenant_id: str,
    agent_type: Optional[str],
    ruling_effect: Optional[str],
) -> None:
    """Capture a failure record without ever masking the customer's exception."""
    try:
        _capture_action(
            client,
            action_name=resolved_action_name,
            action_type=action_type,
            result="failure",
            input_data=input_data,
            outcome={"traceback": redactor.serialize(traceback.format_exc())},
            duration_ms=duration_ms,
            error_message=str(exc),
            tenant_id=tenant_id,
            agent_type=agent_type,
            ruling_effect=ruling_effect,
        )
    except Exception as audit_exc:  # noqa: BLE001
        logger.warning(
            "vera.gate: failed to capture failure record for %s: %s",
            resolved_action_name,
            audit_exc,
        )


# ---------------------------------------------------------------------------
# Async wrapper internals.
# ---------------------------------------------------------------------------


async def _async_call(
    func: Callable[..., Any],
    args: tuple,
    kwargs: dict,
    *,
    action_class: str,
    action_type: str,
    tenant: Optional[str],
    agent_type: Optional[str],
    redactor: Optional[Redactor],
    realtime: bool,
    client: Any,
    # Wave 2B PR B1 — optional GateEvaluateRequest passthroughs.
    agent_id: Optional[str] = None,
    action_description: Optional[str] = None,
    data_subject_id: Optional[str] = None,
    target_system: Optional[str] = None,
    target_resource: Optional[str] = None,
) -> Any:
    """Async sibling of :func:`_sync_call`.

    Wraps an async function. The shape mirrors the sync version
    closely so backward-compat / capture invariants are obvious side
    by side; the only difference is ``await``\\ s on the wrapped
    function and the evaluate call. ``realtime=True`` routing is
    identical to the sync path — see :func:`_sync_call` for the
    "queue and continue" vs "block and wait" rationale.
    """
    from .decorator import (
        _default_redactor,
        _warn_empty_client_once,
    )

    effective_client = _resolve_client(client, async_preferred=True)
    if effective_client is None:
        _warn_empty_client_once()
        return await func(*args, **kwargs)

    effective_redactor = redactor if redactor is not None else _default_redactor
    resolved_action_name = action_class or func.__name__
    input_data = effective_redactor.serialize_args(args, kwargs)
    tenant_id, tenant_source = resolve_tenant(explicit=tenant)
    resolved_agent_type = resolve_agent_type(explicit=agent_type)

    start = time.perf_counter()

    if is_bypassing_gates():
        return await _async_invoke_and_capture_allow(
            func,
            args,
            kwargs,
            effective_client=effective_client,
            effective_redactor=effective_redactor,
            resolved_action_name=resolved_action_name,
            action_type=action_type,
            input_data=input_data,
            tenant_id=tenant_id,
            agent_type=resolved_agent_type,
            start=start,
            ruling_effect=_RULING_ALLOW,
        )

    body = _build_evaluate_request(
        action_class=resolved_action_name,
        action_type=action_type,
        tenant_id=tenant_id,
        tenant_source=tenant_source,
        agent_name=getattr(effective_client, "agent_name", "") or "",
        agent_id=agent_id,
        agent_type=resolved_agent_type,
        authorized_by=_short_key_hint(_client_api_key(effective_client)),
        input_data=input_data,
        data_subject_id=data_subject_id,
        target_system=target_system,
        target_resource=target_resource,
        action_description=action_description,
    )
    ruling = await _call_evaluate_async(effective_client, body)

    if ruling is None:
        _warn_evaluate_404_once()
        return await _async_invoke_and_capture_allow(
            func,
            args,
            kwargs,
            effective_client=effective_client,
            effective_redactor=effective_redactor,
            resolved_action_name=resolved_action_name,
            action_type=action_type,
            input_data=input_data,
            tenant_id=tenant_id,
            agent_type=resolved_agent_type,
            start=start,
            ruling_effect=None,
        )

    effect = ruling["effect"]

    if effect == _RULING_BLOCK:
        _capture_action(
            effective_client,
            action_name=resolved_action_name,
            action_type=action_type,
            result="blocked",
            input_data=input_data,
            outcome={"ruling": ruling.get("_raw") or {}},
            duration_ms=int((time.perf_counter() - start) * 1000),
            error_message=ruling.get("reason") or "",
            tenant_id=tenant_id,
            agent_type=resolved_agent_type,
            ruling_effect=_RULING_BLOCK,
        )
        raise _build_policy_block(ruling)

    if effect == _RULING_REQUIRE_HITL:
        if realtime:
            # See _sync_call B2 branch for the rationale — async
            # mirror of the "queue and continue" semantics.
            _capture_action(
                effective_client,
                action_name=resolved_action_name,
                action_type=action_type,
                result="pending_review",
                input_data=input_data,
                outcome={
                    "ruling": ruling.get("_raw") or {},
                    "realtime": True,
                },
                duration_ms=int((time.perf_counter() - start) * 1000),
                error_message=None,
                tenant_id=tenant_id,
                agent_type=resolved_agent_type,
                review_id=ruling.get("review_id"),
                ruling_effect=_RULING_REQUIRE_HITL,
            )
            raise _build_requires_deferred_review(ruling)

        try:
            result_value = await func(*args, **kwargs)
        except Exception as exc:
            _capture_failure(
                effective_client,
                effective_redactor,
                resolved_action_name=resolved_action_name,
                action_type=action_type,
                input_data=input_data,
                exc=exc,
                duration_ms=int((time.perf_counter() - start) * 1000),
                tenant_id=tenant_id,
                agent_type=resolved_agent_type,
                ruling_effect=_RULING_REQUIRE_HITL,
            )
            raise
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        _capture_action(
            effective_client,
            action_name=resolved_action_name,
            action_type=action_type,
            result="pending_review",
            input_data=input_data,
            outcome={"return_value": effective_redactor.serialize(result_value)},
            duration_ms=elapsed_ms,
            error_message=None,
            tenant_id=tenant_id,
            agent_type=resolved_agent_type,
            review_id=ruling.get("review_id"),
            ruling_effect=_RULING_REQUIRE_HITL,
        )
        raise _build_pending_review(ruling)

    if effect == _RULING_REQUIRE_DEFERRED_REVIEW:
        # See _sync_call — wire-level REQUIRE_DEFERRED_REVIEW is always
        # a queue-and-continue decision regardless of the realtime flag.
        _capture_action(
            effective_client,
            action_name=resolved_action_name,
            action_type=action_type,
            result="pending_review",
            input_data=input_data,
            outcome={
                "ruling": ruling.get("_raw") or {},
                "deferred_review_wire_effect": True,
            },
            duration_ms=int((time.perf_counter() - start) * 1000),
            error_message=None,
            tenant_id=tenant_id,
            agent_type=resolved_agent_type,
            review_id=ruling.get("review_id"),
            ruling_effect=_RULING_REQUIRE_DEFERRED_REVIEW,
        )
        raise _build_requires_deferred_review(ruling)

    if effect not in _KNOWN_RULINGS:
        _warn_unknown_ruling_once(effect)
    return await _async_invoke_and_capture_allow(
        func,
        args,
        kwargs,
        effective_client=effective_client,
        effective_redactor=effective_redactor,
        resolved_action_name=resolved_action_name,
        action_type=action_type,
        input_data=input_data,
        tenant_id=tenant_id,
        agent_type=resolved_agent_type,
        start=start,
        ruling_effect=effect or _RULING_ALLOW,
    )


async def _async_invoke_and_capture_allow(
    func: Callable[..., Any],
    args: tuple,
    kwargs: dict,
    *,
    effective_client: Any,
    effective_redactor: Redactor,
    resolved_action_name: str,
    action_type: str,
    input_data: Any,
    tenant_id: str,
    agent_type: Optional[str],
    start: float,
    ruling_effect: Optional[str],
) -> Any:
    """Async invoke + capture for ALLOW / bypass / 404-fallback paths."""
    try:
        result_value = await func(*args, **kwargs)
    except Exception as exc:
        _capture_failure(
            effective_client,
            effective_redactor,
            resolved_action_name=resolved_action_name,
            action_type=action_type,
            input_data=input_data,
            exc=exc,
            duration_ms=int((time.perf_counter() - start) * 1000),
            tenant_id=tenant_id,
            agent_type=agent_type,
            ruling_effect=ruling_effect,
        )
        raise
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    _capture_action(
        effective_client,
        action_name=resolved_action_name,
        action_type=action_type,
        result="success",
        input_data=input_data,
        outcome={"return_value": effective_redactor.serialize(result_value)},
        duration_ms=elapsed_ms,
        error_message=None,
        tenant_id=tenant_id,
        agent_type=agent_type,
        ruling_effect=ruling_effect,
    )
    return result_value


# ---------------------------------------------------------------------------
# Public decorator factory.
# ---------------------------------------------------------------------------


def gate(
    action_class: str = "",
    *,
    action_type: str = "function_call",
    tenant: Optional[str] = None,
    agent_type: Optional[str] = None,
    redactor: Optional[Redactor] = None,
    realtime: bool = False,
    client: Any = None,
    # --- Wave 2B PR B1 — optional GateEvaluateRequest passthroughs.
    # All None by default; emitted on the wire only when set, so
    # the wire shape stays minimal for callers that don't need them.
    agent_id: Optional[str] = None,
    action_description: Optional[str] = None,
    data_subject_id: Optional[str] = None,
    target_system: Optional[str] = None,
    target_resource: Optional[str] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """The v1 ``@vera.gate`` primitive — wrap an agent action with policy enforcement.

    Synchronous sibling of ``async_gate``; the same factory handles
    both — ``inspect.iscoroutinefunction`` picks the right wrapper at
    decoration time.

    Args:
        action_class: Canonical action taxonomy entry (e.g.
            ``"chart_note_finalize"``, ``"loan_approve"``). Backend
            uses this to look up the policy. Defaults to the wrapped
            function's ``__name__`` when empty.
        action_type: Backwards-compat with ``@vera.audit``'s
            ``action_type`` field; preserved on the ActionRecord.
        tenant: Explicit ``tenant_id`` for this call site. Wins over
            the context manager / middleware / default. ``None`` (the
            default) consults the resolver.
        agent_type: Explicit agent type for this call site (e.g.
            ``"clinical_summarizer"``, ``"underwriter"``). Wins over
            ``vera.init(agent_type=...)``. ``None`` consults the
            global.
        redactor: Per-decorator redaction policy override.
        realtime: When True, ``REQUIRE_HITL`` rulings raise
            :class:`vera.errors.RequiresDeferredReview` instead of
            :class:`vera.errors.PendingReview` and the wrapped function
            is NOT invoked — caller is expected to queue the action
            into a customer-side deferred-execution store and resume
            on the ``review.completed`` webhook. ``ALLOW`` and
            ``BLOCK`` rulings are unchanged. Wave 2C PR B2.
        client: Explicit client override. Defaults to the
            module-level default registered by ``vera.init``.
        agent_id: Optional stable identifier for this specific agent
            instance (vs. ``client.agent_name`` which identifies the
            agent class). Forwarded to the backend's
            ``GateEvaluateRequest.agent_id``. ``None`` to omit.
        action_description: Human-readable description of the action
            for the audit ledger (e.g. ``"Commit chart note draft to
            EHR"``). ``None`` to omit. Wave 2B PR B1.
        data_subject_id: Identifier of the data subject the action
            targets (e.g. patient ID, applicant ID). Lets the backend's
            policy lookup scope on the affected party. ``None`` to omit.
        target_system: System the action will affect (e.g. ``"EHR"``,
            ``"LOS"``, ``"CRM"``). ``None`` to omit.
        target_resource: Specific resource handle within
            ``target_system`` (e.g. ``"encounter:789"``,
            ``"application:abc"``). ``None`` to omit.

    Routing (when the backend ``/v1/gates/evaluate`` endpoint exists):

    * ``ALLOW`` → invoke the wrapped function, capture as
      ActionRecord, return the result.
    * ``REQUIRE_HITL`` → invoke for draft, capture, raise
      :class:`PendingReview`.
    * ``BLOCK`` → do NOT invoke, raise :class:`PolicyBlock`.

    When the endpoint returns 404 (Phase 1 — backend not yet shipped):
    fall back to audit-only capture with a once-per-process
    ``UserWarning``. Auto-activates full gate semantics when Phase 2
    lands; no SDK release required.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                return await _async_call(
                    func,
                    args,
                    kwargs,
                    action_class=action_class,
                    action_type=action_type,
                    tenant=tenant,
                    agent_type=agent_type,
                    redactor=redactor,
                    realtime=realtime,
                    client=client,
                    agent_id=agent_id,
                    action_description=action_description,
                    data_subject_id=data_subject_id,
                    target_system=target_system,
                    target_resource=target_resource,
                )

            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            return _sync_call(
                func,
                args,
                kwargs,
                action_class=action_class,
                action_type=action_type,
                tenant=tenant,
                agent_type=agent_type,
                redactor=redactor,
                realtime=realtime,
                client=client,
                agent_id=agent_id,
                action_description=action_description,
                data_subject_id=data_subject_id,
                target_system=target_system,
                target_resource=target_resource,
            )

        return sync_wrapper

    return decorator


__all__ = [
    "gate",
    "is_bypassing_gates",
    "GATE_EVALUATE_PATH",
]
