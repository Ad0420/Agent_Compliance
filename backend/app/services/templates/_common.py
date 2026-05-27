"""Shared helpers for the Phase 5 template generators.

Kept private (underscore-prefixed) so the public surface of the
``templates`` package is the generator functions + ``TEMPLATE_KEYS``.
"""

from __future__ import annotations

from datetime import datetime, timezone

# Placeholder marker the frontend CSS-highlights so reviewers know where
# to type their actual practice. Used by every generator; defined here
# so a future style change is a one-line edit.
REPLACE_MARKER = "<<REPLACE WITH YOUR ACTUAL PRACTICE>>"


def format_generated_date(dt: datetime | None = None) -> str:
    """Render the generated-on date as ``Mon DD, YYYY`` per voice rules.

    The voice rules in ``CLAUDE.md`` mandate full-date format with year
    ("Mar 15, 2026" not "Mar 15"). ``%b %d, %Y`` produces the right
    shape; we strip the leading zero from the day so ``Mar 5, 2026``
    instead of ``Mar 05, 2026`` matches the reference output exactly.
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    # ``%-d`` is the GNU extension for "day without leading zero" and is
    # not portable to Windows / strict POSIX. Strip it ourselves.
    day = dt.day
    return f"{dt.strftime('%b')} {day}, {dt.year}"


def generated_note() -> str:
    """The "Generated on ... — review with counsel" sub-header line.

    One-liner shared across all five templates. Keeps the voice rules
    enforced in one place: no bare imperatives ("Consider reviewing"
    not "You should review"), full date with year.
    """
    return (
        f"_Generated {format_generated_date()} from your onboarding "
        f"answers — review with counsel before sign-off._"
    )


# Per-jurisdiction slug sets that AI Care Disclosure (and any other
# generator that branches on geography) intersects with the wizard's
# ``jurisdictions`` answer.
#
# Each set carries the canonical Phase 5 slug + any legacy slug a
# pre-Phase 5 wizard row might still carry on disk. The
# ``WizardAnswers`` schema rewrites legacy slugs to canonical on load
# (see ``schemas/wizard._validate_jurisdictions``), so in practice the
# legacy aliases here are belt-and-suspenders for old rows that bypass
# the schema (e.g. a raw DB read).
CALIFORNIA_AB489_SLUGS = frozenset({"california_ab489", "california", "us_ca"})
CALIFORNIA_SB942_SLUGS = frozenset({"california_sb942"})
TEXAS_SLUGS = frozenset({"texas"})
UTAH_SLUGS = frozenset({"utah"})
COLORADO_SLUGS = frozenset({"colorado"})
EU_SLUGS = frozenset({"eu"})
NEW_YORK_SLUGS = frozenset({"new_york"})
OTHER_SLUGS = frozenset({"other"})

# Backwards-compat alias — pre-Phase 5 the CA slug set was named
# ``CALIFORNIA_SLUGS`` (no AB 489 / SB 942 split). Keep the old name
# pointing at the AB 489 set so any external caller (or stale import in
# a half-merged branch) keeps working.
CALIFORNIA_SLUGS = CALIFORNIA_AB489_SLUGS


def has_jurisdiction(jurisdictions, *slugs) -> bool:
    """Return True if ``jurisdictions`` intersects any of the given
    slug sets.

    Tolerates ``None`` and empty lists (returns False). Used by the
    AI-Assisted Care Disclosure generator to decide whether to emit a
    conditional clause.
    """
    if not jurisdictions:
        return False
    selected = set(jurisdictions)
    for slug_set in slugs:
        if selected & set(slug_set):
            return True
    return False
