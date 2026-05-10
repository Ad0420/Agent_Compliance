import warnings

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings

_DEFAULT_SECRET = "dev_secret_change_in_production"


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./vera.db"
    secret_key: str = _DEFAULT_SECRET
    environment: str = "development"

    # API key prefix for generated keys
    api_key_prefix: str = "al_live_"

    # Max records per batch ingest
    max_batch_size: int = 100

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
        """If Clerk JWKS is configured, the issuer must also be set.

        Otherwise we'd verify signatures but skip issuer validation, which
        means a JWT signed by ANY Clerk instance (including someone else's)
        would be accepted as long as the kid happens to match. Fail-fast
        at startup beats silently failing open.
        """
        if self.clerk_jwks_url and not self.clerk_issuer:
            raise ValueError(
                "CLERK_ISSUER is required when CLERK_JWKS_URL is set. "
                "Without an expected issuer, JWTs from any Clerk instance "
                "would pass signature verification."
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
