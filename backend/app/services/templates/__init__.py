"""Markdown template generators for the Phase 5 counsel-attestation flow.

Five canonical templates, one per file in this package. Each generator
is a pure function that takes the org's validated ``WizardAnswers`` +
the ``Organization`` row and returns a Markdown string. The route layer
in ``app/routes/templates.py`` persists the strings into the
``generated_templates`` table and exposes CRUD + attest endpoints.

Locked key set
--------------
``TEMPLATE_KEYS`` is the single source of truth for the five values
``template_key`` may take. The route layer validates against this set;
the model column is a free VARCHAR so adding a sixth key is a one-line
service change, not a migration.

Voice rules
-----------
Bodies follow the project's copy rules (see ``CLAUDE.md`` §Voice &
copy):
  * No bare imperatives — use ``Consider X`` / ``Recommended: X``.
  * "Customer" not "Hospital" / "Tenant".
  * Full-date format with year ("Mar 15, 2026").
  * Never "court-admissible" — use "regulator-ready" / "evidence trail".

Each generator's docstring spells out the sections it produces; the
unit tests in ``tests/test_templates.py`` assert key sections + the
voice-rule constraints.
"""

from __future__ import annotations

from .ai_care_disclosure import generate_ai_care_disclosure
from .ai_tool_inventory import generate_ai_tool_inventory
from .hipaa_risk_analysis import generate_hipaa_risk_analysis
from .section_1557_ndp import generate_section_1557_ndp
from .workforce_training_outline import generate_workforce_training_outline

# Locked key set. The route layer validates against this; the generator
# dispatch table below also keys off it. Order is significant only for
# the list endpoint's default sort (alphabetical anyway, but we keep the
# tuple ordered so ``TEMPLATE_KEYS[0]`` is stable for tests).
TEMPLATE_KEYS: tuple[str, ...] = (
    "hipaa_risk_analysis",
    "section_1557_ndp",
    "ai_tool_inventory",
    "workforce_training_outline",
    "ai_care_disclosure",
)

# Dispatch table — single source of truth for "which generator handles
# which key". The route layer iterates over ``TEMPLATE_KEYS`` and looks
# each one up here. Adding a new generator requires adding one entry
# here AND one entry to ``TEMPLATE_KEYS``; the unit tests assert both
# stay in sync.
_GENERATORS = {
    "hipaa_risk_analysis": generate_hipaa_risk_analysis,
    "section_1557_ndp": generate_section_1557_ndp,
    "ai_tool_inventory": generate_ai_tool_inventory,
    "workforce_training_outline": generate_workforce_training_outline,
    "ai_care_disclosure": generate_ai_care_disclosure,
}


def generate(template_key: str, wizard_answers, org) -> str:
    """Dispatch to the right generator for ``template_key``.

    Raises ``KeyError`` if the key is unknown — the route layer
    validates against ``TEMPLATE_KEYS`` before calling this, so an
    unknown key here is a programmer error, not a user-facing 4xx.
    """
    return _GENERATORS[template_key](wizard_answers, org)


__all__ = [
    "TEMPLATE_KEYS",
    "generate",
    "generate_ai_care_disclosure",
    "generate_ai_tool_inventory",
    "generate_hipaa_risk_analysis",
    "generate_section_1557_ndp",
    "generate_workforce_training_outline",
]
