"""Vera maintenance CLI.

Usage::

    python -m app.cli orgs dedupe --name=<org-name> --keep=<org-id> [--dry-run]

Wraps operator-only maintenance that's too risky to expose as an HTTP
endpoint. Currently a single subcommand (``orgs dedupe``) covering the
cleanup-after-duplicate-orgs flow documented in the
``t0o2p3q4r5s6_unique_organizations_name`` migration docstring (W1.6).

Design notes
------------

* Uses ``argparse`` rather than Click / Typer to avoid adding a new
  runtime dependency. The CLI is small (one subcommand today) and the
  ergonomics gain isn't worth the install footprint.
* Executes raw SQL via SQLAlchemy Core ``text(...)`` in a single
  transaction. The cleanup re-points eight FK tables and deletes the
  losing organization; doing this row-by-row via the ORM is both slower
  and (more importantly) easier to half-finish, leaving the database in
  a state where the unique-name migration still aborts.
* Runs synchronously. Maintenance CLIs aren't on a hot path and a sync
  driver removes the async-context boilerplate that would otherwise eat
  half the file. We derive the sync URL from
  ``settings.database_url`` by swapping the driver scheme.

The dedupe SQL recipe lives in
``backend/alembic/versions/t0o2p3q4r5s6_unique_organizations_name.py``
— this CLI is its operational wrapper. Keep them in sync.
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from .config import settings


# Tables that carry ``org_id`` and must be re-pointed before the losing
# row is deleted. Order matches the migration docstring; FK direction is
# always (table.org_id -> organizations.id), so re-pointing first then
# deleting is safe under foreign_keys=ON.
_REPOINT_TABLES: tuple[str, ...] = (
    "action_records",
    "api_keys",
    "customers",
    "baa_agreements",
    "policies",
    "policy_violations",
    "approvals",
    "org_memberships",
    "checkpoints",
)

# Tables whose ``org_id`` row for the losing org is just deleted (no
# need to merge — the surviving org keeps its own chain_state row).
_DELETE_TABLES: tuple[str, ...] = ("chain_state",)


def _sync_database_url() -> str:
    """Return a *synchronous* SQLAlchemy URL derived from settings.

    The app runs on async drivers (``sqlite+aiosqlite``, ``postgresql+asyncpg``);
    maintenance CLIs are simpler with sync drivers, and the operator's
    workstation rarely has both installed. Swap the driver portion.
    """
    url = settings.database_url
    if url.startswith("sqlite+aiosqlite://"):
        return url.replace("sqlite+aiosqlite://", "sqlite://", 1)
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    # Either already-sync or a driver we haven't special-cased — let
    # SQLAlchemy raise the descriptive error if it doesn't load.
    return url


def _dedupe_statements(keep_id: str, delete_id: str) -> list[str]:
    """Return the ordered SQL statements that merge ``delete_id`` INTO ``keep_id``.

    Pure function — used both by the executor and ``--dry-run`` printer
    so the printed SQL is exactly what would run.
    """
    stmts: list[str] = []
    for table in _REPOINT_TABLES:
        stmts.append(
            f"UPDATE {table} SET org_id='{keep_id}' WHERE org_id='{delete_id}';"
        )
    for table in _DELETE_TABLES:
        stmts.append(f"DELETE FROM {table} WHERE org_id='{delete_id}';")
    stmts.append(f"DELETE FROM organizations WHERE id='{delete_id}';")
    return stmts


def _matching_org_ids(conn: Connection, name: str) -> list[str]:
    rows = conn.execute(
        text("SELECT id FROM organizations WHERE name = :name ORDER BY id"),
        {"name": name},
    ).fetchall()
    return [r[0] for r in rows]


def dedupe_orgs(
    engine: Engine,
    *,
    name: str,
    keep: str,
    dry_run: bool,
    out=sys.stdout,
) -> int:
    """Execute the dedupe for ``name``, keeping ``keep`` and merging others.

    Returns a process-style exit code (0 success, non-zero on refusal).
    Raises on unexpected DB failures so the outer transaction rolls back.
    """
    # Two phases — both share one connection so the SQLite PRAGMA lasts
    # across them. Phase 1 reads + validates (no DB writes). Phase 2 is
    # the merge transaction; everything in it commits-or-rolls-back as
    # a single unit (single ``conn.begin()`` block).
    with engine.connect() as conn:
        # Force per-statement FK enforcement on SQLite. Postgres always
        # enforces FKs; sqlite needs the PRAGMA per-connection. If the
        # CLI's sqlite session didn't have FKs on, the delete of the
        # losing org row would succeed even with mis-repointed
        # children, hiding bugs in operator-supplied input.
        if conn.dialect.name == "sqlite":
            # PRAGMAs must run outside any transaction. SQLAlchemy 2.x
            # ``connect()`` returns a connection in implicit-begin mode;
            # roll back the autobegun txn first, then issue the PRAGMA
            # at the driver level (which sidesteps autobegin entirely).
            conn.rollback()
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")

        matching = _matching_org_ids(conn, name)

        if len(matching) == 0:
            print(
                f"refuse: no organizations with name={name!r}; nothing to do",
                file=out,
            )
            return 2
        if len(matching) == 1:
            print(
                f"refuse: only one organization with name={name!r} "
                f"(id={matching[0]}); nothing to dedupe",
                file=out,
            )
            return 2
        if keep not in matching:
            print(
                f"refuse: --keep={keep} is not among the matching org ids "
                f"for name={name!r}; candidates: {matching}",
                file=out,
            )
            return 2

        # Build the list of losers — every matching id that isn't keep.
        losers = [oid for oid in matching if oid != keep]

        if dry_run:
            print(
                f"# dry-run: would merge {len(losers)} org(s) into {keep} "
                f"for name={name!r}",
                file=out,
            )
            print("BEGIN;", file=out)
            for delete_id in losers:
                print(f"-- merging {delete_id} -> {keep}", file=out)
                for stmt in _dedupe_statements(keep, delete_id):
                    print(stmt, file=out)
            print("COMMIT;", file=out)
            return 0

        # The read-validation above started an autobegun transaction;
        # commit it so the explicit merge transaction below is its
        # own unit and rollbacks have a clear meaning. (Nothing in
        # the validation phase wrote rows; this is purely a state
        # reset.)
        conn.commit()

        # Real run — single transaction across every loser. If any
        # statement fails, the whole merge rolls back.
        with conn.begin():
            for delete_id in losers:
                for stmt in _dedupe_statements(keep, delete_id):
                    conn.execute(text(stmt))

        # Sanity check after commit: there should be exactly one row left
        # with this name.
        remaining = _matching_org_ids(conn, name)
        if remaining != [keep]:
            # The merge committed but the surviving set isn't what we
            # expected. Print loud detail; we don't try to undo (that's
            # worse). The operator inspects manually.
            print(
                f"warn: post-merge name={name!r} resolves to {remaining} "
                f"(expected exactly [{keep}])",
                file=out,
            )
            return 3

        print(
            f"ok: merged {len(losers)} org(s) into {keep} for name={name!r}",
            file=out,
        )
        return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="app.cli",
        description="Vera maintenance CLI.",
    )
    sub = parser.add_subparsers(dest="group", required=True)

    orgs = sub.add_parser("orgs", help="Organization maintenance commands.")
    orgs_sub = orgs.add_subparsers(dest="command", required=True)

    dedupe = orgs_sub.add_parser(
        "dedupe",
        help=(
            "Merge duplicate organizations sharing the same name into one "
            "surviving row. Re-points every FK table, deletes the losers, "
            "all in a single transaction."
        ),
    )
    dedupe.add_argument(
        "--name", required=True, help="Organization name with duplicates."
    )
    dedupe.add_argument(
        "--keep",
        required=True,
        help=(
            "Organization id (UUID string) to keep. Must be one of the rows "
            "matching --name; refuses if not."
        ),
    )
    dedupe.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the SQL that would run; do not execute.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.group == "orgs" and args.command == "dedupe":
        engine = create_engine(_sync_database_url(), future=True)
        try:
            return dedupe_orgs(
                engine,
                name=args.name,
                keep=args.keep,
                dry_run=args.dry_run,
            )
        finally:
            engine.dispose()

    parser.error("unknown command")
    return 1  # unreachable; argparse.error exits


if __name__ == "__main__":
    sys.exit(main())
