"""Phase 2 Wave 2B — DEA Schedule II–V controlled-substance reference list.

Hardcoded ``frozenset[str]`` of ~50 commonly-prescribed Schedule II/III/IV
generic names plus a brand → generic mapping. This is the *reference data*
for ``ControlledSubstanceGate``.

Why hardcoded (vs. live RxNorm)?
--------------------------------
The DEA schedule list changes a few times a year. A hardcoded list is:

* **Shippable today** — no NIH RxNorm RTT (200-500 ms), no caching layer,
  no graceful-degradation policy for NIH outages.
* **Auditable** — `git blame` on this file is the regulatory history.
* **Swappable** — every call site goes through ``is_controlled(name)`` /
  ``find_controlled_in_text(text)``. A follow-up PR can replace the
  body of those helpers with a cached RxNorm client without touching
  the gate.

Coverage targets the ~50 most commonly prescribed Schedule II/III/IV
generics plus 5 Schedule V. Brand-name mapping covers the ~10 most
prescribed branded controlled substances. This is a *trigger surface*,
not an exhaustive formulary: false negatives (an obscure brand name
slipping through) are far less costly than false positives (every
``acetaminophen`` order pinging an attending).
"""

from __future__ import annotations

import re
from typing import Final

# All entries lowercase. Sanity asserted by ``test_controlled_substance_list``.
# Sourced from the DEA Diversion Control Division's published schedule
# (see https://www.deadiversion.usdoj.gov/schedules/) cross-referenced
# with CDC outpatient prescribing volume. NOT a formulary — see module
# docstring.
_SCHEDULE_II: Final[frozenset[str]] = frozenset({
    # Opioids
    "oxycodone",
    "hydrocodone",
    "oxymorphone",
    "hydromorphone",
    "morphine",
    "fentanyl",
    "sufentanil",
    "alfentanil",
    "remifentanil",
    "methadone",
    "meperidine",
    "codeine",
    "tapentadol",
    # Stimulants
    "amphetamine",
    "dextroamphetamine",
    "methamphetamine",
    "methylphenidate",
    "lisdexamfetamine",
    # Barbiturates
    "secobarbital",
    "pentobarbital",
    # Anesthetics / dissociatives
    "ketamine",
})

_SCHEDULE_III: Final[frozenset[str]] = frozenset({
    "buprenorphine",
    "codeine",  # combinations like Tylenol w/ Codeine
    "ketamine",  # also Schedule III in combo forms — both listings safe
    "nalorphine",
    "testosterone",
    "anabolic_steroid",
    "anabolic",
})

_SCHEDULE_IV: Final[frozenset[str]] = frozenset({
    # Benzodiazepines
    "alprazolam",
    "lorazepam",
    "diazepam",
    "clonazepam",
    "temazepam",
    "midazolam",
    "oxazepam",
    "triazolam",
    "chlordiazepoxide",
    # Z-drugs
    "zolpidem",
    "zaleplon",
    "eszopiclone",
    # Other
    "tramadol",
    "modafinil",
    "armodafinil",
    "phentermine",
    "carisoprodol",
})

_SCHEDULE_V: Final[frozenset[str]] = frozenset({
    "pregabalin",
    "lacosamide",
    "ezogabine",
    "diphenoxylate",
    "difenoxin",
})

# Union of all schedules. Lookup target for ``is_controlled``.
_SCHEDULED_DRUGS: Final[frozenset[str]] = (
    _SCHEDULE_II | _SCHEDULE_III | _SCHEDULE_IV | _SCHEDULE_V
)

# Brand → generic mapping. Lowercase keys. The gate normalizes input,
# looks up the brand, and reports the *generic* in the ruling
# reason_detail so the log line and the SDK error message reference the
# DEA-listed substance rather than a trademark.
_BRAND_TO_GENERIC: Final[dict[str, str]] = {
    # Opioids
    "oxycontin": "oxycodone",
    "percocet": "oxycodone",
    "roxicodone": "oxycodone",
    "vicodin": "hydrocodone",
    "norco": "hydrocodone",
    "lortab": "hydrocodone",
    "dilaudid": "hydromorphone",
    "ms_contin": "morphine",
    "duragesic": "fentanyl",
    "actiq": "fentanyl",
    "subutex": "buprenorphine",
    "suboxone": "buprenorphine",
    "ultram": "tramadol",
    # Stimulants
    "adderall": "amphetamine",
    "vyvanse": "lisdexamfetamine",
    "ritalin": "methylphenidate",
    "concerta": "methylphenidate",
    "focalin": "methylphenidate",
    # Benzos & z-drugs
    "xanax": "alprazolam",
    "ativan": "lorazepam",
    "valium": "diazepam",
    "klonopin": "clonazepam",
    "restoril": "temazepam",
    "versed": "midazolam",
    "ambien": "zolpidem",
    "lunesta": "eszopiclone",
    "sonata": "zaleplon",
    # Other
    "lyrica": "pregabalin",
    "soma": "carisoprodol",
    "provigil": "modafinil",
    "nuvigil": "armodafinil",
}


# Tokens used by the free-text scan. Built once at import time.
# Sorted longest-first so multi-word brands match before single-word
# generics that happen to be substrings (defensive; current data has
# no such collisions, but the sort is cheap and locks the invariant).
_TEXT_SCAN_TOKENS: Final[tuple[str, ...]] = tuple(
    sorted(
        _SCHEDULED_DRUGS | set(_BRAND_TO_GENERIC.keys()),
        key=len,
        reverse=True,
    )
)


# Word-boundary regex matches each token surrounded by non-word characters
# (or string boundary). Prevents false positives like "morphine" matching
# inside "amorphine" (made-up example) or "ambient" containing "ambien"
# only when whitespace-separated.
_WORD_BOUNDARY = re.compile(r"\w+")


def normalize_drug_name(s: str) -> str:
    """Lowercase + collapse hyphens/underscores/whitespace to a single space.

    Used before set membership lookup. Hyphens collapse to nothing so
    ``"oxy-codone"`` resolves to ``"oxycodone"``; underscores in JSON-y
    keys (``"ms_contin"``) preserve as-is via the brand map's underscore
    keys. The brand map uses underscore-joined forms for multi-word
    brands; lookups normalize the same way.
    """
    if not s:
        return ""
    # Replace hyphens with empty string (oxy-codone → oxycodone).
    cleaned = s.lower().replace("-", "")
    # Collapse internal whitespace to single underscore so multi-word
    # brand names like "ms contin" map to "ms_contin".
    cleaned = re.sub(r"\s+", "_", cleaned.strip())
    return cleaned


def is_controlled(name: str) -> bool:
    """Return True iff ``name`` (after normalization) is on the DEA list.

    Resolves brand names via ``_BRAND_TO_GENERIC`` then checks the
    union of all schedules. Empty / whitespace-only input returns
    False (no FP on empty fields).
    """
    if not name:
        return False
    normalized = normalize_drug_name(name)
    if not normalized:
        return False
    if normalized in _SCHEDULED_DRUGS:
        return True
    if normalized in _BRAND_TO_GENERIC:
        return True
    return False


def resolve_generic(name: str) -> str | None:
    """Return the DEA-list generic name for ``name``, or None if unknown.

    For an already-generic input, returns the normalized generic. For a
    brand, returns the mapped generic. For something not on the list,
    returns None. Used by the gate to report the *generic* (not the
    brand) in ruling.reason_detail.
    """
    if not name:
        return None
    normalized = normalize_drug_name(name)
    if normalized in _SCHEDULED_DRUGS:
        return normalized
    if normalized in _BRAND_TO_GENERIC:
        return _BRAND_TO_GENERIC[normalized]
    return None


def find_controlled_in_text(text: str) -> list[str]:
    """Scan free-text for controlled-substance tokens; return generic names.

    Tokenizes ``text`` on word boundaries, normalizes each token, and
    looks it up against the union of generics + brands. Returns the
    DEA-list *generic* form (brand → generic via ``resolve_generic``)
    for each unique match, in first-appearance order.

    Used by Stage B of ``ControlledSubstanceGate``: when no structured
    medication field matched, scan ``action_name`` + ``action_description``
    + scalar input values. False positives on free-text negation
    (``"patient denies oxycodone"``) are an acceptable trade-off — better
    to over-route to HITL on a controlled-substance keyword than to
    miss a dose-string buried in a description.
    """
    if not text:
        return []
    seen: set[str] = set()
    matches: list[str] = []
    lowered = text.lower()
    for token_match in _WORD_BOUNDARY.finditer(lowered):
        token = token_match.group(0)
        # ``token`` is already lowercase and has no hyphens (regex \w+
        # already split them). Direct lookup; no extra normalize call.
        generic = None
        if token in _SCHEDULED_DRUGS:
            generic = token
        elif token in _BRAND_TO_GENERIC:
            generic = _BRAND_TO_GENERIC[token]
        if generic and generic not in seen:
            seen.add(generic)
            matches.append(generic)
    return matches


__all__ = [
    "is_controlled",
    "normalize_drug_name",
    "resolve_generic",
    "find_controlled_in_text",
]
