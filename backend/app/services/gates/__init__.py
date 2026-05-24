"""Phase 2 gates package.

Re-exports the public ``evaluate_gates`` entry point. Real gate
implementations (``ClinicalScribePack``) land in Wave 2B PR A2 as
sibling modules in this package.
"""

from .evaluator import evaluate_gates

__all__ = ["evaluate_gates"]
