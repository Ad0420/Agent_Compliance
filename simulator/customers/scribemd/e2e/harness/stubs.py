"""In-memory fakes for the LLM providers and the Vera client.

We duplicate the fakes here rather than importing from
`simulator.customers.scribemd.backend.tests.test_smoke` because:

  * pytest's `tests/` package isn't on the install path of a regular
    `pip install` of the simulator — depending on it from a non-test
    runtime would force the harness to know about pytest's layout.
  * the test factories there are tied to pytest fixtures (resetting
    module singletons, etc.) — what we need is just the fake classes
    and the two factory functions, with no test-runner state.

Keeping this small and explicit means the e2e harness has a clean
dependency graph: it imports the production backend and these stubs,
nothing else.

The fakes here exactly mirror the protocol surface that
`workflow_runner._run_workflow` calls into — `record_action`,
`request_approval`, `_client.post`, `wait_for_approval`, `close`. If the
backend grows new methods on the Vera client, we'll need to extend the
fake here too.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Optional


class FakeLLMResponse:
    """Mirrors the shape of a real LLM provider's response object."""

    def __init__(self, text: str, model: str):
        self.text = text
        self.input_tokens = 10
        self.output_tokens = 20
        self.model = model
        self.duration_ms = 5


class FakeOpenAILLM:
    """Returns a deterministic SOAP note for the note-drafter agent."""

    model = "gpt-4o-mini-fake"

    def chat(self, system: str, user: str, max_tokens: int = 512) -> FakeLLMResponse:
        return FakeLLMResponse(
            text=(
                "SUBJECTIVE: Patient reports severe epigastric pain.\n"
                "OBJECTIVE: Tender to palpation, guarding present.\n"
                "ASSESSMENT: Possible: acute pancreatitis.\n"
                "PLAN: NPO, IV fluids, ondansetron, admit for observation."
            ),
            model=self.model,
        )


class FakeAnthropicLLM:
    """Returns a deterministic JSON orders payload for the extractor agent."""

    model = "claude-fake"

    def chat(self, system: str, user: str, max_tokens: int = 512) -> FakeLLMResponse:
        return FakeLLMResponse(
            text=json.dumps(
                {
                    "diagnoses": ["Acute pancreatitis"],
                    "medication_orders": ["Ondansetron 4mg IV q6h PRN"],
                    "lab_or_imaging_orders": ["Lipase", "CBC", "Abdominal US"],
                }
            ),
            model=self.model,
        )


def fake_llm_factory(name: str):
    if name == "openai":
        return FakeOpenAILLM()
    if name == "anthropic":
        return FakeAnthropicLLM()
    raise ValueError(name)


class FakeVeraClient:
    """In-memory Vera client.

    Records every action for later inspection and resolves approvals
    when the route handler calls `.post(...)`. All instances share an
    approval registry so a request from one agent's client is visible
    to whichever client the route handler ends up holding.
    """

    _approvals: dict[str, dict] = {}
    _approval_lock = threading.Lock()

    def __init__(
        self,
        *,
        agent_name: str,
        model_id: Optional[str] = None,
        framework: Optional[str] = None,
    ):
        self.agent_name = agent_name
        self.model_id = model_id
        self.framework = framework
        self.records: list[dict] = []

    def record_action(self, **kwargs) -> dict:
        rec = {
            "id": f"rec_{uuid.uuid4().hex[:12]}",
            "sequence_number": len(self.records) + 1,
            **kwargs,
        }
        self.records.append(rec)
        return rec

    def request_approval(self, **kwargs) -> dict:
        approval_id = f"apr_{uuid.uuid4().hex[:12]}"
        approval = {
            "id": approval_id,
            "status": "pending",
            "context": kwargs.get("context", {}),
            "risk_tier": kwargs.get("risk_tier"),
        }
        with FakeVeraClient._approval_lock:
            FakeVeraClient._approvals[approval_id] = approval
        return approval

    @property
    def _client(self):  # mimics the SDK's underlying httpx client surface
        return self

    def post(self, path: str, json: dict | None = None):  # noqa: A002
        # Match _decide_approval_via_api's call shape: /v1/approvals/<id>/decide
        approval_id = path.split("/")[-2]
        with FakeVeraClient._approval_lock:
            approval = FakeVeraClient._approvals.get(approval_id)
            if approval is not None and json is not None:
                approval["status"] = (
                    "approved" if json["decision"] == "approve" else "rejected"
                )
                approval["approver"] = json["approver"]
                approval["note"] = json.get("note")

        class _Resp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self_inner):  # noqa: N805
                return approval

        return _Resp()

    def wait_for_approval(
        self,
        approval_id: str,
        timeout: float = 10.0,
        poll_interval: float = 0.5,
    ) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with FakeVeraClient._approval_lock:
                approval = FakeVeraClient._approvals.get(approval_id, {})
            if approval.get("status") in ("approved", "rejected", "expired"):
                if approval["status"] == "rejected":
                    from vera import ApprovalRejectedError

                    raise ApprovalRejectedError(approval)
                return approval
            time.sleep(poll_interval)
        raise TimeoutError(f"approval {approval_id} did not resolve in {timeout}s")

    def close(self) -> None:
        pass


def fake_vera_factory(
    *,
    agent_name: str,
    model_id: Optional[str] = None,
    framework: Optional[str] = None,
):
    return FakeVeraClient(
        agent_name=agent_name,
        model_id=model_id,
        framework=framework,
    )
