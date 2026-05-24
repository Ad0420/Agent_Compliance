"""Durable background job queue abstraction.

Production can enqueue jobs to SQS and process them from a separate ECS
worker service. Development/test defaults to local asyncio tasks so existing
flows keep working without AWS infrastructure.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import Awaitable, Callable

from ..config import settings

logger = logging.getLogger("vera.jobs")

JobRunner = Callable[[], Awaitable[None]]


def _provider() -> str:
    return settings.actionledger_job_queue_provider.strip().lower()


async def enqueue_job(
    job_type: str,
    payload: dict,
    *,
    local_runner: JobRunner | None = None,
) -> str:
    """Enqueue a background job and return its job id.

    In ``local`` mode this schedules an asyncio task. In ``sqs`` mode it
    writes a JSON message for ``app.worker`` to consume.
    """
    job_id = str(uuid.uuid4())
    body = {
        "schema_version": 1,
        "job_id": job_id,
        "type": job_type,
        "payload": payload,
    }

    if _provider() == "sqs":
        if not settings.actionledger_sqs_queue_url:
            raise RuntimeError(
                "ACTIONLEDGER_SQS_QUEUE_URL is required when "
                "ACTIONLEDGER_JOB_QUEUE_PROVIDER=sqs"
            )
        await _send_sqs_message(body)
        return job_id

    runner = local_runner or (lambda: run_job(body))
    asyncio.create_task(_run_local(job_type, runner))
    return job_id


async def _run_local(job_type: str, runner: JobRunner) -> None:
    try:
        await runner()
    except Exception:
        logger.exception("local background job failed: type=%s", job_type)


async def _send_sqs_message(body: dict) -> None:
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - boto3 is in prod deps
        raise RuntimeError("boto3 is required for SQS jobs") from exc

    client = boto3.client("sqs", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    await asyncio.to_thread(
        client.send_message,
        QueueUrl=settings.actionledger_sqs_queue_url,
        MessageBody=json.dumps(body, separators=(",", ":"), sort_keys=True),
    )


async def run_job(job: dict) -> None:
    """Run a decoded job payload.

    Kept import-local to avoid tying request-time imports to optional worker
    dependencies and to prevent circular imports with services.webhooks.
    """
    job_type = job.get("type")
    payload = job.get("payload") or {}

    if job_type == "webhook.delivery":
        from .webhooks import deliver_webhook_job

        await deliver_webhook_job(payload)
        return

    if job_type == "email.tamper_alert":
        from .email import send_tamper_alert

        await send_tamper_alert(**payload)
        return

    if job_type == "email.policy_violation_alert":
        from .email import send_policy_violation_alert

        await send_policy_violation_alert(**payload)
        return

    if job_type == "email.checkpoint_alert":
        from .email import send_checkpoint_alert

        await send_checkpoint_alert(**payload)
        return

    if job_type == "checkpoint.create":
        from ..database import AsyncSessionLocal
        from .checkpoint import create_checkpoint

        async with AsyncSessionLocal() as session:
            await create_checkpoint(session, payload["org_id"])
        return

    if job_type == "export.pdf":
        from .export_jobs import run_pdf_export_job

        await run_pdf_export_job(payload["export_job_id"])
        return

    raise ValueError(f"Unknown job type: {job_type!r}")
