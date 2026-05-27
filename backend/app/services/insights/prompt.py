"""System + user prompt templates for the AI Insights endpoint.

Kept in a single module so a copy tweak is a one-file diff. The
system prompt is intentionally specific about JSON-only output +
quoted_source-must-be-a-substring — the validator catches drift
either way, but a tight prompt cuts the regen rate.
"""

from __future__ import annotations

import json
from typing import Any


# The system prompt is verbatim what the brief specified. Care:
#   * "JSON only; no preamble" cuts the most common drift mode.
#   * "NEVER paraphrase" the quoted_source — the validator backs this
#     up with a substring check, but telling the model up front keeps
#     the fallback rate low.
#   * Voice-rule wording (Consider/Recommended) tracks the dashboard
#     copy rules in ``dashboard-design-system.md §Voice & copy``. The
#     model's output isn't gated by CI copy lint, but the prompt's
#     bias is the cheapest way to keep cards in voice.
INSIGHTS_SYSTEM_PROMPT = (
    "You are a compliance posture analyst for healthcare-AI vendors. "
    "The user will give you a JSON snapshot of their runtime "
    "compliance posture across six dimensions. Your job: produce "
    "exactly 3 to 5 short recommendation cards. Each card has: "
    "title (≤10 words), severity (HIGH | MEDIUM | LOW), quoted_source "
    "(a literal short substring from the posture JSON — NEVER "
    "paraphrase), description (1-2 sentences explaining the signal), "
    "suggested_action (1 sentence; always start with \"Consider\" or "
    "\"Recommended:\"). Output JSON only; no preamble, no commentary. "
    "If the posture data is too thin to produce meaningful insights, "
    "return cards that say so honestly."
)


# JSON-only reminder appended on the retry path. Slightly stronger
# wording — if the first call already drifted, we lean harder on the
# format constraint before falling through to the canned cards.
INSIGHTS_RETRY_REMINDER = (
    " IMPORTANT: Respond with ONLY a JSON object of the form "
    '{"insights": [...]}. Do not include any text before or after '
    "the JSON. Do not wrap the JSON in markdown code fences. Each "
    "insight MUST include id, title, severity, quoted_source, "
    "description, and suggested_action fields."
)


def build_user_message(posture_dict: dict[str, Any]) -> str:
    """Build the user-message payload for the Haiku call.

    The model gets the raw posture JSON plus a one-line frame.
    Keeping the framing minimal — the system prompt already carries
    the full instruction set; the user message just hands over data.
    """
    # ``indent=2`` keeps the substring check in the validator readable:
    # multi-line JSON gives the model whole-line anchors it can copy
    # without paraphrase. Compact JSON works too but the validator's
    # whitespace-tolerance handles either; readability wins for the
    # human operator inspecting logs.
    return (
        "Here is the compliance posture snapshot for this customer. "
        "Produce 3 to 5 recommendation cards per the system "
        "instructions. Reply with JSON only.\n\n"
        f"```json\n{json.dumps(posture_dict, indent=2, default=str)}\n```"
    )
