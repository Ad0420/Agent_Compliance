"""S3 document storage helpers for BAAs and generated exports."""
from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath

from ..config import settings


@dataclass(frozen=True)
class StoredObject:
    bucket: str
    key: str
    uri: str
    size_bytes: int
    content_type: str


def _s3_client():
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - boto3 is in prod deps
        raise RuntimeError("boto3 is required for S3 document storage") from exc

    return boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def _normalise_prefix(prefix: str) -> str:
    cleaned = str(PurePosixPath(prefix.strip("/"))) if prefix.strip("/") else ""
    return f"{cleaned}/" if cleaned else ""


async def put_baa_pdf(
    *,
    org_id: str,
    customer_id: str,
    body: bytes,
    content_type: str,
) -> StoredObject:
    if not settings.actionledger_baa_bucket:
        raise RuntimeError("ACTIONLEDGER_BAA_BUCKET is not configured")

    prefix = _normalise_prefix(settings.actionledger_baa_prefix)
    now = datetime.now(timezone.utc)
    key = (
        f"{prefix}{org_id}/{customer_id}/"
        f"{now.strftime('%Y/%m/%d')}/{uuid.uuid4()}.pdf"
    )
    extra_args = {
        "ContentType": content_type,
        "Metadata": {
            "org_id": org_id,
            "customer_id": customer_id,
        },
    }
    if settings.actionledger_baa_kms_key_id:
        extra_args["ServerSideEncryption"] = "aws:kms"
        extra_args["SSEKMSKeyId"] = settings.actionledger_baa_kms_key_id

    client = _s3_client()
    await asyncio.to_thread(
        client.put_object,
        Bucket=settings.actionledger_baa_bucket,
        Key=key,
        Body=body,
        **extra_args,
    )
    return StoredObject(
        bucket=settings.actionledger_baa_bucket,
        key=key,
        uri=f"s3://{settings.actionledger_baa_bucket}/{key}",
        size_bytes=len(body),
        content_type=content_type,
    )


async def put_export_pdf(
    *,
    org_id: str,
    export_job_id: str,
    body: bytes,
) -> StoredObject:
    if not settings.actionledger_export_bucket:
        raise RuntimeError("ACTIONLEDGER_EXPORT_BUCKET is not configured")

    prefix = _normalise_prefix(settings.actionledger_export_prefix)
    now = datetime.now(timezone.utc)
    key = (
        f"{prefix}{org_id}/{now.strftime('%Y/%m/%d')}/"
        f"{export_job_id}.pdf"
    )
    extra_args = {
        "ContentType": "application/pdf",
        "Metadata": {
            "org_id": org_id,
            "export_job_id": export_job_id,
        },
    }
    if settings.actionledger_export_kms_key_id:
        extra_args["ServerSideEncryption"] = "aws:kms"
        extra_args["SSEKMSKeyId"] = settings.actionledger_export_kms_key_id

    client = _s3_client()
    await asyncio.to_thread(
        client.put_object,
        Bucket=settings.actionledger_export_bucket,
        Key=key,
        Body=body,
        **extra_args,
    )
    return StoredObject(
        bucket=settings.actionledger_export_bucket,
        key=key,
        uri=f"s3://{settings.actionledger_export_bucket}/{key}",
        size_bytes=len(body),
        content_type="application/pdf",
    )
