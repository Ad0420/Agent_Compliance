"""Boots the ScribeMD FastAPI backend on port 8001 with stubs installed.

Run as a script (Playwright's `webServer.command` shells this out):

    python -m simulator.customers.scribemd.e2e.harness.server

The harness:

  * Sets the env vars the backend reads (passkey, db url, CORS, approval
    timeout). The DB URL gets a fresh path per process so two consecutive
    runs don't share state.
  * Installs the in-memory Vera + LLM factories from `stubs.py` via the
    backend's `install_test_factories(...)` hook.
  * Starts uvicorn programmatically. We import the FastAPI app *after*
    env vars are set so `get_settings()` and `_ensure_engine()` see the
    test config.

The harness is deliberately thin — no CLI flags, no host overrides. The
e2e suite is the only consumer; if you need a different shape, build a
new harness rather than overloading this one.
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path


def _set_env_defaults() -> None:
    """Populate env vars the backend reads at startup.

    `setdefault` so a developer can override individual values from the
    parent shell without editing this file.
    """
    db_path = f"/tmp/scribemd_e2e_{uuid.uuid4().hex}.db"
    defaults = {
        "SCRIBEMD_PASSKEY": "test-passkey-123",
        "SCRIBEMD_DB_URL": f"sqlite+aiosqlite:///{db_path}",
        "CORS_ORIGINS": "http://localhost:3001,http://127.0.0.1:3001",
        # Tight timeout so even if a test bails before deciding, the
        # workflow terminates and the process can shut down cleanly.
        "SCRIBEMD_APPROVAL_TIMEOUT_SECONDS": "10",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


def _ensure_repo_on_path() -> None:
    """When run via `python -m simulator.customers.scribemd.e2e.harness.server`
    Python already has the repo root on `sys.path`. When run as a plain
    script (e.g. `python harness/server.py`) it doesn't — add it.
    """
    here = Path(__file__).resolve()
    # e2e/harness/server.py → e2e/harness → e2e → scribemd → customers → simulator → repo root
    repo_root = here.parents[5]
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)


def main() -> None:
    _ensure_repo_on_path()
    _set_env_defaults()

    # Import-after-env: the backend reads SCRIBEMD_DB_URL etc. on first
    # access, so we want the env in place before `create_app()` runs.
    import uvicorn

    from simulator.customers.scribemd.backend import workflow_runner
    from simulator.customers.scribemd.backend.main import create_app
    from simulator.customers.scribemd.e2e.harness.stubs import (
        fake_llm_factory,
        fake_vera_factory,
    )

    workflow_runner.install_test_factories(
        vera_factory=fake_vera_factory,
        llm_factory=fake_llm_factory,
    )

    app = create_app()

    port = int(os.environ.get("SCRIBEMD_E2E_PORT", "8001"))
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        log_level=os.environ.get("SCRIBEMD_E2E_LOG_LEVEL", "warning"),
    )


if __name__ == "__main__":
    main()
