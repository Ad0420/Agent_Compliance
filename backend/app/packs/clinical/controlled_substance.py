"""Phase 2 Wave 2B — Gate 2: controlled_substance_requires_dea.

Triggers when the proposed action references a DEA-listed controlled
substance (Schedule II-V; see ``controlled_substance_list``). Routes
to HITL with ``required_role='dea_authorized'``.

Citation: ``21 CFR 1306.04(a)`` — "a prescription for a controlled
substance to be effective must be issued for a legitimate medical
purpose by an individual practitioner acting in the usual course of
his professional practice".

Two-stage detection
-------------------
**Stage A — structured medication fields.** Walk ``input_data`` for
known medication-shaped keys (``medication``, ``drug``, ``prescription``,
``rx``, ``substance`` and ``_name`` variants). Recurse one level for
nested dicts (e.g. ``{"order": {"medication": "OxyContin 5mg"}}``).
Pass each value through ``find_controlled_in_text`` so a free-text
dose string ("oxycodone 5mg q4h") still resolves to the generic.

**Stage B — free-text scan.** When Stage A finds nothing, concatenate
``action_name`` + ``action_description`` + scalar values of
``input_data`` and run the same ``find_controlled_in_text``. Catches
informally-worded calls like ``action_name='prescribe vicodin'``.

Either stage producing a match fires the gate. The matched *generic*
name is reported in the ruling's ``reason_detail``; the matched text
itself is NOT echoed back (PHI-safe).
"""

from __future__ import annotations

from typing import Final

from ...schemas.gate import Ruling, RulingEffect
from ..base import Gate, GateContext
from .controlled_substance_list import find_controlled_in_text, resolve_generic


# Keys whose value should be scanned as a medication name. Normalized
# by `_normalize_key` before comparison so ``Medication-Name`` /
# ``medication_name`` / ``MedicationName`` all hit.
_MEDICATION_KEYS: Final[frozenset[str]] = frozenset({
    "medication",
    "medicationname",
    "drug",
    "drugname",
    "prescription",
    "prescriptionname",
    "rx",
    "rxname",
    "med",
    "medname",
    "substance",
    "substancename",
    "controlledsubstance",
    "controlledsubstancename",
    "orderedmedication",
})

# Cap recursion at depth 2 so a deeply nested adversarial payload
# can't blow the stack or pin CPU. The structured walk is intended
# for shallow ``{"order": {"medication": "..."}}`` shapes; anything
# deeper relies on Stage B.
_MAX_RECURSION_DEPTH: Final[int] = 2


def _normalize_key(k: str) -> str:
    """Lowercase + strip dashes/underscores/whitespace for forgiving lookup."""
    return k.lower().replace("-", "").replace("_", "").replace(" ", "")


def _scan_structured(
    data: object, depth: int = 0
) -> list[str]:
    """Walk ``data`` looking for medication-shaped keys.

    Returns the list of generic names matched. Recurses into nested
    dicts up to ``_MAX_RECURSION_DEPTH``; lists scanned one level (the
    list itself counts as one depth step).
    """
    if depth > _MAX_RECURSION_DEPTH:
        return []
    matches: list[str] = []
    if isinstance(data, dict):
        for raw_key, value in data.items():
            if isinstance(raw_key, str) and _normalize_key(raw_key) in _MEDICATION_KEYS:
                if isinstance(value, str):
                    # Run through the text scanner — a value like
                    # "oxycodone 5mg q4h" should still resolve.
                    matches.extend(find_controlled_in_text(value))
                elif isinstance(value, (list, tuple)):
                    for item in value:
                        if isinstance(item, str):
                            matches.extend(find_controlled_in_text(item))
            # Recurse into nested dicts/lists regardless of key — a
            # benign-named wrapper might hold a medication-shaped
            # subdict.
            if isinstance(value, dict):
                matches.extend(_scan_structured(value, depth + 1))
            elif isinstance(value, (list, tuple)):
                for item in value:
                    matches.extend(_scan_structured(item, depth + 1))
    return matches


def _scan_freetext(ctx: GateContext) -> list[str]:
    """Stage B: concatenate readable strings and scan for tokens.

    Includes ``action_name``, ``action_description``, and scalar string
    values in ``input_data`` (one level — not the recursive walk Stage
    A does, to keep this strictly a fallback).
    """
    req = ctx.request
    chunks: list[str] = []
    if req.action_name:
        chunks.append(req.action_name)
    if req.action_description:
        chunks.append(req.action_description)
    if req.input_data:
        for value in req.input_data.values():
            if isinstance(value, str):
                chunks.append(value)
    if not chunks:
        return []
    return find_controlled_in_text(" ".join(chunks))


class ControlledSubstanceGate:
    """Gate 2 — fires on actions that reference a DEA-listed substance.

    Routes to HITL with ``required_role='dea_authorized'`` per
    21 CFR 1306.04 (prescription must be issued by a registered
    practitioner).
    """

    name: Final[str] = "controlled_substance_requires_dea"

    def applies(self, ctx: GateContext) -> bool:
        # The gate is cheap: it walks at most a couple of dict levels
        # and runs a regex over a small bounded string. Always run.
        # Returning True here means evaluate() also runs the scan —
        # we accept the duplicate work because the alternative
        # (stashing matches on `self`) would break the stateless /
        # re-entrant contract documented on ``Gate``.
        return True

    async def evaluate(self, ctx: GateContext) -> Ruling:
        # Stage A: structured medication keys.
        matches = _scan_structured(ctx.request.input_data)
        # Stage B fallback: free-text scan over action_name + description
        # + scalar input values.
        if not matches:
            matches = _scan_freetext(ctx)

        if not matches:
            return Ruling(
                effect=RulingEffect.ALLOW,
                reason="no_controlled_substance_detected",
                gate_name=self.name,
            )

        # Use the first matched generic for the reason_detail. The full
        # list is logged at INFO via the evaluator, never echoed back to
        # the SDK (the SDK only needs to know that *something* DEA-listed
        # triggered the gate; the matched generic name is a useful but
        # bounded detail).
        matched_generic = resolve_generic(matches[0]) or matches[0]
        return Ruling(
            effect=RulingEffect.REQUIRE_HITL,
            reason="controlled_substance_detected",
            reason_detail=(
                f"Proposed action references a controlled substance "
                f"(matched: {matched_generic}). DEA requires a registered "
                f"practitioner to authorize controlled-substance "
                f"prescriptions."
            ),
            citation="21 CFR 1306.04",
            required_role="dea_authorized",
            gate_name=self.name,
        )


__all__ = ["ControlledSubstanceGate"]
