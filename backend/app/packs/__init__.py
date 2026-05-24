"""Phase 2 Wave 2B — gate-pack scaffolding.

A *pack* is an ordered, named bundle of ``Gate`` instances that the
evaluator iterates over for a given vertical (clinical scribe, lender
underwriter, hiring agent, …). The base building blocks live in
``app.packs.base``; each concrete pack lives in its own subpackage and
re-exports a single ``CLINICAL_SCRIBE_PACK``-style constant from its
``__init__.py``.

A2 ships one pack — ``CLINICAL_SCRIBE_PACK`` — for medtech workloads.
Future PRs (D-series) add more packs without touching the evaluator.
"""

from .base import Gate, GateContext, GatePack
from .clinical import CLINICAL_SCRIBE_PACK

__all__ = ["CLINICAL_SCRIBE_PACK", "Gate", "GateContext", "GatePack"]
