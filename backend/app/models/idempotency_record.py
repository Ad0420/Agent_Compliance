"""Stub for Phase 2 idempotency-keys implementation.

TODO(phase-2): Define the IdempotencyRecord SQLAlchemy model here. Will track
request fingerprints (api_key_id + idempotency_key + body_hash) and the
cached response so duplicate writes return the original record without
re-running the action. Phase 2 agent will also wire it into
``backend/app/models/__init__.py``.
"""
