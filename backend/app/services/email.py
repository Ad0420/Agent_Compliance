"""
Async email alerting via Resend (https://resend.com).

Gracefully skips sending if RESEND_API_KEY is not configured.
Request paths should enqueue these through services.jobs so production
deliveries survive process restarts.
"""
import html as html_module
import logging

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"


async def _send(subject: str, html: str, to: str) -> None:
    """Low-level send via Resend API. Logs and swallows errors."""
    if not settings.resend_api_key:
        logger.warning("RESEND_API_KEY not set — skipping tamper alert email to %s", to)
        return

    payload = {
        "from": settings.alert_from_email,
        "to": [to],
        "subject": subject,
        "html": html,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                RESEND_URL,
                json=payload,
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            )
            if resp.status_code >= 400:
                logger.error(
                    "Resend API error %s: %s", resp.status_code, resp.text[:200]
                )
            else:
                logger.info("Tamper alert email sent to %s (Resend id=%s)", to, resp.json().get("id"))
    except Exception as exc:
        logger.exception("Failed to send email to %s: %s", to, exc)


async def send_tamper_alert(
    *,
    org_name: str,
    org_id: str,
    alert_email: str,
    first_invalid_seq: int | None,
    records_checked: int,
    detected_at: str,
) -> None:
    """Send an email when chain verification detects tampering."""
    seq_text = f"#{first_invalid_seq}" if first_invalid_seq is not None else "unknown"
    subject = f"[Vera] ALERT: Audit chain tampering detected — {org_name}"
    html = f"""
<div style="font-family:sans-serif;max-width:560px;margin:0 auto;padding:24px">
  <div style="background:#ef4444;color:#fff;border-radius:8px;padding:16px 20px;margin-bottom:24px">
    <strong style="font-size:16px">&#x26A0;&#xFE0F; Audit Chain Tampering Detected</strong>
  </div>

  <p style="margin:0 0 16px;color:#374151">
    Vera detected that the audit chain for <strong>{org_name}</strong> has been tampered with.
    One or more records have been modified after they were written.
  </p>

  <table style="width:100%;border-collapse:collapse;margin-bottom:24px">
    <tr style="border-bottom:1px solid #e5e7eb">
      <td style="padding:10px 0;color:#6b7280;width:160px">Organization</td>
      <td style="padding:10px 0;font-weight:600">{org_name}</td>
    </tr>
    <tr style="border-bottom:1px solid #e5e7eb">
      <td style="padding:10px 0;color:#6b7280">Org ID</td>
      <td style="padding:10px 0;font-family:monospace;font-size:13px">{org_id}</td>
    </tr>
    <tr style="border-bottom:1px solid #e5e7eb">
      <td style="padding:10px 0;color:#6b7280">First invalid sequence</td>
      <td style="padding:10px 0;font-weight:600;color:#ef4444">{seq_text}</td>
    </tr>
    <tr style="border-bottom:1px solid #e5e7eb">
      <td style="padding:10px 0;color:#6b7280">Records checked</td>
      <td style="padding:10px 0">{records_checked}</td>
    </tr>
    <tr>
      <td style="padding:10px 0;color:#6b7280">Detected at</td>
      <td style="padding:10px 0;font-family:monospace;font-size:13px">{detected_at}</td>
    </tr>
  </table>

  <p style="color:#374151;margin:0 0 8px">
    <strong>Required action:</strong> Investigate immediately. Under EU AI Act Art. 73,
    serious incidents must be reported to the relevant Market Surveillance Authority
    within 15 days (2 days if safety-critical).
  </p>

  <p style="color:#6b7280;font-size:13px;margin:24px 0 0;border-top:1px solid #e5e7eb;padding-top:16px">
    This alert was sent by <strong>Vera</strong> &mdash; AI Compliance Audit Trail.<br>
    You are receiving this because {alert_email} is configured as the alert address for {org_name}.
  </p>
</div>
"""
    await _send(subject=subject, html=html, to=alert_email)


async def send_policy_violation_alert(
    *,
    org_name: str,
    org_id: str,
    alert_email: str,
    policy_name: str,
    condition_type: str,
    severity: str,
    record_id: str,
    context: dict,
) -> None:
    """Send an email when a policy with action='email' is triggered."""
    severity_colors = {
        "critical": "#dc2626",
        "high": "#ea580c",
        "medium": "#d97706",
        "low": "#65a30d",
    }
    color = severity_colors.get(severity, "#6b7280")
    subject = f"[Vera] Policy Violation ({severity.upper()}): {policy_name} — {org_name}"

    e = html_module.escape  # shorthand for escaping user-controlled values
    context_rows = ""
    for k, v in context.items():
        context_rows += f"""
    <tr style="border-bottom:1px solid #e5e7eb">
      <td style="padding:8px 0;color:#6b7280;width:160px">{e(str(k))}</td>
      <td style="padding:8px 0;font-family:monospace;font-size:13px">{e(str(v))}</td>
    </tr>"""

    html = f"""
<div style="font-family:sans-serif;max-width:560px;margin:0 auto;padding:24px">
  <div style="background:{color};color:#fff;border-radius:8px;padding:16px 20px;margin-bottom:24px">
    <strong style="font-size:16px">&#x26A0;&#xFE0F; Policy Violation Detected ({e(severity.upper())})</strong>
  </div>

  <p style="margin:0 0 16px;color:#374151">
    A policy rule was triggered for <strong>{e(org_name)}</strong>.
  </p>

  <table style="width:100%;border-collapse:collapse;margin-bottom:24px">
    <tr style="border-bottom:1px solid #e5e7eb">
      <td style="padding:10px 0;color:#6b7280;width:160px">Policy</td>
      <td style="padding:10px 0;font-weight:600">{e(policy_name)}</td>
    </tr>
    <tr style="border-bottom:1px solid #e5e7eb">
      <td style="padding:10px 0;color:#6b7280">Condition</td>
      <td style="padding:10px 0">{e(condition_type)}</td>
    </tr>
    <tr style="border-bottom:1px solid #e5e7eb">
      <td style="padding:10px 0;color:#6b7280">Severity</td>
      <td style="padding:10px 0;font-weight:600;color:{color}">{e(severity.upper())}</td>
    </tr>
    <tr style="border-bottom:1px solid #e5e7eb">
      <td style="padding:10px 0;color:#6b7280">Record ID</td>
      <td style="padding:10px 0;font-family:monospace;font-size:13px">{e(record_id)}</td>
    </tr>
    <tr style="border-bottom:1px solid #e5e7eb">
      <td style="padding:10px 0;color:#6b7280">Organization</td>
      <td style="padding:10px 0">{e(org_name)} ({e(org_id)})</td>
    </tr>
  </table>

  <p style="margin:0 0 8px;font-weight:600;color:#374151">Context</p>
  <table style="width:100%;border-collapse:collapse;margin-bottom:24px">
    {context_rows}
  </table>

  <p style="color:#6b7280;font-size:13px;margin:24px 0 0;border-top:1px solid #e5e7eb;padding-top:16px">
    This alert was sent by <strong>Vera</strong> &mdash; AI Compliance Audit Trail.<br>
    You are receiving this because {e(alert_email)} is configured as the alert address for {e(org_name)}.
  </p>
</div>
"""
    await _send(subject=subject, html=html, to=alert_email)


async def send_checkpoint_alert(
    *,
    org_name: str,
    org_id: str,
    alert_email: str,
    invalid_checkpoints: list[dict],
    detected_at: str,
) -> None:
    """Send an email when checkpoint verification finds invalid checkpoints."""
    count = len(invalid_checkpoints)
    subject = f"[Vera] ALERT: {count} invalid checkpoint(s) detected — {org_name}"

    rows = ""
    for cp in invalid_checkpoints:
        cp_id = cp.get("checkpoint_id", "?")
        seq = cp.get("sequence", "?")
        rows += f"""
        <tr style="border-bottom:1px solid #e5e7eb">
          <td style="padding:8px 0;font-family:monospace;font-size:12px">{cp_id[:16]}…</td>
          <td style="padding:8px 0">#{seq}</td>
        </tr>"""

    html = f"""
<div style="font-family:sans-serif;max-width:560px;margin:0 auto;padding:24px">
  <div style="background:#ef4444;color:#fff;border-radius:8px;padding:16px 20px;margin-bottom:24px">
    <strong style="font-size:16px">&#x26A0;&#xFE0F; Invalid Checkpoint(s) Detected</strong>
  </div>

  <p style="margin:0 0 16px;color:#374151">
    <strong>{count}</strong> checkpoint(s) for <strong>{org_name}</strong> failed signature
    verification. This may indicate tampering or key rotation issues.
  </p>

  <table style="width:100%;border-collapse:collapse;margin-bottom:24px">
    <tr style="border-bottom:2px solid #e5e7eb">
      <th style="padding:8px 0;text-align:left;color:#6b7280;font-size:12px;text-transform:uppercase">Checkpoint ID</th>
      <th style="padding:8px 0;text-align:left;color:#6b7280;font-size:12px;text-transform:uppercase">Sequence</th>
    </tr>
    {rows}
  </table>

  <p style="color:#374151;margin:0 0 8px">
    <strong>Required action:</strong> Investigate immediately. Checkpoints are cryptographic
    anchors for your audit trail — an invalid checkpoint may indicate tampering or
    an infrastructure issue.
  </p>

  <p style="margin:8px 0 0;color:#6b7280;font-size:13px">Detected at: {detected_at}</p>

  <p style="color:#6b7280;font-size:13px;margin:24px 0 0;border-top:1px solid #e5e7eb;padding-top:16px">
    This alert was sent by <strong>Vera</strong> &mdash; AI Compliance Audit Trail.<br>
    You are receiving this because {alert_email} is configured as the alert address for {org_name}.
  </p>
</div>
"""
    await _send(subject=subject, html=html, to=alert_email)
