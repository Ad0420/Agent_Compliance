from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_queue_pdf_export_creates_job(async_client, org_and_key):
    _, raw_key, _ = org_and_key

    mock_enqueue = AsyncMock(return_value="queue-message-id")
    with patch("app.routes.export.enqueue_job", mock_enqueue):
        resp = await async_client.post(
            "/v1/export/pdf/jobs?agent_name=agent-a",
            headers={"Authorization": f"Bearer {raw_key}"},
        )

    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "queued"
    assert body["job_id"]
    mock_enqueue.assert_awaited_once_with(
        "export.pdf", {"export_job_id": body["job_id"]}
    )

    status = await async_client.get(
        f"/v1/export/jobs/{body['job_id']}",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert status.status_code == 200
    assert status.json()["filters"] == {"agent_name": "agent-a"}
