"""Regression test for the Phase 3 evidence-bundle manifest hotfix.

Wave 3D.2's dashboard evidence exporter
(``backend/app/services/evidence_export.py``) emits ``manifest.json``
keys that the Wave 3C.1 SDK offline verifier
(``sdk/vera/verify/offline.py``) needs to even open the bundle. The
two PRs were written in parallel against the same brief and the
manifest schema diverged — the SDK expected ``vera_version`` /
``exported_at`` / ``checkpoint_count`` / ``record_count`` while the
dashboard emitted ``schema_version`` / ``generated_at`` (no counts).

That mismatch broke the headline Phase 3 acceptance gate:
``vera verify --offline <dashboard-bundle>`` failed at the manifest
parse step before any record-level verification ran. Found during
Phase 3 Scenario 4 manual walkthrough.

This test pins the four SDK-required keys on every bundle build so a
future refactor that drops them fails fast in CI rather than waiting
for a regulator-ready demo to surface the regression.

If the SDK adds a new required manifest key (e.g. ``signing_kms_id``
in a later wave), add it here AND in the exporter's manifest dict —
and document why in both spots.
"""
from __future__ import annotations

import io
import json
import tarfile

import pytest

from app.services.evidence_export import build_evidence_bundle_tar_gz


# Keys the SDK's offline verifier reads at bundle-open time. Source of
# truth: ``sdk/vera/verify/offline.py::_load_manifest``. If the SDK
# adds or removes a required key, mirror it here.
SDK_REQUIRED_MANIFEST_KEYS = frozenset(
    {
        "vera_version",
        "exported_at",
        "checkpoint_count",
        "record_count",
    }
)


def _read_manifest_from_bundle_bytes(buf: bytes) -> dict:
    """Decompress + untar in-memory and return the parsed manifest.json."""
    with tarfile.open(fileobj=io.BytesIO(buf), mode="r:gz") as tar:
        for member in tar.getmembers():
            if member.name == "manifest.json":
                file = tar.extractfile(member)
                assert file is not None, "manifest.json had no readable content"
                return json.loads(file.read().decode("utf-8"))
    raise AssertionError("bundle did not contain a manifest.json")


@pytest.mark.asyncio
async def test_manifest_includes_all_sdk_required_keys(db_session):
    """Build a real bundle and assert every SDK-required key is present.

    Uses the same ``build_evidence_bundle_tar_gz`` entry point the
    dashboard route calls. If a future change drops one of the four
    SDK-required keys, the SDK offline verifier breaks immediately and
    this test catches it before merge.
    """
    from app.models import Organization, Customer

    # Minimal fixture — one org, one customer, no records. The exporter
    # is required to emit a valid manifest even on an empty window
    # (the auditor still wants to see "0 records, signed at X").
    org = Organization(name="test-org-manifest-schema")
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)

    customer = Customer(
        org_id=org.id,
        tenant_id="test-tenant-manifest",
        display_name="Test Customer",
        status="active",
    )
    db_session.add(customer)
    await db_session.commit()
    await db_session.refresh(customer)

    import datetime as _dt
    start = _dt.datetime(2026, 1, 1)
    end = _dt.datetime(2026, 12, 31, 23, 59, 59, 999999)

    bundle_bytes_outer, _summary = await build_evidence_bundle_tar_gz(
        db_session,
        customer=customer,
        org=org,
        start=start,
        end=end,
    )

    manifest = _read_manifest_from_bundle_bytes(bundle_bytes_outer)

    missing = SDK_REQUIRED_MANIFEST_KEYS - set(manifest.keys())
    assert not missing, (
        f"manifest.json is missing SDK-required keys: {missing}. "
        f"The SDK offline verifier (sdk/vera/verify/offline.py) reads "
        f"these at bundle-open time. Without them, "
        f"``vera verify --offline <bundle>`` rejects the bundle as "
        f"malformed before any record-level verification runs. Edit "
        f"backend/app/services/evidence_export.py and re-add the "
        f"missing key(s)."
    )

    # Pin the values too, not just the keys — a future bug that sets
    # one to None or 0 unconditionally would still pass a key-only
    # check but break the SDK at parse time.
    assert manifest["vera_version"], "vera_version must be a non-empty value"
    assert manifest["exported_at"], "exported_at must be a non-empty ISO timestamp"
    assert isinstance(manifest["checkpoint_count"], int), (
        "checkpoint_count must be an int (the SDK uses it for the summary line)"
    )
    assert isinstance(manifest["record_count"], int), (
        "record_count must be an int (the SDK uses it for the summary line)"
    )
    # Empty window → both counts should be 0, not None.
    assert manifest["checkpoint_count"] == len(manifest.get("checkpoints", []))
    assert manifest["record_count"] == len(manifest.get("records", []))


@pytest.mark.asyncio
async def test_manifest_keeps_dashboard_only_keys(db_session):
    """The hotfix added SDK keys WITHOUT removing dashboard-only keys.

    The dashboard reads ``schema_version``, ``customer_display_name``,
    ``org_name``, ``warnings`` and other extras to render the bundle
    metadata. SDK ignores these as unknowns; dashboard depends on them.
    A future cleanup that "tidies up" the manifest could regress by
    removing them. Pin the load-bearing ones.
    """
    from app.models import Organization, Customer

    org = Organization(name="test-org-manifest-extras")
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)

    customer = Customer(
        org_id=org.id,
        tenant_id="test-tenant-extras",
        display_name="Test Customer Extras",
        status="active",
    )
    db_session.add(customer)
    await db_session.commit()
    await db_session.refresh(customer)

    import datetime as _dt
    start = _dt.datetime(2026, 1, 1)
    end = _dt.datetime(2026, 12, 31, 23, 59, 59, 999999)

    bundle_bytes, _summary = await build_evidence_bundle_tar_gz(
        db_session,
        customer=customer,
        org=org,
        start=start,
        end=end,
    )

    manifest = _read_manifest_from_bundle_bytes(bundle_bytes)

    dashboard_required_keys = {
        "schema_version",
        "tenant_id",
        "customer_display_name",
        "org_id",
        "org_name",
        "date_range",
        "warnings",
    }
    missing = dashboard_required_keys - set(manifest.keys())
    assert not missing, (
        f"manifest.json is missing dashboard-rendering keys: {missing}. "
        f"The Vera dashboard's bundle-preview/recent-exports surfaces "
        f"read these. SDK ignores them as unknowns, but the dashboard "
        f"breaks without them."
    )
