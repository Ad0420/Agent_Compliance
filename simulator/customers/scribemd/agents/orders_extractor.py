"""Orders-extraction agent — pulls structured diagnoses + medication orders
from the SOAP note drafted upstream.

Uses Anthropic Claude. Mixing providers across the pipeline is intentional:
one demo run exercises both `AuditedOpenAI` (note drafter) and
`AuditedAnthropic` (this agent), proving Vera's multi-provider auditing.
"""

from __future__ import annotations

import json
import re

from simulator.shared.llm import LLMProvider

from vera import VeraClient


SYSTEM_PROMPT = (
    "You are an extraction agent for ScribeMD Health. "
    "Read the provided SOAP note and return a JSON object with three keys: "
    "diagnoses (list of strings), medication_orders (list of strings, "
    "each formatted 'drug dose route frequency'), and lab_or_imaging_orders "
    "(list of strings). Output only valid JSON, nothing else. If a field "
    "has no entries, return an empty list."
)


class OrdersExtractorAgent:
    """Extracts structured orders from a SOAP note, records into Vera."""

    AGENT_NAME = "scribemd-orders-extractor"
    FRAMEWORK = "scribemd-pipeline"

    def __init__(self, llm: LLMProvider, vera: VeraClient):
        self.llm = llm
        self.vera = vera

    def extract(self, *, note: str, patient_subject_id: str, encounter_id: str) -> dict:
        """Return `{"diagnoses": [...], "medication_orders": [...],
        "lab_or_imaging_orders": [...], "record_id": str}`."""
        resp = self.llm.chat(system=SYSTEM_PROMPT, user=note, max_tokens=400)
        parsed = _safe_json(resp.text)

        result_label = "success" if parsed is not None else "partial"
        outcome_payload = parsed or {"raw_output": resp.text, "parse_error": True}

        record = self.vera.record_action(
            action_name="extract_orders",
            action_type="llm_call",
            result=result_label,
            data_subject_id=patient_subject_id,
            input_data={
                "encounter_id": encounter_id,
                "note_excerpt": note[:300],
                "note_length": len(note),
            },
            outcome={
                **outcome_payload,
                "input_tokens": resp.input_tokens,
                "output_tokens": resp.output_tokens,
            },
            reasoning={"model": resp.model},
            duration_ms=resp.duration_ms,
            model_id=resp.model,
            framework=self.FRAMEWORK,
        )

        return {
            "diagnoses": (parsed or {}).get("diagnoses", []),
            "medication_orders": (parsed or {}).get("medication_orders", []),
            "lab_or_imaging_orders": (parsed or {}).get("lab_or_imaging_orders", []),
            "record_id": record["id"],
            "sequence_number": record["sequence_number"],
            "model": resp.model,
            "tokens": {"input": resp.input_tokens, "output": resp.output_tokens},
        }


_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _safe_json(text: str) -> dict | None:
    """Parse a JSON object out of `text`, tolerating markdown fences."""
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
    # Last resort: find first { and last } and try
    first = text.find("{")
    last = text.rfind("}")
    if 0 <= first < last:
        try:
            return json.loads(text[first : last + 1])
        except json.JSONDecodeError:
            return None
    return None
