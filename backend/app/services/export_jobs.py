"""Durable export job execution."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ..database import AsyncSessionLocal
from ..models import ExportJob
from .export import generate_pdf
from .s3_documents import put_export_pdf

logger = logging.getLogger("vera.export_jobs")


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _coerce_filters(filters: dict) -> dict:
    coerced = dict(filters or {})
    for key in ("start_date", "end_date"):
        value = coerced.get(key)
        if isinstance(value, str):
            coerced[key] = datetime.fromisoformat(value)
    return coerced


async def create_pdf_export_job(
    session: AsyncSession,
    *,
    org_id: str,
    filters: dict,
    requested_by: str | None = None,
) -> ExportJob:
    job = ExportJob(
        org_id=org_id,
        format="pdf",
        status="queued",
        filters=filters,
        requested_by=requested_by,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def run_pdf_export_job(export_job_id: str) -> None:
    """Generate a PDF export, store it in S3, and update job status."""
    async with AsyncSessionLocal() as session:
        job = await session.get(ExportJob, export_job_id)
        if job is None:
            logger.warning("export job not found: %s", export_job_id)
            return

        if job.status not in {"queued", "failed"}:
            logger.info("export job %s already %s; skipping", job.id, job.status)
            return

        job.status = "running"
        job.error_message = None
        job.updated_at = _utcnow_naive()
        await session.commit()

        try:
            pdf_bytes = await generate_pdf(
                session, job.org_id, _coerce_filters(job.filters or {})
            )
            stored = await put_export_pdf(
                org_id=job.org_id,
                export_job_id=job.id,
                body=pdf_bytes,
            )
        except Exception as exc:
            logger.exception("PDF export job failed: %s", job.id)
            job.status = "failed"
            job.error_message = str(exc)[:1000]
            job.updated_at = _utcnow_naive()
            job.completed_at = _utcnow_naive()
            await session.commit()
            return

        job.status = "succeeded"
        job.result_uri = stored.uri
        job.updated_at = _utcnow_naive()
        job.completed_at = _utcnow_naive()
        await session.commit()
