import warnings

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings

_DEFAULT_SECRET = "dev_secret_change_in_production"


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./vera.db"
    secret_key: str = _DEFAULT_SECRET
    environment: str = "development"

    # API key prefix for generated keys. The tier suffix (``test`` vs
    # ``live``) is appended by ``services.auth.generate_api_key`` so
    # newly-minted keys look like ``al_test_<token>`` or
    # ``al_live_<token>``. Existing pre-Phase-1-PR-4 keys all start with
    # ``al_live_`` (the historical default) and continue to authenticate
    # because the auth path's prefix check uses the shorter ``al_``
    # root. The full literal default stays here for the rate-limit
    # middleware and other call sites that only care about the bearer
    # shape.
    api_key_prefix: str = "al_"

    # Max records per batch ingest
    max_batch_size: int = 100

    # ── Wave 2B PR A3: webhook delivery sweeper ────────────────────────
    # Background sweeper that picks up due ``webhook_deliveries`` rows
    # (retries + scheduled first attempts) and POSTs them. Also runs the
    # approval-expiry pass on the same tick. Disable in tests that don't
    # want time-driven side effects.
    webhook_sweeper_enabled: bool = True
    # Tick cadence. Worst-case retry lag = tick * 1 (one full sleep).
    webhook_sweeper_tick_seconds: int = 30
    # Max rows the sweeper claims per tick. Caps the per-tick work so a
    # backlog doesn't starve other event loop tasks.
    webhook_sweeper_batch_size: int = 50
    # Approval-expiry batch size on the same tick. Smaller because each
    # expiry writes a chain ActionRecord (acquires the per-org lock).
    approval_expiry_batch_size: int = 20

    # ── Phase 3 Wave 3A.b: checkpoint cadence sweeper ─────────────────
    # Background asyncio task that walks each org once per tick and
    # triggers ``services.checkpoint.create_checkpoint`` when the org's
    # ``checkpoint_cadence`` says the last checkpoint is overdue
    # (daily: >24h; hourly: >1h; disabled: never). Separate from the
    # webhook sweeper (different concern, different cadence). Disabled
    # in tests by default — see ``backend/tests/conftest.py``.
    checkpoint_sweeper_enabled: bool = True
    # Tick cadence — how often the sweeper scans the org table looking
    # for due checkpoints. 5 minutes (300s) is much smaller than the
    # finest cadence threshold (1h) so worst-case lag for an hourly org
    # is one tick. Tunable down for tests that exercise the loop.
    checkpoint_sweeper_tick_seconds: int = 300
    # Max orgs the sweeper considers per tick. The query is a single
    # LEFT JOIN against ``checkpoints``, so the cost is bounded by the
    # number of orgs — typical Vera deploy has hundreds, not millions.
    checkpoint_sweeper_batch_size: int = 100

    # Max size for JSON blob fields (bytes of serialized JSON)
    max_json_field_size: int = 1_000_000  # 1 MB

    # Max search query length
    max_search_length: int = 200

    # CORS origins (comma-separated)
    cors_origins: str = "http://localhost:3000"

    # Valid API key permissions
    valid_permissions: list[str] = ["read", "write", "admin"]

    # Rate limiting
    rate_limit_rpm: int = 120  # requests per minute per key
    rate_limit_burst: int = 20  # max burst per second

    # Email alerting via Resend (https://resend.com)
    resend_api_key: str = ""
    alert_from_email: str = "alerts@usevera.xyz"

    # ── Clerk auth (dashboard routes only — SDK keeps API-key auth) ────────────
    # JWKS endpoint for Clerk's signing public keys. Per-instance URL like
    # https://<your-instance>.clerk.accounts.dev/.well-known/jwks.json
    clerk_jwks_url: str = ""
    # Expected JWT issuer claim. Typically the Clerk frontend-api origin.
    # Leave empty to skip issuer verification (NOT recommended in production).
    clerk_issuer: str | None = None
    # Optional audience claim. Only set if you've configured a custom JWT template.
    clerk_audience: str | None = None
    # Authorized parties (`azp` claim). Clerk session tokens carry an `azp`
    # rather than an `aud` — it identifies the frontend origin the token was
    # issued to. If set, ``verify_clerk_jwt`` rejects tokens whose ``azp``
    # is not in this list, preventing a token issued for a different Clerk
    # app on the same instance from being accepted by this backend.
    # See: https://clerk.com/docs/backend-requests/handling/manual-jwt
    # Comma-separated env var, e.g. CLERK_AUTHORIZED_PARTIES=https://app.example.com,https://staging.example.com
    clerk_authorized_parties: list[str] | None = None

    # Clerk webhook signing secret. Configured in the Clerk Dashboard under
    # "Webhooks → <Endpoint> → Signing Secret". Verified via Svix on every
    # delivery to ``POST /v1/clerk/webhooks``. Empty means the route refuses
    # all incoming events (503) — never silently accept unsigned bodies.
    clerk_webhook_secret: str = ""

    # Vera-internal staff Clerk org. Wave 3A.c — when a Clerk session's
    # ``org_id`` claim matches this value (OR the session carries an
    # ``org_role == 'vera_staff'`` claim), the request is resolved to
    # ``IamTier.STAFF_READ_ONLY``: PHI fields are redacted from every
    # response and a row is written to ``staff_audit_log``. Empty in
    # development; set in Vera-managed environments only. The role-claim
    # path lets deployments that don't dedicate a single Clerk org work
    # too.
    clerk_staff_org_id: str = ""

    # Clerk Backend API secret key (``sk_live_…`` / ``sk_test_…``). Required
    # only for the defense-in-depth membership freshness re-check in
    # ``require_clerk_role``: when a local ``OrgMembership`` row is older than
    # ``membership_freshness_seconds`` we call Clerk's REST API to confirm
    # the user still has the role we cached. Empty disables the freshness
    # check entirely (cached role is trusted indefinitely).
    clerk_secret_key: str = ""

    # Max age (in seconds) of a cached ``OrgMembership`` row before
    # ``require_clerk_role`` consults Clerk's REST API to confirm the role.
    # Trades a Clerk-API round-trip for closing the gap on missed/late
    # demotion webhooks and 60-second-stale JWT ``org_id`` claims. 5 min is
    # a reasonable middle ground — short enough that a missed demotion is
    # contained, long enough that the typical hot-path stays cached.
    membership_freshness_seconds: int = 300

    model_config = {"env_file": ".env"}

    @field_validator("clerk_authorized_parties", mode="before")
    @classmethod
    def _split_authorized_parties(cls, v):
        """Allow comma-separated env var → list."""
        if v is None or v == "":
            return None
        if isinstance(v, str):
            parts = [p.strip() for p in v.split(",") if p.strip()]
            return parts or None
        return v

    @model_validator(mode="after")
    def _validate_clerk_config(self):
        """Catch the Clerk env-var inconsistencies that produce silent 401s.

        Three checks, all motivated by real failures:

        1. JWKS without ISSUER → JWTs from ANY Clerk instance pass signature
           verification as long as the kid matches. Hard fail.

        2. JWKS host != ISSUER host → the deploy is misconfigured for *which*
           Clerk instance it speaks to. The dashboard hands the backend tokens
           issued by the instance whose pk_* the frontend uses; if the backend
           verifies them against a different instance's JWKS, every request
           401s with no useful server log. Hard fail.

        3. AUTHORIZED_PARTIES unset in production → the backend will accept a
           valid Clerk JWT issued for ANY frontend on the same Clerk instance,
           not just our own. Soft warning (operators sometimes intentionally
           unset this while debugging an `azp` mismatch; don't break startup).
        """
        if self.clerk_jwks_url and not self.clerk_issuer:
            raise ValueError(
                "CLERK_ISSUER is required when CLERK_JWKS_URL is set. "
                "Without an expected issuer, JWTs from any Clerk instance "
                "would pass signature verification."
            )
        if self.clerk_jwks_url and self.clerk_issuer:
            from urllib.parse import urlparse

            jwks_host = urlparse(self.clerk_jwks_url).netloc
            issuer_host = urlparse(self.clerk_issuer).netloc
            if jwks_host and issuer_host and jwks_host != issuer_host:
                raise ValueError(
                    f"CLERK_JWKS_URL host ({jwks_host!r}) does not match "
                    f"CLERK_ISSUER host ({issuer_host!r}). These must point "
                    "at the same Clerk instance, or every JWT will 401."
                )
        if self.environment != "development" and not self.clerk_authorized_parties:
            warnings.warn(
                "CLERK_AUTHORIZED_PARTIES is unset in a non-development "
                "environment. The backend will accept any valid Clerk JWT "
                "issued by this instance, including ones issued for other "
                "frontends on the same Clerk app. Set this to your dashboard "
                "origin(s) — e.g. 'https://app.example.com'.",
                UserWarning,
                stacklevel=2,
            )
        return self


settings = Settings()

# Auto-convert bare postgresql:// URLs to the asyncpg dialect.
# Railway's reference variables (e.g. ${{Postgres.DATABASE_URL}}) emit
# postgresql:// which asyncpg doesn't accept without the +asyncpg suffix.
if settings.database_url.startswith("postgresql://"):
    settings.database_url = settings.database_url.replace(
        "postgresql://", "postgresql+asyncpg://", 1
    )

# Fail-fast: refuse to run with default secret in non-dev environments
if settings.environment != "development" and settings.secret_key == _DEFAULT_SECRET:
    raise RuntimeError(
        "SECRET_KEY must be set to a unique value in non-development environments. "
        "Set the SECRET_KEY environment variable."
    )

if settings.secret_key == _DEFAULT_SECRET:
    warnings.warn(
        "Using default SECRET_KEY — this is insecure. Set SECRET_KEY env var for production.",
        UserWarning,
        stacklevel=1,
    )
