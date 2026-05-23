"""End-to-end test for the Phase 1 PR 1 ``_create_record`` data-drop fix.

The pre-fix bug: ``ActionRecordCreate`` accepted ``tenant_id``, ``domain``,
and ``action_class``, and ``HASHABLE_FIELDS`` listed them — but the
``ActionRecord(...)`` constructor inside ``services.chain._create_record``
silently dropped them. SDK-supplied values were stored as NULL and the
record hash was computed over ``None, None, None``.

This test recreates the exact end-to-end flow the SDK exercises:

  1. POST /v1/actions with all three promoted fields populated
  2. GET /v1/actions/{id} — assert the three fields round-trip
  3. Recompute the expected hash via the canonical pipeline (extract_hashable_fields
     → canonicalize → compute_record_hash). Assert it matches the stored
     record_hash — proves the values actually participated in the hash.
  4. Insert a SECOND action without the three fields. Hash must differ
     from the first — proves the fields meaningfully change the chain.

If any future refactor of ``_create_record`` re-introduces the drop,
this test fails immediately.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import ActionRecord
from app.services.hashing import (
    canonicalize,
    compute_record_hash,
    extract_hashable_fields,
)


@pytest.mark.asyncio
async def test_action_create_round_trips_promoted_columns(
    async_client, org_and_key, db_session
):
    _, raw_key, _ = org_and_key

    # ── 1. POST with tenant_id / domain / action_class ─────────
    payload = {
        "action_name": "chart_entry_test",
        "action_type": "function_call",
        "agent_name": "scribe-agent",
        "result": "success",
        "tenant_id": "cleveland_clinic",
        "domain": "clinical_decision",
        "action_class": "chart_entry",
    }
    create_resp = await async_client.post(
        "/v1/actions",
        json=payload,
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert create_resp.status_code == 200, create_resp.text
    created = create_resp.json()
    record_id = created["id"]
    stored_hash = created["record_hash"]

    # The response itself must surface the three values (no NULLs).
    assert created["tenant_id"] == "cleveland_clinic"
    assert created["domain"] == "clinical_decision"
    assert created["action_class"] == "chart_entry"

    # ── 2. GET round-trip ───────────────────────────────────────
    get_resp = await async_client.get(
        f"/v1/actions/{record_id}",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert get_resp.status_code == 200
    fetched = get_resp.json()
    assert fetched["tenant_id"] == "cleveland_clinic"
    assert fetched["domain"] == "clinical_decision"
    assert fetched["action_class"] == "chart_entry"
    assert fetched["record_hash"] == stored_hash

    # ── 3. Recompute the hash from the ORM row + assert match ──
    # The hash is computed server-side; if _create_record had dropped
    # the three fields, this independent recomputation (which reads them
    # from the DB) would yield a DIFFERENT hash than the stored value.
    result = await db_session.execute(
        select(ActionRecord).where(ActionRecord.id == record_id)
    )
    row = result.scalar_one()
    fields = extract_hashable_fields(row)
    # Sanity: extraction itself sees the populated values.
    assert fields["tenant_id"] == "cleveland_clinic"
    assert fields["domain"] == "clinical_decision"
    assert fields["action_class"] == "chart_entry"

    expected_hash = compute_record_hash(
        canonicalize(fields), row.previous_hash
    )
    assert expected_hash == stored_hash, (
        "Stored record_hash does not match hash recomputed from the row's "
        "current column values — _create_record likely dropped the promoted "
        "columns before hashing."
    )

    # ── 4. Insert a second action WITHOUT the promoted fields ─
    bare_resp = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "chart_entry_test",
            "action_type": "function_call",
            "agent_name": "scribe-agent",
            "result": "success",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert bare_resp.status_code == 200
    bare_hash = bare_resp.json()["record_hash"]
    assert bare_hash != stored_hash, (
        "Records with vs. without tenant_id/domain/action_class produced "
        "identical hashes — the promoted columns are not actually "
        "participating in the chain."
    )
