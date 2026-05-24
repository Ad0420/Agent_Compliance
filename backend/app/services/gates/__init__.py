"""Phase 2 gates package.

Re-exports the public ``evaluate_gates`` entry point and the registered
``CLINICAL_SCRIBE_PACK`` so downstream tooling (dashboard, SDK) can
introspect which gates exist without reaching into the packs tree.
"""

from ...packs import CLINICAL_SCRIBE_PACK
from .evaluator import evaluate_gates

__all__ = ["CLINICAL_SCRIBE_PACK", "evaluate_gates"]
