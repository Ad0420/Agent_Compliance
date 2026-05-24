from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.models import Customer


@pytest.mark.asyncio
async def test_baa_document_upload_stores_pdf(async_client, org_and_key, db_session):
    org, raw_key, _ = org_and_key
    customer = Customer(org_id=org.id, tenant_id="hospital-a")
    db_session.add(customer)
    await db_session.commit()

    stored = SimpleNamespace(
        uri="s3://baa-bucket/baa/org/customer/doc.pdf",
        bucket="baa-bucket",
        key="baa/org/customer/doc.pdf",
        size_bytes=18,
        content_type="application/pdf",
    )
    mock_put = AsyncMock(return_value=stored)

    with patch("app.routes.customers.put_baa_pdf", mock_put):
        resp = await async_client.post(
            "/v1/customers/hospital-a/baa/document",
            files={"file": ("signed.pdf", b"%PDF-1.7\nsigned\n", "application/pdf")},
            headers={"Authorization": f"Bearer {raw_key}"},
        )

    assert resp.status_code == 201
    assert resp.json()["document_uri"] == stored.uri
    assert mock_put.await_args.kwargs["org_id"] == org.id
    assert mock_put.await_args.kwargs["customer_id"] == customer.id


@pytest.mark.asyncio
async def test_baa_document_upload_rejects_non_pdf(
    async_client, org_and_key, db_session
):
    org, raw_key, _ = org_and_key
    db_session.add(Customer(org_id=org.id, tenant_id="hospital-b"))
    await db_session.commit()

    resp = await async_client.post(
        "/v1/customers/hospital-b/baa/document",
        files={"file": ("signed.txt", b"not a pdf", "text/plain")},
        headers={"Authorization": f"Bearer {raw_key}"},
    )

    assert resp.status_code == 415
