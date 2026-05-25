"""Phase 2 Wave 2C PR A4 — reviewer role hierarchy.

Maps reviewer-role strings to numeric levels so the
``POST /v1/reviews/{review_id}/complete`` endpoint can decide whether
the reviewer presenting credentials actually outranks the
``required_role`` stashed on the Approval by Wave 2B PR A2.

Design rules
------------

* **Fail-closed on unknown reviewer roles.** Any reviewer-supplied role
  string that is not in ``_ROLE_LEVELS`` is treated as insufficient,
  even when ``required_role`` is also missing from the table. We never
  silently pass an unrecognised role — the alternative (default level 0)
  would let a typo such as ``"attendng_physician"`` clear a
  ``dea_authorized`` requirement.

* **``required_role=None`` means "any human"**. A2 leaves the field
  blank for gates that don't pin a specific role; the reviewer still
  needs to identify themselves as a known role (so an unrecognised
  string still fails — see fail-closed above).

* **Numeric levels, not enum subset checks.** A hierarchy expressed as
  integers extends cleanly when packs introduce new roles (e.g.
  ``cardiology_attending`` at level 35). The downside — a higher-level
  role automatically passes a lower-level requirement — is intentional
  and matches the way clinical sign-off chains already work.

Future hooks (out of scope for A4):

* Per-tenant role mappings (today the table is global).
* Role aliases learned from BAA scope (``rn`` and ``nurse`` are the only
  aliases shipped here).
* Cryptographic role attestation — A4 trusts the reviewer-supplied
  string; a follow-up PR can layer a signed claim from the reviewer's
  IdP.
"""

from __future__ import annotations


# Numeric levels. Higher number = more privileged.
#
# NOTE on aliases: ``rn`` is exposed as a synonym for ``nurse`` because
# our clinical design partners use both interchangeably. If we ever need
# to distinguish (e.g. LPN below RN), break the alias and add a new
# row — don't reorder.
_ROLE_LEVELS: dict[str, int] = {
    "any_human": 0,
    "nurse": 10,
    "rn": 10,                 # alias of nurse
    "physician": 20,
    "attending_physician": 30,
    "dea_authorized": 40,     # gated by DEA registration
    "medical_director": 50,
    "compliance_officer": 60,
}


def is_role_sufficient(reviewer_role: str, required_role: str | None) -> bool:
    """Return True iff ``reviewer_role`` outranks ``required_role``.

    Parameters
    ----------
    reviewer_role
        The role the human reviewer claims when calling
        ``POST /v1/reviews/{review_id}/complete``. MUST be present in
        ``_ROLE_LEVELS`` — unknown strings return False (fail-closed).
    required_role
        The role the gate pinned on the Approval's ``context``
        (Wave 2B PR A2 writes this). ``None`` is interpreted as
        ``"any_human"`` — any *recognised* human role passes.

    Returns
    -------
    bool
        True when the reviewer's level is greater than or equal to the
        requirement. False when either side is unknown.

    Examples
    --------
    >>> is_role_sufficient("attending_physician", "attending_physician")
    True
    >>> is_role_sufficient("nurse", "attending_physician")
    False
    >>> is_role_sufficient("medical_director", "dea_authorized")
    True
    >>> is_role_sufficient("attendng_physician", "physician")  # typo
    False
    >>> is_role_sufficient("attending_physician", None)
    True
    >>> is_role_sufficient("not_a_real_role", None)
    False
    """
    reviewer_level = _ROLE_LEVELS.get(reviewer_role)
    if reviewer_level is None:
        # Fail-closed: a role string we don't recognise NEVER passes,
        # even when the gate didn't pin a specific requirement. The
        # alternative (default level 0) would silently approve typos.
        return False

    # ``None`` from the gate means "any recognised human is fine".
    if required_role is None:
        return True

    required_level = _ROLE_LEVELS.get(required_role)
    if required_level is None:
        # If the gate pinned a role we don't know about, fail-closed
        # again. This protects against drift between pack authors and
        # this table.
        return False

    return reviewer_level >= required_level


__all__ = ["is_role_sufficient"]
