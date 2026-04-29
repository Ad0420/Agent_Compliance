"""Note-drafting agent — turns a visit transcript into a SOAP note.

Uses OpenAI in Mode A. Each call records into Vera with the full prompt as
input_data, the generated note as outcome, and token usage as reasoning.
This exercises the audit trail's `model_id` / `model_version` / `framework`
fields end-to-end.
"""

from __future__ import annotations

from simulator.shared.llm import LLMProvider

from vera import VeraClient


SYSTEM_PROMPT = (
    "You are a clinical scribe assistant for ScribeMD Health. "
    "Convert the following physician-patient encounter transcript into a "
    "SOAP-format clinical note. Use these section headers exactly: "
    "SUBJECTIVE, OBJECTIVE, ASSESSMENT, PLAN. Be concise. Do not invent "
    "findings the transcript does not support. If a finding is uncertain, "
    "prefix it with 'Possible:'. Output only the note, no extra commentary."
)


class NoteDrafterAgent:
    """SOAP-note drafting agent backed by an LLM provider + Vera."""

    AGENT_NAME = "scribemd-note-drafter"
    FRAMEWORK = "scribemd-pipeline"

    def __init__(self, llm: LLMProvider, vera: VeraClient):
        self.llm = llm
        self.vera = vera

    def draft(self, *, transcript: str, patient_subject_id: str, encounter_id: str) -> dict:
        """Draft a SOAP note from `transcript`. Records the action in Vera and
        returns `{"note": str, "record_id": str, "tokens": {...}}`."""
        resp = self.llm.chat(system=SYSTEM_PROMPT, user=transcript, max_tokens=600)

        record = self.vera.record_action(
            action_name="draft_clinical_note",
            action_type="llm_call",
            result="success",
            data_subject_id=patient_subject_id,
            input_data={
                "encounter_id": encounter_id,
                "transcript_excerpt": transcript[:300],
                "transcript_length": len(transcript),
            },
            outcome={
                "note": resp.text,
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
            "note": resp.text,
            "record_id": record["id"],
            "sequence_number": record["sequence_number"],
            "tokens": {"input": resp.input_tokens, "output": resp.output_tokens},
            "duration_ms": resp.duration_ms,
            "model": resp.model,
        }


def _short_hash(s: str) -> str:
    import hashlib

    return hashlib.sha256(s.encode()).hexdigest()[:16]
