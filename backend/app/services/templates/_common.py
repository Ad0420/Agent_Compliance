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


# California (CMIA add-on) was the wizard's original California slug
# (``us_ca``) before Phase 5 expanded the per-state coverage. The
# generator treats both as "include the CA AB 489 clause" so wizard
# answers persisted before Phase 5 keep working without a backfill.
CALIFORNIA_SLUGS = frozenset({"california", "us_ca"})
TEXAS_SLUGS = frozenset({"texas"})
UTAH_SLUGS = frozenset({"utah"})


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
