"""Private test-only hooks for the Vera SDK.

The module name and prefix (underscore) mark this as private API. It is
NOT covered by SDK stability guarantees. Customers should not import
from this module. The hooks here are wired up so the test suite can
reset once-per-process global state between tests without exposing the
reset surface as part of the public Redactor API.
"""

from __future__ import annotations

from . import redaction as _redaction


def _reset_baa_reminder_for_tests() -> None:
    """Clear the once-per-process BAA-reminder flag.

    Re-exports the original (now private-by-convention) helper that
    lives next to the BAA reminder itself in ``vera.redaction``.
    Tests should import from ``vera._test_hooks`` rather than reaching
    into ``vera.redaction`` directly.
    """
    _redaction._BAA_REMINDER_LOGGED = False


__all__ = ["_reset_baa_reminder_for_tests"]
