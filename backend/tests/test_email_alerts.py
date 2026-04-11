"""
Tests for tamper-detection email alerting.

Covers:
- email.py: _send(), send_tamper_alert(), send_checkpoint_alert()
- routes/organizations.py: PATCH /v1/organizations/me/alert-email
- routes/verification.py: email fires on is_valid=False
- routes/checkpoints.py: email fires on invalid checkpoint
- schemas/organization.py: AlertEmailUpdate validation
- OrganizationResponse includes alert_email field
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.models import Organization, ChainState
from app.services.auth import generate_api_key
from app.schemas.organization import AlertEmailUpdate


# ── AlertEmailUpdate schema validation ─────────────────────


def test_alert_email_update_valid():
    m = AlertEmailUpdate(alert_email="security@example.com")
    assert m.alert_email == "security@example.com"


def test_alert_email_update_none():
    m = AlertEmailUpdate(alert_email=None)
    assert m.alert_email is None


def test_alert_email_update_empty_string_becomes_none():
    m = AlertEmailUpdate(alert_email="")
    assert m.alert_email is None


def test_alert_email_update_strips_whitespace():
    m = AlertEmailUpdate(alert_email="  user@example.com  ")
    assert m.alert_email == "user@example.com"


def test_alert_email_update_invalid_no_at():
    with pytest.raises(Exception):
        AlertEmailUpdate(alert_email="notanemail")


def test_alert_email_update_invalid_no_tld():
    with pytest.raises(Exception):
        AlertEmailUpdate(alert_email="user@nodot")


# ── OrganizationResponse includes alert_email ──────────────


@pytest.mark.asyncio
async def test_get_org_returns_alert_email_field(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    resp = await async_client.get(
        "/v1/organizations/me",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "alert_email" in data
    assert data["alert_email"] is None  # not set yet


# ── PATCH /v1/organizations/me/alert-email ─────────────────


@pytest.mark.asyncio
async def test_set_alert_email(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    resp = await async_client.patch(
        "/v1/organizations/me/alert-email",
        json={"alert_email": "alerts@company.com"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["alert_email"] == "alerts@company.com"


@pytest.mark.asyncio
async def test_set_alert_email_persists(async_client, org_and_key):
    """Setting alert email must be readable via GET /organizations/me."""
    _, raw_key, _ = org_and_key
    await async_client.patch(
        "/v1/organizations/me/alert-email",
        json={"alert_email": "persist@test.com"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    resp = await async_client.get(
        "/v1/organizations/me",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.json()["alert_email"] == "persist@test.com"


@pytest.mark.asyncio
async def test_clear_alert_email(async_client, org_and_key):
    """Setting alert_email to null must clear it."""
    _, raw_key, _ = org_and_key
    # Set it first
    await async_client.patch(
        "/v1/organizations/me/alert-email",
        json={"alert_email": "to_clear@test.com"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    # Clear it
    resp = await async_client.patch(
        "/v1/organizations/me/alert-email",
        json={"alert_email": None},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["alert_email"] is None


@pytest.mark.asyncio
async def test_set_alert_email_invalid_format(async_client, org_and_key):
    """Invalid email format must be rejected with 422."""
    _, raw_key, _ = org_and_key
    resp = await async_client.patch(
        "/v1/organizations/me/alert-email",
        json={"alert_email": "not-an-email"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_set_alert_email_requires_admin(async_client, org_and_key, db_session):
    """A read-only key must not be able to set the alert email."""
    org, _, _ = org_and_key
    raw_key, _ = await generate_api_key(db_session, org.id, "readonly", ["read"])
    resp = await async_client.patch(
        "/v1/organizations/me/alert-email",
        json={"alert_email": "hacker@evil.com"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 403


# ── email.py unit tests ─────────────────────────────────────


@pytest.mark.asyncio
async def test_send_skips_when_no_api_key():
    """_send() must log a warning and skip if RESEND_API_KEY is not set."""
    from app.services.email import _send
    with patch("app.services.email.settings") as mock_settings:
        mock_settings.resend_api_key = ""
        with patch("app.services.email.logger") as mock_logger:
            await _send(subject="Test", html="<p>test</p>", to="x@example.com")
            mock_logger.warning.assert_called_once()


@pytest.mark.asyncio
async def test_send_calls_resend_when_key_configured():
    """_send() must POST to Resend when RESEND_API_KEY is set."""
    from app.services.email import _send

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": "abc123"}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.services.email.settings") as mock_settings, \
         patch("app.services.email.httpx.AsyncClient", return_value=mock_client):
        mock_settings.resend_api_key = "re_test_key"
        mock_settings.alert_from_email = "alerts@usevera.xyz"

        await _send(subject="Test", html="<p>test</p>", to="user@example.com")

        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs[0][0] == "https://api.resend.com/emails"
        body = call_kwargs[1]["json"]
        assert body["to"] == ["user@example.com"]
        assert body["subject"] == "Test"
        assert body["from"] == "alerts@usevera.xyz"


@pytest.mark.asyncio
async def test_send_logs_error_on_resend_400():
    """_send() must log error when Resend returns 4xx, without raising."""
    from app.services.email import _send

    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.text = "Forbidden"

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.services.email.settings") as mock_settings, \
         patch("app.services.email.httpx.AsyncClient", return_value=mock_client), \
         patch("app.services.email.logger") as mock_logger:
        mock_settings.resend_api_key = "re_test_key"
        mock_settings.alert_from_email = "alerts@usevera.xyz"

        await _send(subject="x", html="y", to="z@example.com")

        mock_logger.error.assert_called_once()


@pytest.mark.asyncio
async def test_send_swallows_network_exception():
    """_send() must not raise even if the HTTP call throws."""
    from app.services.email import _send

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))

    with patch("app.services.email.settings") as mock_settings, \
         patch("app.services.email.httpx.AsyncClient", return_value=mock_client):
        mock_settings.resend_api_key = "re_test_key"
        mock_settings.alert_from_email = "alerts@usevera.xyz"

        # Must not raise
        await _send(subject="x", html="y", to="z@example.com")


@pytest.mark.asyncio
async def test_send_tamper_alert_subject_contains_org_name():
    """send_tamper_alert() subject must include org name."""
    from app.services.email import send_tamper_alert

    captured = {}

    async def mock_send(subject, html, to):
        captured["subject"] = subject
        captured["html"] = html
        captured["to"] = to

    with patch("app.services.email._send", side_effect=mock_send):
        await send_tamper_alert(
            org_name="FinFast Bank",
            org_id="org-123",
            alert_email="ciso@finfast.com",
            first_invalid_seq=7,
            records_checked=42,
            detected_at="2026-04-08T12:00:00Z",
        )

    assert "FinFast Bank" in captured["subject"]
    assert "tamper" in captured["subject"].lower() or "ALERT" in captured["subject"]
    assert captured["to"] == "ciso@finfast.com"


@pytest.mark.asyncio
async def test_send_tamper_alert_html_contains_key_details():
    """send_tamper_alert() HTML body must include org, sequence, and timestamp."""
    from app.services.email import send_tamper_alert

    captured_html = {}

    async def mock_send(subject, html, to):
        captured_html["html"] = html

    with patch("app.services.email._send", side_effect=mock_send):
        await send_tamper_alert(
            org_name="AcmeCorp",
            org_id="org-xyz",
            alert_email="sec@acme.com",
            first_invalid_seq=3,
            records_checked=10,
            detected_at="2026-04-08T12:00:00Z",
        )

    html = captured_html["html"]
    assert "AcmeCorp" in html
    assert "#3" in html
    assert "2026-04-08" in html
    assert "EU AI Act Art. 73" in html


@pytest.mark.asyncio
async def test_send_tamper_alert_none_sequence():
    """send_tamper_alert() with first_invalid_seq=None must say 'unknown'."""
    from app.services.email import send_tamper_alert

    captured_html = {}

    async def mock_send(subject, html, to):
        captured_html["html"] = html

    with patch("app.services.email._send", side_effect=mock_send):
        await send_tamper_alert(
            org_name="AcmeCorp",
            org_id="org-xyz",
            alert_email="sec@acme.com",
            first_invalid_seq=None,
            records_checked=5,
            detected_at="2026-04-08T12:00:00Z",
        )

    assert "unknown" in captured_html["html"].lower()


@pytest.mark.asyncio
async def test_send_checkpoint_alert_subject_contains_count():
    """send_checkpoint_alert() subject must include the count of invalid checkpoints."""
    from app.services.email import send_checkpoint_alert

    captured = {}

    async def mock_send(subject, html, to):
        captured["subject"] = subject
        captured["html"] = html

    invalid = [
        {"checkpoint_id": "cp-111", "sequence": 5, "is_valid": False},
        {"checkpoint_id": "cp-222", "sequence": 9, "is_valid": False},
    ]

    with patch("app.services.email._send", side_effect=mock_send):
        await send_checkpoint_alert(
            org_name="TestOrg",
            org_id="org-abc",
            alert_email="ops@test.com",
            invalid_checkpoints=invalid,
            detected_at="2026-04-08T12:00:00Z",
        )

    assert "2" in captured["subject"]
    assert "#5" in captured["html"] or "cp-111" in captured["html"]


# ── Verify chain endpoint fires email on tamper ─────────────


@pytest.mark.asyncio
async def test_verify_chain_fires_email_on_tamper(async_client, org_and_key):
    """GET /v1/verify must call send_tamper_alert when chain is invalid and alert_email is set."""
    import asyncio
    _, raw_key, _ = org_and_key

    # Set alert email on the org
    await async_client.patch(
        "/v1/organizations/me/alert-email",
        json={"alert_email": "tamper@test.com"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )

    from app.schemas.verification import ChainVerificationResult
    mock_result = ChainVerificationResult(
        is_valid=False,
        records_checked=5,
        first_invalid_sequence=3,
        message="Hash mismatch at sequence 3",
    )

    # Patch send_tamper_alert as AsyncMock — let create_task run it normally
    mock_alert = AsyncMock()
    with patch("app.routes.verification.verify_chain", return_value=mock_result), \
         patch("app.routes.verification.send_tamper_alert", mock_alert):

        resp = await async_client.get(
            "/v1/verify",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert resp.status_code == 200
        assert resp.json()["is_valid"] is False
        # Flush pending tasks so create_task coroutine runs
        await asyncio.sleep(0)

    assert mock_alert.called, "send_tamper_alert should have been called"
    assert mock_alert.call_args.kwargs["alert_email"] == "tamper@test.com"
    assert mock_alert.call_args.kwargs["first_invalid_seq"] == 3


@pytest.mark.asyncio
async def test_verify_chain_no_email_when_valid(async_client, org_and_key):
    """GET /v1/verify must NOT call send_tamper_alert when chain is valid."""
    import asyncio
    _, raw_key, _ = org_and_key

    from app.schemas.verification import ChainVerificationResult
    mock_result = ChainVerificationResult(
        is_valid=True,
        records_checked=0,
        first_invalid_sequence=None,
        message="Chain valid",
    )

    mock_alert = AsyncMock()
    with patch("app.routes.verification.verify_chain", return_value=mock_result), \
         patch("app.routes.verification.send_tamper_alert", mock_alert):

        resp = await async_client.get(
            "/v1/verify",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert resp.status_code == 200
        await asyncio.sleep(0)

    mock_alert.assert_not_called()


@pytest.mark.asyncio
async def test_verify_chain_no_email_when_tamper_but_no_alert_email(async_client, org_and_key):
    """GET /v1/verify must NOT call send_tamper_alert if no alert_email is set."""
    import asyncio
    _, raw_key, _ = org_and_key

    from app.schemas.verification import ChainVerificationResult
    mock_result = ChainVerificationResult(
        is_valid=False,
        records_checked=3,
        first_invalid_sequence=1,
        message="Tampered",
    )

    mock_alert = AsyncMock()
    with patch("app.routes.verification.verify_chain", return_value=mock_result), \
         patch("app.routes.verification.send_tamper_alert", mock_alert):

        resp = await async_client.get(
            "/v1/verify",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert resp.status_code == 200
        await asyncio.sleep(0)

    mock_alert.assert_not_called()


# ── Checkpoint verify endpoint fires email on invalid ───────


@pytest.mark.asyncio
async def test_checkpoint_verify_fires_email_on_invalid(async_client, org_and_key):
    """POST /v1/verify/checkpoints/verify must call send_checkpoint_alert on invalid checkpoint."""
    import asyncio
    _, raw_key, _ = org_and_key

    # Set alert email
    await async_client.patch(
        "/v1/organizations/me/alert-email",
        json={"alert_email": "cp@test.com"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )

    invalid_results = [
        {"checkpoint_id": "cp-bad", "sequence": 2, "is_valid": False,
         "verified_at": "2026-04-08T12:00:00Z", "hash": "abc", "merkle_root": None},
    ]

    mock_cp_alert = AsyncMock()
    with patch("app.routes.checkpoints.verify_all_checkpoints", return_value=invalid_results), \
         patch("app.routes.checkpoints.send_checkpoint_alert", mock_cp_alert):

        resp = await async_client.post(
            "/v1/verify/checkpoints/verify",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert resp.status_code == 200
        assert resp.json()["all_valid"] is False
        await asyncio.sleep(0)

    assert mock_cp_alert.called
    assert mock_cp_alert.call_args.kwargs["alert_email"] == "cp@test.com"


@pytest.mark.asyncio
async def test_checkpoint_verify_no_email_when_all_valid(async_client, org_and_key):
    """POST /v1/verify/checkpoints/verify must NOT call email when all valid."""
    import asyncio
    _, raw_key, _ = org_and_key

    valid_results = [
        {"checkpoint_id": "cp-ok", "sequence": 1, "is_valid": True,
         "verified_at": "2026-04-08T12:00:00Z", "hash": "abc", "merkle_root": None},
    ]

    mock_cp_alert = AsyncMock()
    with patch("app.routes.checkpoints.verify_all_checkpoints", return_value=valid_results), \
         patch("app.routes.checkpoints.send_checkpoint_alert", mock_cp_alert):

        resp = await async_client.post(
            "/v1/verify/checkpoints/verify",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert resp.status_code == 200
        assert resp.json()["all_valid"] is True
        await asyncio.sleep(0)

    mock_cp_alert.assert_not_called()


@pytest.mark.asyncio
async def test_checkpoint_verify_no_email_without_alert_email(async_client, org_and_key):
    """POST /v1/verify/checkpoints/verify must NOT call email if no alert_email set."""
    import asyncio
    _, raw_key, _ = org_and_key

    invalid_results = [
        {"checkpoint_id": "cp-bad", "sequence": 1, "is_valid": False,
         "verified_at": "2026-04-08T12:00:00Z", "hash": "abc", "merkle_root": None},
    ]

    mock_cp_alert = AsyncMock()
    with patch("app.routes.checkpoints.verify_all_checkpoints", return_value=invalid_results), \
         patch("app.routes.checkpoints.send_checkpoint_alert", mock_cp_alert):

        resp = await async_client.post(
            "/v1/verify/checkpoints/verify",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert resp.status_code == 200
        await asyncio.sleep(0)

    mock_cp_alert.assert_not_called()
