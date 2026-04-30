"""Triage classifier — turns a patient symptom narrative into an acuity level.

Uses OpenAI in Mode A. Each call records into Vera with the symptom text
as input_data, the parsed acuity level as outcome, and token/model
metadata as reasoning.
"""

from __future__ import annotations

import hashlib
import json
import re

from simulator.shared.llm import LLMProvider

from vera import VeraClient


SYSTEM_PROMPT = (
    "You are TriageGuard's AI triage classifier for a telehealth front door. "
    "Read the patient's symptom narrative and return a JSON object with "
    "exactly these keys: level (one of \"self_care\", \"virtual_visit\", "
    "\"urgent_care\", \"ER\"), reasoning (1-2 sentence rationale), confidence "
    "(float 0..1). Do NOT inflate acuity for legal protection — return your "
    "honest first read. Output ONLY valid JSON, no markdown fencing."
)


_VALID_LEVELS = {"self_care", "virtual_visit", "urgent_care", "ER"}


class TriageClassifierAgent:
    """Initial-acuity classifier backed by an LLM provider + Vera."""

    AGENT_NAME = "triageguard-triage-classifier"
    FRAMEWORK = "triageguard-pipeline"

    def __init__(self, llm: LLMProvider, vera: VeraClient):
        self.llm = llm
        self.vera = vera

    def classify(
        self, *, symptoms: str, patient_subject_id: str, session_id: str
    ) -> dict:
        """Classify `symptoms` and record into Vera.

        Returns `{level, reasoning, confidence, record_id, sequence_number,
        model, tokens, duration_ms}`.
        """
        resp = self.llm.chat(system=SYSTEM_PROMPT, user=symptoms, max_tokens=300)
        parsed = _safe_json(resp.text) or {}

        level = parsed.get("level")
        if level not in _VALID_LEVELS:
            # Fall back conservatively to virtual_visit if the model returned
            # something unparseable. Audit chain captures the parse_error.
            level = "virtual_visit"
            parsed.setdefault("parse_error", True)

        reasoning_text = parsed.get("reasoning", "")
        confidence = parsed.get("confidence", None)

        result_label = "success" if not parsed.get("parse_error") else "partial"

        record = self.vera.record_action(
            action_name="classify_triage",
            action_type="llm_call",
            result=result_label,
            data_subject_id=patient_subject_id,
            input_data={
                "session_id": session_id,
                "symptoms_excerpt": symptoms[:300],
                "symptoms_length": len(symptoms),
            },
            outcome={
                "level": level,
                "model_reasoning": reasoning_text,
                "confidence": confidence,
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
            "level": level,
            "reasoning": reasoning_text,
            "confidence": confidence,
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
