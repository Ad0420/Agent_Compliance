"""AI Insights service (Phase 4 Wave 2 PR B2).

Synchronous OpenAI-backed recommendation cards for the compliance
posture endpoint. No persistence in v1 — every call regenerates from
the live posture snapshot. See ``services/insights/generator.py`` for
the orchestrator and ``validator.py`` for the substring-anchor +
clamp helpers that keep model output honest.
"""

from .generator import generate_insights

__all__ = ["generate_insights"]
