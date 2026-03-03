"""Unit tests for the hashing service."""

from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.hashing import canonicalize, compute_record_hash, verify_record_hash


class TestCanonicalize:
    def test_sorted_keys(self):
        result = canonicalize({"z": 1, "a": 2, "m": 3})
        assert result.index('"a"') < result.index('"m"') < result.index('"z"')

    def test_none_filtering(self):
        result = canonicalize({"a": 1, "b": None, "c": 3})
        assert "b" not in result

    def test_no_whitespace(self):
        result = canonicalize({"key": "value", "num": 42})
        assert " " not in result

    def test_datetime_normalization(self):
        dt = datetime(2024, 1, 15, 12, 30, 0, tzinfo=timezone.utc)
        result = canonicalize({"ts": dt})
        # Timezone should be stripped for consistent hashing
        assert "2024-01-15T12:30:00" in result

    def test_determinism(self):
        data = {"action": "test", "seq": 1, "agent": "bot"}
        r1 = canonicalize(data)
        r2 = canonicalize(data)
        assert r1 == r2

    def test_different_key_order_same_result(self):
        r1 = canonicalize({"a": 1, "b": 2})
        r2 = canonicalize({"b": 2, "a": 1})
        assert r1 == r2


class TestComputeRecordHash:
    def test_basic_hash(self):
        canonical = canonicalize({"action": "test"})
        h = compute_record_hash(canonical, "GENESIS")
        assert len(h) == 64  # SHA-256 hex digest
        assert all(c in "0123456789abcdef" for c in h)

    def test_different_previous_hash(self):
        canonical = canonicalize({"action": "test"})
        h1 = compute_record_hash(canonical, "GENESIS")
        h2 = compute_record_hash(canonical, "different_hash")
        assert h1 != h2

    def test_different_content(self):
        c1 = canonicalize({"action": "test1"})
        c2 = canonicalize({"action": "test2"})
        h1 = compute_record_hash(c1, "GENESIS")
        h2 = compute_record_hash(c2, "GENESIS")
        assert h1 != h2


class TestVerifyRecordHash:
    def _make_record(self, **overrides):
        defaults = {
            "action_name": "test_action",
            "action_type": "function_call",
            "agent_name": "test-agent",
            "data_subject_id": None,
            "agent_version": None,
            "model_id": None,
            "model_version": None,
            "action_description": None,
            "action_timestamp": datetime(2024, 1, 15, 12, 0, 0),
            "target_system": None,
            "target_resource": None,
            "authorized_by": "system",
            "authorization_scope": None,
            "delegation_chain": [],
            "result": "success",
            "error_message": None,
            "duration_ms": 100,
            "input_data": {},
            "policies_applied": [],
            "environment": {},
            "outcome": {},
            "reasoning": {},
            "metadata_": {},
            "org_id": "test-org-id",
            "sequence_number": 1,
            "framework": None,
            "framework_version": None,
            "previous_hash": "GENESIS",
        }
        defaults.update(overrides)

        # Compute correct hash
        from app.services.hashing import extract_hashable_fields
        record = SimpleNamespace(**defaults)
        fields = extract_hashable_fields(record)
        canonical = canonicalize(fields)
        record.record_hash = compute_record_hash(canonical, record.previous_hash)
        return record

    def test_valid_record_passes(self):
        record = self._make_record()
        assert verify_record_hash(record) is True

    def test_tampered_record_fails(self):
        record = self._make_record()
        record.action_name = "tampered_action"
        assert verify_record_hash(record) is False

    def test_tampered_hash_fails(self):
        record = self._make_record()
        record.record_hash = "0" * 64
        assert verify_record_hash(record) is False
