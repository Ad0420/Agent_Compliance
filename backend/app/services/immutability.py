"""Database-level append-only enforcement.

These triggers make action_records tamper-proof at the DB level.
Even if application code has a bug, the DB will refuse mutations.

SQLite: Uses BEFORE UPDATE/DELETE triggers with RAISE(ABORT, ...).
PostgreSQL: Uses PL/pgSQL trigger functions (defined in migrations/init.sql).
"""

from sqlalchemy import text


SQLITE_TRIGGERS = [
    # Prevent any UPDATE on action_records
    """
    CREATE TRIGGER IF NOT EXISTS no_update_action_records
    BEFORE UPDATE ON action_records
    BEGIN
        SELECT RAISE(ABORT, 'action_records are immutable — updates are not allowed');
    END;
    """,
    # Prevent any DELETE on action_records
    """
    CREATE TRIGGER IF NOT EXISTS no_delete_action_records
    BEFORE DELETE ON action_records
    BEGIN
        SELECT RAISE(ABORT, 'action_records are immutable — deletes are not allowed');
    END;
    """,
    # Ensure chain_state sequence only moves forward
    """
    CREATE TRIGGER IF NOT EXISTS chain_state_monotonic
    BEFORE UPDATE ON chain_state
    WHEN NEW.latest_sequence < OLD.latest_sequence
    BEGIN
        SELECT RAISE(ABORT, 'chain_state.latest_sequence must be monotonically increasing');
    END;
    """,
]


def install_sqlite_triggers(connection):
    """Install SQLite triggers on a synchronous connection.

    Called via: await conn.run_sync(install_sqlite_triggers)
    The connection is passed by SQLAlchemy's run_sync.
    """
    for trigger_sql in SQLITE_TRIGGERS:
        connection.execute(text(trigger_sql))
