"""Settings for the ScribeMD backend.

All knobs come from env. Sensible dev defaults are baked in so a developer
can just run `uvicorn ...` and click through the demo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_csv(name: str, default: str) -> list[str]:
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    # Auth
    passkey: str = field(
        default_factory=lambda: os.environ.get(
            "SCRIBEMD_PASSKEY", "qwertyuiop24072004"
        )
    )
    signed_in_as: str = field(
        default_factory=lambda: os.environ.get("SCRIBEMD_USER_LABEL", "Dr. Adams")
    )

    # Operational state DB (SQLite). Vera holds the audit truth, not us.
    db_url: str = field(
        default_factory=lambda: os.environ.get(
            "SCRIBEMD_DB_URL",
            "sqlite+aiosqlite:///./scribemd_backend.db",
        )
    )

    # Vera target
    vera_url: str = field(
        default_factory=lambda: os.environ.get(
            "VERA_API_URL", "https://api.usevera.xyz"
        ).rstrip("/")
    )
    vera_customer_slug: str = "scribemd"

    # CORS — frontend dev server lives at 3001 to avoid clashing with the
    # main Vera frontend (which uses 3000).
    cors_origins: list[str] = field(
        default_factory=lambda: _env_csv(
            "CORS_ORIGINS", "http://localhost:3001,http://127.0.0.1:3001"
        )
    )

    # Cookie name for the session
    cookie_name: str = "scribemd_session"
    cookie_max_age_seconds: int = 60 * 60 * 8  # 8h working day

    # Approval wait — soft cap on how long a workflow blocks for a decision.
    approval_timeout_seconds: int = int(
        os.environ.get("SCRIBEMD_APPROVAL_TIMEOUT_SECONDS", "300")
    )


def get_settings() -> Settings:
    """Recompute settings on every call.

    A factory rather than a module-level singleton so tests can monkeypatch
    env vars between runs without picking up cached values.
    """
    return Settings()
