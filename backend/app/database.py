from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from .config import settings

_is_sqlite = settings.database_url.startswith("sqlite")

engine_kwargs = {
    "echo": settings.environment == "development",
}
if _is_sqlite:
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    if settings.db_pool_size <= 0:
        engine_kwargs["poolclass"] = NullPool
    else:
        engine_kwargs["pool_size"] = settings.db_pool_size
        engine_kwargs["max_overflow"] = settings.db_max_overflow
        engine_kwargs["pool_timeout"] = settings.db_pool_timeout
    engine_kwargs["pool_pre_ping"] = True   # detect stale connections before use
    engine_kwargs["pool_recycle"] = settings.db_pool_recycle_seconds

engine = create_async_engine(settings.database_url, **engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    """FastAPI dependency: yields a DB session per request."""
    async with AsyncSessionLocal() as session:
        yield session
