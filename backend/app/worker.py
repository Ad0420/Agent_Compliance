"""SQS worker entrypoint for durable background jobs.

Run in ECS as a separate service:

    python -m app.worker
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

from .config import settings
from .services.jobs import run_job

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger("vera.worker")


async def run_sqs_worker() -> None:
    if not settings.actionledger_sqs_queue_url:
        raise RuntimeError("ACTIONLEDGER_SQS_QUEUE_URL must be set for the worker")

    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - boto3 is in prod deps
        raise RuntimeError("boto3 is required for the SQS worker") from exc

    client = boto3.client("sqs", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    logger.info("Vera worker started")

    while True:
        response = await asyncio.to_thread(
            client.receive_message,
            QueueUrl=settings.actionledger_sqs_queue_url,
            MaxNumberOfMessages=5,
            WaitTimeSeconds=20,
            VisibilityTimeout=120,
        )
        for message in response.get("Messages", []):
            receipt = message["ReceiptHandle"]
            try:
                job = json.loads(message.get("Body") or "{}")
                await run_job(job)
            except Exception:
                logger.exception("job failed; message will return to SQS")
                continue

            await asyncio.to_thread(
                client.delete_message,
                QueueUrl=settings.actionledger_sqs_queue_url,
                ReceiptHandle=receipt,
            )


def main() -> None:
    asyncio.run(run_sqs_worker())


if __name__ == "__main__":
    main()
