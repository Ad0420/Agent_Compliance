"""HIPAA AI Audit Trail PDF generator (Phase 4 Wave 1 A1).

The central product artifact: a regulator-ready PDF that maps each
HIPAA / Section 1557 requirement to Vera's chain-anchored evidence for
a specific Customer over a specified date range.

Public entry point::

    from app.services.pdf import generate_audit_pdf

    pdf_bytes = await generate_audit_pdf(
        db, org_id, customer_id,
        sections=["cover", "scope", "audit_controls", ...],
        branding="customer",
        date_from=date(2026, 1, 1),
        date_to=date(2026, 3, 31),
    )

Section list (rendered in this order):

  1. ``cover``                  — title page
  2. ``scope``                  — basic scope statement (A2 extends with
                                  Coverage Matrix + Merkle proofs)
  3. ``audit_controls``         — HIPAA § 164.312(b) implementation map
  4. ``hitl_evidence``          — Approval counts + reviewer roles
  5. ``demographic_monitoring`` — Section 1557 § 92.210 aggregates
  6. ``workforce_training``     — Customer-attested training records
  7. ``baa_chain``              — ScribeMD → Customer signed BAA
  8. ``technical_appendix``     — chain head hash + KMS key id + verify URL

A2 follow-up will extend ``render_scope`` with the AI Coverage Matrix and
per-decision Merkle proof attachments. A3 follow-up adds white-label cover
branding pulled from ``Organization.logo_url`` (new column).
"""
from .generator import generate_audit_pdf, PdfRenderTimeout

__all__ = ["generate_audit_pdf", "PdfRenderTimeout"]
