"""Boots the TriageGuard FastAPI backend on port 8002 with stubs installed.

Run as a script (Playwright's `webServer.command` shells this out):

    python -m simulator.customers.triageguard.e2e.harness.server

The harness:

  * Sets the env vars the backend reads (passkey, db url, CORS, review
    timeout). The DB URL gets a fresh path per process so two consecutive
    runs don't share state.
  * Imports `FakeOpenAILLM`, `FakeAnthropicLLM`, `FakeVeraClient` from
    the existing pytest smoke at
    `simulator.customers.triageguard.backend.tests.test_smoke` — the
    fakes already encode the contract (chest-pain narrative trips a
    red-flag with `recommended_override="ER"`), so the e2e and pytest
    surfaces share one set of canned responses.

    (ScribeMD's harness opted for harness-local stubs instead; we
    deliberately go the importing route here for parity with the
    contract — when the contract moves, the smoke moves, and so do we.)
  * Installs the in-memory factories via the backend's
    `workflow_runner.install_test_factories(...)` hook.
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
    db_path = f"/tmp/triageguard_e2e_{uuid.uuid4().hex}.db"
    defaults = {
        "TRIAGEGUARD_PASSKEY": "e2e-passkey-123",
        "TRIAGEGUARD_DB_URL": f"sqlite+aiosqlite:///{db_path}",
        "CORS_ORIGINS": "http://localhost:3002,http://127.0.0.1:3002",
        # Long enough to give the test time to render the gate and
        # click "Escalate to ER" through Next.js dev-mode compile +
        # SSE delivery, but short enough that a hung test still
        # terminates cleanly. (Brief suggested 10s; real-browser
        # latency forced 30s.)
        "TRIAGEGUARD_REVIEW_TIMEOUT_SECONDS": "30",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


def _ensure_repo_on_path() -> None:
    """When run via `python -m simulator.customers.triageguard.e2e.harness.server`
    Python already has the repo root on `sys.path`. When run as a plain
    script (e.g. `python harness/server.py`) it doesn't — add it.
    """
    here = Path(__file__).resolve()
    # e2e/harness/server.py → e2e/harness → e2e → triageguard → customers → simulator → repo root
    repo_root = here.parents[5]
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)


def main() -> None:
    _ensure_repo_on_path()
    _set_env_defaults()

    # Import-after-env: the backend reads TRIAGEGUARD_DB_URL etc. on
    # first access, so we want the env in place before `create_app()`
    # runs.
    import uvicorn

    from simulator.customers.triageguard.backend import workflow_runner
    from simulator.customers.triageguard.backend.main import create_app

    # Reach into the pytest smoke for the fakes — they already encode
    # the canonical fixture behaviour (chest pain trips the red-flag,
    # recommends ER override). One source of truth for both e2e and
    # the pytest suite.
    from simulator.customers.triageguard.backend.tests.test_smoke import (
        FakeAnthropicLLM,
        FakeOpenAILLM,
        FakeVeraClient,
    )

    def vera_factory(*, agent_name, model_id=None, framework=None):
        return FakeVeraClient(
            agent_name=agent_name,
            model_id=model_id,
            framework=framework,
        )

    def llm_factory(name: str):
        if name == "openai":
            return FakeOpenAILLM()
        if name == "anthropic":
            return FakeAnthropicLLM()
        raise ValueError(name)

    workflow_runner.install_test_factories(
        vera_factory=vera_factory,
        llm_factory=llm_factory,
    )

    app = create_app()

    port = int(os.environ.get("TRIAGEGUARD_E2E_PORT", "8002"))
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        log_level=os.environ.get("TRIAGEGUARD_E2E_LOG_LEVEL", "warning"),
    )


if __name__ == "__main__":
    main()
