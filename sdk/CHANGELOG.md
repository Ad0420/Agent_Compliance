# Changelog

All notable changes to `vera-sdk` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Schema-driven redaction mode. `Redactor(schema=...)` with `Schema`,
  `FieldRule`, `FieldPolicy` types from `vera.redaction`. Deny-by-default
  for unmapped fields; PHI fields explicitly tagged. `Redactor.medtech_starter_schema()`
  provides a canonical patient-encounter schema as a starting point.
  Defense-in-depth: existing regex pass and `block_keys` still apply on
  top of schema rules.
- Default redaction patterns for MRN, DOB (multiple formats), IPv4/IPv6
  addresses. ICD-10 pattern is available via schema (`pattern_name="icd10"`)
  but intentionally excluded from the default regex pass — it collides
  with normal English text.
- Branded exception hierarchy in `vera.errors` (public API ahead of v0.4 client integration)
- Single-WARN on first `@audit` invocation when no Vera client is configured
- DeprecationWarning utility for orderly behavioral changes
- `CHANGELOG.md` and `MIGRATION.md`

### Changed
- Default HTTP timeout reduced from 30s to 5s for fail-fast semantics

### Fixed
- `@audit` and `@async_audit` decorators no longer propagate Vera-side HTTP failures as exceptions in customer code

## [0.3.0] - 2026-04-27

### Added
- `Redactor` class for built-in PII/secret redaction
- Opt-in redaction for direct `client.record_action()` calls
- LangChain and CrewAI integrations with redaction on captured content
- OpenAI integration: audit streaming responses with `Redactor` applied to captured content
- Anthropic integration: audit streaming responses with `Redactor` applied to captured content
- Auto-generated `Idempotency-Key` header on action writes
- Human-in-the-loop approval flow (`request_approval` / `wait_for_approval`)

### Changed
- Renamed `actionledger` SDK package to `vera` (published on PyPI as `vera-sdk`)
