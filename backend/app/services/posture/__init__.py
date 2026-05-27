"""Compliance Posture service (Phase 4 Wave 1 PR B1).

Computes the six universal posture dimensions on demand. No
``posture_snapshots`` table; no cron; no caching layer. The F7
deferral re-enters only at 1M actions OR p99 > 500ms — see
``policy-engine-mvp.md §Compliance Posture``.
"""

from .compute import compute_posture

__all__ = ["compute_posture"]
