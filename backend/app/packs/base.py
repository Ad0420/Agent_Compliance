"""Phase 2 Wave 2B — gate-pack base types.

Three small types make up the pack contract:

* ``GateContext`` — read-only bundle passed to every gate. Carries the
  ``AsyncSession`` (gates that need DB access — e.g. ``StaleBaaGate``
  — pull state from here), the org id, and the proposed-action
  ``GateEvaluateRequest`` payload. ``frozen=True`` because gates must
  not mutate the request — strictest-wins reduction relies on every
  gate seeing the same input.

* ``Gate`` — runtime-checkable Protocol. Every gate exposes a ``name``
  (used as the gate_name in the resulting ``Ruling`` and as the
  tie-breaker in the reducer), a synchronous ``applies(ctx)`` predicate
  for cheap early-exit, and an async ``evaluate(ctx)`` that returns a
  ``Ruling``. Protocol over ABC: gates don't share implementation, and
  ``runtime_checkable`` lets tests assert membership without inheritance.

* ``GatePack`` — ordered container of gates. The tuple order is the
  documented evaluation order AND the reducer's tie-breaker (first in
  pack wins same-effect ties). See ``app.services.gates.reducer`` for
  the strictest-wins reduction.

PR scope guard: no ``GatePack.register`` / dynamic discovery — the
evaluator wires the single ``CLINICAL_SCRIBE_PACK`` constant directly.
A multi-pack registry lands in a later wave when a second vertical is
on the roadmap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas.gate import GateEvaluateRequest, Ruling


@dataclass(frozen=True)
class GateContext:
    """Read-only context passed to every gate's ``applies`` / ``evaluate``.

    ``frozen=True`` so gates can't accidentally mutate the request mid-
    pack — strictest-wins reduction depends on every gate seeing the
    same payload. The ``AsyncSession`` is mutable by nature (it owns
    DB connections), but gates are expected to use it read-only; the
    evaluator owns any write side-effects (e.g. materializing an
    ``Approval`` row on ``REQUIRE_HITL``).
    """

    session: AsyncSession
    org_id: str
    request: GateEvaluateRequest


@runtime_checkable
class Gate(Protocol):
    """One gate. Stateless. Cheap to construct. Re-entrant.

    Gates are instantiated once at module import time (see each pack's
    ``pack.py``) and reused across requests. Concrete gates therefore
    must not hold per-request state on ``self``. All per-request state
    lives on ``GateContext``.

    Protocol shape (NOT ABC) so tests can synthesise lightweight fakes
    via ``types.SimpleNamespace`` or small dataclasses without inheriting
    from a base class. ``runtime_checkable`` lets the pack constructor
    assert membership cheaply at import time.
    """

    name: str

    def applies(self, ctx: GateContext) -> bool:  # pragma: no cover - protocol
        """Cheap predicate: should this gate evaluate this request at all?

        Pure, synchronous, no DB. Lets the evaluator skip a gate without
        paying its async setup cost when the action shape is obviously
        out of scope (e.g. ``NewDiagnosisGate.applies`` returns False
        for a `get_patient_summary` action).

        ``StaleBaaGate.applies`` always returns True — BAA freshness is
        action-agnostic.
        """

    async def evaluate(self, ctx: GateContext) -> Ruling:  # pragma: no cover
        """Produce a ``Ruling`` for this request.

        Called only when ``applies(ctx)`` returned True. Free to query
        the DB via ``ctx.session`` and to call sibling services
        (``is_org_baa_active`` etc). Must NOT mutate the request, write
        ``Approval`` rows, or dispatch webhooks — those side effects
        belong to the evaluator's HITL materializer.
        """


@dataclass(frozen=True)
class GatePack:
    """Ordered, named bundle of ``Gate`` instances.

    The ``gates`` tuple order is significant in two ways:

    1. **Evaluation order.** The evaluator iterates left-to-right so the
       cheapest / most-often-BLOCKing gate runs first. For
       ``CLINICAL_SCRIBE_PACK`` that is ``StaleBaaGate`` — a single
       cached call that BLOCKs the whole pack when an org has no BAA,
       sparing PHI-adjacent scans on payloads we'd refuse anyway.

    2. **Reducer tie-breaker.** When two gates produce the same effect
       (e.g. two ``BLOCK`` rulings), the strictest-wins reducer breaks
       the tie by first-in-pack-order. See
       ``app.services.gates.reducer.reduce_rulings``. This makes the
       reducer's output deterministic and debuggable: the same input
       always picks the same gate's ruling.
    """

    name: str
    gates: tuple[Gate, ...]

    def __post_init__(self) -> None:
        # Assert at construction time so a pack with a non-Gate-shaped
        # instance fails at import rather than at the first request that
        # hits the bad gate. ``runtime_checkable`` Protocol membership
        # is structural — duck-typing checked by hasattr — so this is
        # essentially "every entry has .name, .applies, .evaluate".
        for g in self.gates:
            if not isinstance(g, Gate):
                raise TypeError(
                    f"GatePack {self.name!r}: object {g!r} does not "
                    f"satisfy the Gate Protocol (needs name, applies, evaluate)"
                )
        # Gate names must be unique so the reducer's order_index is
        # well-defined and so logs / tests can address a specific gate
        # unambiguously.
        names = [g.name for g in self.gates]
        if len(names) != len(set(names)):
            raise ValueError(
                f"GatePack {self.name!r}: duplicate gate names in {names}"
            )

    @property
    def gate_order(self) -> list[str]:
        """Names in evaluation/tie-break order. Stable for the lifetime of the pack."""
        return [g.name for g in self.gates]


__all__ = ["Gate", "GateContext", "GatePack"]
