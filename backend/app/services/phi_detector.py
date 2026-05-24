"""Production-grade PHI-shape detector for ``tenant_id`` (Phase 1 PR 5, Stream C item C3).

Replaces the temporary 5-pattern bridge guard shipped in PR #195. The
detector inspects a ``tenant_id`` string and returns a ``PHIDetection``
describing whether the value resembles known PHI shapes (SSN, dates,
names, addresses, phone, email, MRN, NPI, high-entropy obfuscation).

Design contract
---------------
* **Lean false-positive.** Over-blocking is a 422 the customer can
  rename out of; under-blocking is a PHI leak. When in doubt, match.
* **PHI-safe.** This module NEVER logs, returns, or otherwise echoes
  the input string. Callers receive ``pattern_name`` + ``severity``
  only — the value itself is the diagnostic data we're trying to
  contain.
* **No catastrophic backtracking.** Every regex below uses bounded
  quantifiers and anchored alternations. No nested ``+``/``*`` over
  the same character class, no ``(.*)+`` constructions. The detector
  runs on every incoming action so the cost has to stay flat.
* **Stateless.** Module-level compiled regexes; ``detect_phi_shape``
  takes a string in, returns a dataclass out.

Returned ``severity`` semantics
-------------------------------
* ``"high"`` — definite PHI shape (SSN, dates, full names, MRN).
* ``"medium"`` — strong PHI signal but with non-trivial false-positive
  risk (high-entropy alphanumerics, address shapes that share form
  with generic opaque IDs).
* ``"low"`` — suspicious shape worth flagging but the call-site may
  choose to permit (NPI is 10 raw digits which collides with many
  legitimate IDs).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Optional


# ── Result type ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PHIDetection:
    """Outcome of running ``detect_phi_shape`` against a string.

    Attributes
    ----------
    matched
        True if at least one PHI-shape pattern fired.
    pattern_name
        Stable identifier for the first-matching family
        (``"ssn"``, ``"date_ymd"``, ``"name_pair"``, ``"address"``,
        ``"phone"``, ``"email"``, ``"mrn"``, ``"npi"``,
        ``"high_entropy"``). ``None`` when ``matched is False``.
    severity
        ``"high"`` for definite PHI, ``"medium"`` for strong signal,
        ``"low"`` for suspicious-but-noisy. ``"low"`` when
        ``matched is False`` so callers can branch on severity safely
        even on the no-match path.
    """

    matched: bool
    pattern_name: Optional[str]
    severity: Literal["high", "medium", "low"]


# ── Pattern families ───────────────────────────────────────────────────────
# Each family below contributes one or more regex / numeric checks. The
# detector tries them in order and returns the FIRST match — order is
# tuned so the most-confident "this is PHI" families fire before the
# noisier ones. The order should also place tighter patterns before
# looser ones so a value like ``john_doe_19720314`` is reported as
# ``date_ymd`` (the more diagnostic family) rather than ``name_pair``.

# SSN — 3-2-4 with optional separators OR raw 9-digit run. The raw
# 9-digit version is broader so we keep it AFTER the separated form to
# preserve the diagnostic name when both would match.
_SSN_SEPARATED_RE = re.compile(r"\d{3}[-_ /]\d{2}[-_ /]\d{4}")
_SSN_RUN_RE = re.compile(r"(?<!\d)\d{9}(?!\d)")

# Phone (US 10-digit), optionally with +1 prefix. Bounded so we don't
# match arbitrarily long digit runs.
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?1[-_ ]?)?\d{3}[-_ ]?\d{3}[-_ ]?\d{4}(?!\d)"
)

# Date with explicit separators.
_DATE_YMD_SEP_RE = re.compile(r"(?<!\d)\d{4}[-_/]\d{2}[-_/]\d{2}(?!\d)")
_DATE_MDY_SEP_RE = re.compile(r"(?<!\d)\d{2}[-_/]\d{2}[-_/]\d{4}(?!\d)")
# DD-MMM-YYYY (e.g. ``15-Mar-1972``). Use a fixed list of month
# abbreviations so we don't accept ``15-Foo-1972``.
_DATE_DMMMY_RE = re.compile(
    r"(?<![A-Za-z\d])\d{1,2}[-_/]"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"[-_/]\d{4}(?![A-Za-z\d])",
    re.IGNORECASE,
)
# Bare 8-digit run — checked numerically by ``_eight_digits_is_date``.
_EIGHT_DIGIT_RE = re.compile(r"(?<!\d)(\d{8})(?!\d)")

# Email — RFC-loose. The user-facing pattern is enough: ``foo@bar.tld``.
_EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"
)

# MRN — opaque ID of length 7+ with ``MRN`` or ``mrn`` prefix/suffix.
# We require the literal token "mrn" adjacent to the digits so generic
# strings like ``customer_mrn_team`` (no digits adjacent to ``mrn``)
# don't trigger.
_MRN_RE = re.compile(
    r"(?:(?<![A-Za-z])mrn[-_]?\d{7,}|\d{7,}[-_]?mrn(?![A-Za-z]))",
    re.IGNORECASE,
)

# Name pair — two or more Capitalized tokens separated by space, hyphen,
# or underscore. ``John_Doe``, ``Jane Smith``, ``Mary-Lou-Smith`` all
# match; ``acme_corp`` (lowercase) does not.
_NAME_PAIR_RE = re.compile(
    r"(?<![A-Za-z])[A-Z][a-z]+(?:[\s_\-][A-Z][a-z]+)+(?![A-Za-z])"
)

# Address — street suffix (St, Ave, Rd, ...) anywhere as a standalone
# token. We require a word boundary or separator on both sides so
# ``Stuart`` and ``First`` do NOT match. Suffix-only patterns also fire
# when preceded by digits (``123 Main St`` → matches the suffix form
# AND the digit+street form below).
_ADDRESS_SUFFIX_RE = re.compile(
    r"(?<![A-Za-z])(?:St|Ave|Rd|Blvd|Ln|Dr|Way|Ct|Pl|Street|Avenue|Road|"
    r"Boulevard|Lane|Drive|Court|Place)(?![A-Za-z])",
    re.IGNORECASE,
)
# Digit run + separator + Capitalised word — ``123 Main``, ``1234_Maple``.
# Bounded digit length to avoid colliding with simple opaque IDs like
# ``rev_42``.
_ADDRESS_NUMBERED_RE = re.compile(
    r"(?<!\d)\d{1,6}[\s_][A-Z][a-z]+"
)

# NPI — exactly 10 raw digits. The spec note acknowledges 10 raw digits
# have non-trivial collision risk with generic IDs, so we flag at LOW
# severity only. Anchored against digit boundaries so phone-shaped
# 10-digit runs are still caught by the phone regex first (phone has
# separators-tolerant form; raw 10-digit gets caught here).
_NPI_RE = re.compile(r"(?<!\d)\d{10}(?!\d)")

# High-entropy alphanumeric — length ≥ 12 with at least one lowercase,
# one uppercase, and one digit. Catches obfuscated PHI like
# ``Js5g8Lpq2bN``. Also catches hex-y strings like ``a1b2c3d4e5f6``
# (the spec's example) via the length-12 / mixed case+digit gate.
# Pure-hex of length 12 (no uppercase) is its own branch.
_HEX_ID_RE = re.compile(r"(?<![A-Za-z0-9])[a-f0-9]{12,}(?![A-Za-z0-9])")


def _eight_digits_is_date(digits: str) -> bool:
    """True if 8 digits parse as plausible YYYYMMDD or MMDDYYYY.

    Year bounds 1900-2050, month 1-12, day 1-31. Generous on day-of-
    month — calendar correctness (Feb 30 etc.) doesn't matter; we're
    pattern-matching, not validating dates.
    """
    # YYYYMMDD
    y1, m1, d1 = int(digits[0:4]), int(digits[4:6]), int(digits[6:8])
    if 1900 <= y1 <= 2050 and 1 <= m1 <= 12 and 1 <= d1 <= 31:
        return True
    # MMDDYYYY
    m2, d2, y2 = int(digits[0:2]), int(digits[2:4]), int(digits[4:8])
    if 1900 <= y2 <= 2050 and 1 <= m2 <= 12 and 1 <= d2 <= 31:
        return True
    return False


def _has_high_entropy_mixed(s: str) -> bool:
    """True if ``s`` contains a 12+ char run mixing upper, lower, digits.

    Walks the string once looking for the longest alphanumeric run, then
    checks the character-class mix on that run. Cheap and predictable;
    no regex catastrophic-backtracking risk.
    """
    if len(s) < 12:
        return False
    run_start = None
    for i, ch in enumerate(s):
        if ch.isalnum():
            if run_start is None:
                run_start = i
        else:
            if run_start is not None:
                run = s[run_start:i]
                if (
                    len(run) >= 12
                    and any(c.isupper() for c in run)
                    and any(c.islower() for c in run)
                    and any(c.isdigit() for c in run)
                ):
                    return True
                run_start = None
    # Tail run.
    if run_start is not None:
        run = s[run_start:]
        if (
            len(run) >= 12
            and any(c.isupper() for c in run)
            and any(c.islower() for c in run)
            and any(c.isdigit() for c in run)
        ):
            return True
    return False


def detect_phi_shape(value: str) -> PHIDetection:
    """Return a ``PHIDetection`` describing whether ``value`` looks PHI-shaped.

    Never raises. ``None`` / empty inputs return a no-match detection
    so callers can pass through optional tenant_id values without
    a None-check.

    Order of checks is fixed: tighter / more-diagnostic patterns first,
    so a string like ``patient_19720314`` reports ``date_ymd`` rather
    than something noisier. Returns on the first match.
    """
    if not value:
        return PHIDetection(matched=False, pattern_name=None, severity="low")

    # SSN — explicit separators first (more specific name), then raw run.
    if _SSN_SEPARATED_RE.search(value):
        return PHIDetection(matched=True, pattern_name="ssn", severity="high")
    if _SSN_RUN_RE.search(value):
        return PHIDetection(matched=True, pattern_name="ssn", severity="high")

    # Phone — bounded 10-digit US shape. Note: a raw 9-digit run would
    # have matched SSN above; a raw 10-digit run that DOESN'T match the
    # phone-with-separator shape falls through to NPI below.
    if _PHONE_RE.search(value):
        return PHIDetection(matched=True, pattern_name="phone", severity="high")

    # Email.
    if _EMAIL_RE.search(value):
        return PHIDetection(matched=True, pattern_name="email", severity="high")

    # Dates with separators.
    if _DATE_YMD_SEP_RE.search(value):
        return PHIDetection(matched=True, pattern_name="date_ymd", severity="high")
    if _DATE_MDY_SEP_RE.search(value):
        return PHIDetection(matched=True, pattern_name="date_mdy", severity="high")
    if _DATE_DMMMY_RE.search(value):
        return PHIDetection(matched=True, pattern_name="date_dmmmy", severity="high")

    # Bare 8-digit YYYYMMDD / MMDDYYYY — numeric check.
    for m in _EIGHT_DIGIT_RE.finditer(value):
        if _eight_digits_is_date(m.group(1)):
            return PHIDetection(matched=True, pattern_name="date_ymd", severity="high")

    # MRN.
    if _MRN_RE.search(value):
        return PHIDetection(matched=True, pattern_name="mrn", severity="high")

    # Address — digit + capitalised word OR explicit street suffix.
    if _ADDRESS_NUMBERED_RE.search(value):
        return PHIDetection(matched=True, pattern_name="address", severity="medium")
    if _ADDRESS_SUFFIX_RE.search(value):
        return PHIDetection(matched=True, pattern_name="address", severity="medium")

    # Name pair — two or more Capitalized tokens with separator.
    if _NAME_PAIR_RE.search(value):
        return PHIDetection(matched=True, pattern_name="name_pair", severity="high")

    # NPI — 10 raw digits. LOW severity per the spec note (collides with
    # legitimate IDs). Comes AFTER the phone check so phone-with-
    # separator wins the more-diagnostic label.
    if _NPI_RE.search(value):
        return PHIDetection(matched=True, pattern_name="npi", severity="low")

    # Pure-hex 12+ chars.
    if _HEX_ID_RE.search(value):
        return PHIDetection(matched=True, pattern_name="high_entropy", severity="medium")

    # High-entropy mixed alphanumeric.
    if _has_high_entropy_mixed(value):
        return PHIDetection(matched=True, pattern_name="high_entropy", severity="medium")

    return PHIDetection(matched=False, pattern_name=None, severity="low")
