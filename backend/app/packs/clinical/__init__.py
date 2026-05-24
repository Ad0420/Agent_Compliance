"""Phase 2 Wave 2B — ClinicalScribePack.

Single pack of three gates for medtech scribe workloads:

* ``StaleBaaGate``            — HIPAA 45 CFR 164.502(e)
* ``NewDiagnosisGate``        — CMS 42 CFR 482.24(c)(4)(viii)
* ``ControlledSubstanceGate`` — DEA 21 CFR 1306.04

Re-exports ``CLINICAL_SCRIBE_PACK`` so callers can ``from app.packs import
CLINICAL_SCRIBE_PACK`` without reaching into ``.pack``.
"""

from .pack import CLINICAL_SCRIBE_PACK

__all__ = ["CLINICAL_SCRIBE_PACK"]
