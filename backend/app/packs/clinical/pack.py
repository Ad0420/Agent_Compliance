"""Phase 2 Wave 2B — ClinicalScribePack composition.

A single ``GatePack`` instance composed of the medtech gates in their
documented evaluation order. The evaluator imports
``CLINICAL_SCRIBE_PACK`` and iterates ``.gates`` left-to-right.

Order rationale
---------------
1. ``StaleBaaGate``           — cheap (cached), often BLOCKs. Avoids
   running PHI-adjacent scans on payloads we'd refuse anyway.
2. ``NewDiagnosisGate``       — cheap field-shape check.

(Commit 5 of PR A2 appends ``ControlledSubstanceGate``.)

The reducer's strictest-wins guarantee is order-independent, so this
order is purely a runtime optimisation. Re-ordering at a later date
will not change correctness; tests in ``test_gates_evaluate_integration``
pin the documented expectation.
"""

from __future__ import annotations

from ..base import GatePack
from .new_diagnosis import NewDiagnosisGate
from .stale_baa import StaleBaaGate

CLINICAL_SCRIBE_PACK = GatePack(
    name="clinical_scribe",
    gates=(
        StaleBaaGate(),
        NewDiagnosisGate(),
    ),
)

__all__ = ["CLINICAL_SCRIBE_PACK"]
