"""Phase 2 Wave 2B — Gate 1: new_diagnosis_requires_attending.

When an agent proposes to add a new diagnosis (or any new entry on the
patient problem list / ICD-10 assignment), CMS conditions of participation
for hospitals require the entry be authenticated by the responsible
practitioner. We route to HITL with ``required_role='attending_physician'``.

Citation: ``42 CFR 482.24(c)(4)(viii)``.

Trigger surface
---------------
The gate fires when ANY of the following are true:

1. ``action_type`` matches a known diagnosis-creating verb-noun pair
   (set membership, exact match).
2. ``action_name`` matches one of five regex patterns (word-anchored,
   case-insensitive) that capture human-written verb forms ("add
   diagnosis", "record new diagnosis", "icd-10 assign", "diagnose").
3. ``input_data`` carries an ``icd10`` / ``diagnosis_code`` field with a
   non-empty value. Key lookup is normalized (lowercase, no dashes /
   underscores) so ``ICD-10``, ``icd_10``, ``icd10`` all hit.

A deny-pattern strips out two confusable cases that must NOT trigger:

* ``"undiagnose"`` / ``"un-diagnose"`` — explicit removal verb.
* ``"differential_diagnosis_*"`` / ``"differential diagnosis *"`` — a
  clinical reasoning step, not a chart entry.

The deny-pattern check runs *first* so it short-circuits before the
positive regex panel.
"""

from __future__ import annotations

import re
from typing import Final

from ...schemas.gate import Ruling, RulingEffect
from ..base import Gate, GateContext


# Exact-match action_type set. Lowercase. Membership check is O(1).
_DIAGNOSIS_ACTION_TYPES: Final[frozenset[str]] = frozenset({
    "diagnosis_create",
    "diagnosis_add",
    "problem_list_add",
    "problem_list_create",
    "condition_create",
    "condition_add",
})

# Positive patterns. Each is word-anchored so we don't match inside an
# unrelated identifier. Order is irrelevant — any match fires.
_DX_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    # "add diagnosis" / "create new diagnosis" / "record diagnosis" /
    # "note diagnosis" / "enter new diagnosis"
    re.compile(
        r"\b(add|create|record|note|enter)[_\s-]*(new[_\s-]+)?diagnos(is|es)\b",
        re.IGNORECASE,
    ),
    # Bare "new diagnosis" / "new_diagnosis" / "new-diagnosis"
    re.compile(r"\bnew[_\s-]+diagnos(is|es)\b", re.IGNORECASE),
    # "add to problem list" / "append to problem_list"
    re.compile(
        r"\b(add|append)[_\s-]+to[_\s-]+problem[_\s-]+list\b",
        re.IGNORECASE,
    ),
    # "icd10 assign" / "icd-10 code add" / "icd_10 assign"
    re.compile(
        r"\bicd[_\s-]*10([_\s-]+code)?[_\s-]+(add|assign|create)\b",
        re.IGNORECASE,
    ),
    # Verb form: "diagnose" / "diagnosed" / "diagnoses" — word-anchored
    # so "undiagnose" / "misdiagnose" / "differential_diagnosis" don't
    # match (their leading characters break the \b boundary).
    re.compile(r"\bdiagnose[sd]?\b", re.IGNORECASE),
)

# Negative patterns. Checked BEFORE the positive panel. Any match
# short-circuits the gate's trigger logic to False.
#
# We use ``(?:^|[\s_-])`` / ``(?:[\s_-]|$)`` as boundary anchors rather
# than ``\b`` because the latter treats underscore as a word character —
# so ``\bdifferential\b`` does NOT match ``differential_diagnosis``. The
# explicit boundary class catches the snake_case / kebab-case forms an
# action_name realistically takes.
_TOKEN_START = r"(?:^|[\s_\-])"
_TOKEN_END = r"(?:[\s_\-]|$)"
_DX_DENY_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(
        rf"{_TOKEN_START}undiagnose[sd]?{_TOKEN_END}", re.IGNORECASE
    ),
    re.compile(rf"{_TOKEN_START}differential{_TOKEN_END}", re.IGNORECASE),
    re.compile(rf"{_TOKEN_START}rule[_\s-]*out{_TOKEN_END}", re.IGNORECASE),
)

# Lowercased + normalized keys to look up in input_data.
_ICD_CODE_KEYS: Final[frozenset[str]] = frozenset({
    "icd10",
    "icd10code",
    "diagnosiscode",
    "dxcode",
    "primarydiagnosiscode",
})


def _normalize_key(k: str) -> str:
    """Lowercase the key and strip dashes/underscores for forgiving lookup.

    ``ICD-10`` / ``icd_10`` / ``ICD10`` all become ``icd10``. Lets a
    well-meaning agent send any of those without us missing the trigger.
    """
    return k.lower().replace("-", "").replace("_", "")


def _input_has_icd_code(input_data: dict[str, object]) -> bool:
    """Return True iff input_data has a non-empty ICD-10 / diagnosis-code field."""
    if not input_data:
        return False
    for raw_key, value in input_data.items():
        if not isinstance(raw_key, str):
            continue
        if _normalize_key(raw_key) not in _ICD_CODE_KEYS:
            continue
        # Reject empty strings and None, accept any non-empty value.
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return True
    return False


def _text_triggers_diagnosis(text: str) -> bool:
    """Check a free-text string against the regex panel.

    Deny patterns checked first. Empty string → False.
    """
    if not text:
        return False
    for pat in _DX_DENY_PATTERNS:
        if pat.search(text):
            return False
    for pat in _DX_PATTERNS:
        if pat.search(text):
            return True
    return False


class NewDiagnosisGate:
    """Gate 1 — fires on actions that record a new patient diagnosis.

    Routes to HITL with ``required_role='attending_physician'`` per CMS
    medical-records authentication requirements (42 CFR 482.24(c)(4)(viii)).
    """

    name: Final[str] = "new_diagnosis_requires_attending"

    def applies(self, ctx: GateContext) -> bool:
        req = ctx.request

        # 1. action_type exact match.
        if req.action_type and req.action_type.lower() in _DIAGNOSIS_ACTION_TYPES:
            # Deny patterns still get a chance to veto via action_name —
            # an action_type='diagnosis_create' with
            # action_name='differential_diagnosis_review' is a clinical
            # reasoning step.
            if req.action_name and any(
                pat.search(req.action_name) for pat in _DX_DENY_PATTERNS
            ):
                return False
            return True

        # 2. action_name regex panel (deny patterns checked inside helper).
        if req.action_name and _text_triggers_diagnosis(req.action_name):
            return True

        # 3. input_data has an ICD-10 / diagnosis-code field with a
        #    non-empty value.
        if _input_has_icd_code(req.input_data):
            return True

        return False

    async def evaluate(self, ctx: GateContext) -> Ruling:
        # No DB. No PHI in the response — reason_detail names the *kind*
        # of action ("a new patient diagnosis") without echoing any input
        # field. The original input_data is stashed by the evaluator into
        # Approval.context so the human reviewer has the full payload,
        # but it never leaves /v1/gates/evaluate in the Ruling itself.
        return Ruling(
            effect=RulingEffect.REQUIRE_HITL,
            reason="new_diagnosis_proposed",
            reason_detail=(
                "Proposed action records a new patient diagnosis. CMS "
                "requires an attending physician to confirm new "
                "diagnoses before they enter the patient's chart."
            ),
            citation="42 CFR 482.24(c)(4)(viii)",
            required_role="attending_physician",
            gate_name=self.name,
        )


__all__ = ["NewDiagnosisGate"]
