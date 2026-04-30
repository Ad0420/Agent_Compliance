"""Red-flag detector — secondary check for high-risk symptom terms.

Uses Anthropic Claude in Mode A. The detector reads the same symptom
narrative the classifier saw and returns whether it spotted a red-flag
term (chest pain, sudden weakness, severe headache, anaphylaxis signs,
sepsis indicators, etc.) plus a recommended override level.

Mixing providers across the pipeline is intentional — one demo run
exercises both `AuditedOpenAI` (classifier) and `AuditedAnthropic`
(this detector), proving Vera's multi-provider auditing.
"""

from __future__ import annotations

import hashlib
import json
import re

from simulator.shared.llm import LLMProvider

from vera import VeraClient


SYSTEM_PROMPT = (
    "You are TriageGuard's red-flag detector. Read the patient's symptom "
    "narrative and the AI classifier's preliminary level. Identify any "
    "high-risk signs (chest pain, jaw/arm radiation, diaphoresis, sudden "
    "weakness or facial droop, severe sudden-onset headache, anaphylaxis "
    "signs, sepsis indicators like high fever + altered mental status, "
    "active suicidal ideation, severe respiratory distress, signs of "
    "stroke). Return JSON with exactly these keys: flagged (bool), terms "
    "(list of strings — the red-flag phrases you saw, empty if none), "
    "recommended_override (one of \"self_care\", \"virtual_visit\", "
    "\"urgent_care\", \"ER\", or null if no override needed), reasoning "
    "(1-2 sentences). Output ONLY valid JSON, no markdown fencing."
)


_VALID_LEVELS = {"self_care", "virtual_visit", "urgent_care", "ER"}


class RedFlagDetectorAgent:
    """Secondary safety check, records into Vera."""

    AGENT_NAME = "triageguard-red-flag-detector"
    FRAMEWORK = "triageguard-pipeline"

    def __init__(self, llm: LLMProvider, vera: VeraClient):
        self.llm = llm
        self.vera = vera

    def evaluate(
        self,
        *,
        symptoms: str,
        classifier_level: str,
        patient_subject_id: str,
        session_id: str,
    ) -> dict:
        """Evaluate `symptoms`, return
        `{flagged, terms, recommended_override, reasoning, record_id, …}`.
        """
        user_blob = (
            f"Classifier level: {classifier_level}\n\n"
            f"Symptoms:\n{symptoms}"
        )
        resp = self.llm.chat(system=SYSTEM_PROMPT, user=user_blob, max_tokens=400)
        parsed = _safe_json(resp.text) or {}

        flagged = bool(parsed.get("flagged", False))
        terms = parsed.get("terms") or []
        if not isinstance(terms, list):
            terms = []
        recommended_override = parsed.get("recommended_override")
        if recommended_override not in _VALID_LEVELS:
            recommended_override = None
        reasoning_text = parsed.get("reasoning", "")

        result_label = "success" if parsed else "partial"
        outcome_payload = {
            "flagged": flagged,
            "terms": terms,
            "recommended_override": recommended_override,
            "model_reasoning": reasoning_text,
        }
        if not parsed:
            outcome_payload["raw_output"] = resp.text
            outcome_payload["parse_error"] = True

        record = self.vera.record_action(
            action_name="evaluate_red_flags",
            action_type="llm_call",
            result=result_label,
            data_subject_id=patient_subject_id,
            input_data={
                "session_id": session_id,
                "classifier_level": classifier_level,
                "symptoms_excerpt": symptoms[:300],
                "symptoms_length": len(symptoms),
            },
            outcome={
                **outcome_payload,
                "input_tokens": resp.input_tokens,
                "output_tokens": resp.output_tokens,
            },
            reasoning={
                "system_prompt_hash": _short_hash(SYSTEM_PROMPT),
                "model": resp.model,
            },
            duration_ms=resp.duration_ms,
            model_id=resp.model,
            framework=self.FRAMEWORK,
        )

        return {
            "flagged": flagged,
            "terms": terms,
            "recommended_override": recommended_override,
            "reasoning": reasoning_text,
            "record_id": record["id"],
            "sequence_number": record["sequence_number"],
            "model": resp.model,
            "tokens": {"input": resp.input_tokens, "output": resp.output_tokens},
            "duration_ms": resp.duration_ms,
        }


_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _safe_json(text: str) -> dict | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = _JSON_FENCE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            return None
    first = text.find("{")
    last = text.rfind("}")
    if 0 <= first < last:
        try:
            return json.loads(text[first : last + 1])
        except json.JSONDecodeError:
            return None
    return None


def _short_hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]
