"""Schema migrations for the compatibility bead mirror.

Each migration is idempotent: it inspects the live table and returns without
touching the database when the target shape is already in place.
"""

from __future__ import annotations

import sqlite3

from sase.core.rust import require_rust_binding

_EXTERNAL_REF_INDEX_SQL = """\
CREATE UNIQUE INDEX IF NOT EXISTS idx_issues_external_ref
    ON issues(external_ref)
    WHERE external_ref IS NOT NULL AND external_ref != ''
"""


def _columns(conn: sqlite3.Connection) -> set[str]:
    return {row["name"] for row in conn.execute("PRAGMA table_info(issues)").fetchall()}


def _create_table_sql(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='issues'"
    ).fetchone()
    return None if row is None else str(row["sql"])


def _migrate_add_is_ready_to_work(conn: sqlite3.Connection) -> None:
    """Add is_ready_to_work column to a pre-existing issues table if missing."""
    create_table_sql = _create_table_sql(conn)
    if create_table_sql is None or "is_ready_to_work" in create_table_sql:
        return
    conn.execute(
        "ALTER TABLE issues ADD COLUMN is_ready_to_work INTEGER NOT NULL DEFAULT 0"
    )
    conn.commit()


def _migrate_add_patch_metadata(conn: sqlite3.Connection) -> None:
    """Add Patch metadata columns to a pre-existing issues table."""
    columns = _columns(conn)
    if not columns:
        return
    if "changespec_name" not in columns:
        conn.execute(
            "ALTER TABLE issues ADD COLUMN changespec_name TEXT NOT NULL DEFAULT ''"
        )
    if "changespec_bug_id" not in columns:
        conn.execute(
            "ALTER TABLE issues ADD COLUMN changespec_bug_id TEXT NOT NULL DEFAULT ''"
        )
    conn.commit()


def _migrate_notes_default(conn: sqlite3.Connection) -> None:
    """Backfill a NULL ``notes`` column to an empty structured note list.

    ``notes`` predates this migration, so unlike a brand-new column this is
    a value backfill rather than an ``ALTER TABLE ADD COLUMN``: a pre-existing
    row may still carry SQL NULL from before ``notes`` defaulted to ``'[]'``.
    """
    columns = _columns(conn)
    if not columns:
        return
    conn.execute("UPDATE issues SET notes = '[]' WHERE notes IS NULL")
    conn.commit()


def _migrate_add_model(conn: sqlite3.Connection) -> None:
    """Add model column to a pre-existing issues table if missing."""
    columns = _columns(conn)
    if not columns or "model" in columns:
        return
    conn.execute("ALTER TABLE issues ADD COLUMN model TEXT NOT NULL DEFAULT ''")
    conn.commit()


def _migrate_add_refs(conn: sqlite3.Connection) -> None:
    """Add artifact-reference storage to a pre-existing issues table."""
    columns = _columns(conn)
    if not columns or "refs" in columns:
        return
    conn.execute("ALTER TABLE issues ADD COLUMN refs TEXT NOT NULL DEFAULT ''")
    conn.commit()


def _migrate_add_close_history(conn: sqlite3.Connection) -> None:
    """Add archived close-record storage to a pre-existing issues table.

    A plain ``ALTER TABLE`` suffices here: unlike ``plus_one_evidence`` this
    column carries no CHECK constraint, so no table rebuild is needed.
    """
    columns = _columns(conn)
    if not columns or "close_history" in columns:
        return
    conn.execute(
        "ALTER TABLE issues ADD COLUMN close_history TEXT NOT NULL DEFAULT '[]'"
    )
    conn.commit()


def _migrate_snoozed_status(conn: sqlite3.Connection) -> None:
    """Admit the snoozed status and its record using the Rust policy.

    The status is constrained by a CHECK, so this rebuilds the table; the
    copied column list includes ``close_history``, which is why the caller
    runs this after :func:`_migrate_add_close_history`.
    """
    needs_migration = require_rust_binding("bead_needs_snoozed_status_migration")
    if not needs_migration(_create_table_sql(conn)):
        return

    migration_sql = require_rust_binding("bead_snoozed_status_migration_sql")
    conn.executescript(migration_sql())


def _migrate_add_plus_one_evidence(conn: sqlite3.Connection) -> None:
    """Add structured task +1 evidence to the compatibility mirror."""
    binding = require_rust_binding("bead_needs_plus_one_evidence_migration")
    if not binding(_create_table_sql(conn)):
        return
    sql_binding = require_rust_binding("bead_plus_one_evidence_migration_sql")
    conn.execute(sql_binding())
    conn.commit()


def _migrate_external_ref(conn: sqlite3.Connection) -> None:
    """Add project-qualified external issue identity storage and index."""
    needs_migration = require_rust_binding("bead_needs_external_ref_migration")
    if needs_migration(_create_table_sql(conn)):
        migration_sql = require_rust_binding("bead_external_ref_migration_sql")
        conn.executescript(migration_sql())
        conn.commit()


def _migrate_external_ref_index(conn: sqlite3.Connection) -> None:
    """Rebuild the external-ref unique index after flag rows are gone.

    Historical ``external_ref`` SQL still carves ``issue_type != 'flag'`` out
    of uniqueness. The drop-flag rebuild owns the current index; this pass
    only strips a leftover predicate on stores that no longer have flag
    rows, so it must run after :func:`_migrate_drop_flag_type`.
    """
    columns = _columns(conn)
    if "external_ref" not in columns or "issue_type" not in columns:
        return
    row = conn.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE type='index' AND name='idx_issues_external_ref'"
    ).fetchone()
    sql = "" if row is None or row["sql"] is None else str(row["sql"])
    if row is not None and "issue_type" not in sql:
        return
    conn.execute("DROP INDEX IF EXISTS idx_issues_external_ref")
    conn.execute(_EXTERNAL_REF_INDEX_SQL)
    conn.commit()


def _migrate_add_size(conn: sqlite3.Connection) -> None:
    """Add phase-size metadata to a pre-existing issues table if missing."""
    columns = _columns(conn)
    if not columns or "size" in columns:
        return
    conn.execute(
        "ALTER TABLE issues ADD COLUMN size TEXT "
        "CHECK(size IN ('xsmall','small','medium','large','xlarge'))"
    )
    conn.commit()


def _migrate_relax_size_check(conn: sqlite3.Connection) -> None:
    """Expand the legacy three-value phase-size constraint via Rust policy."""
    needs_migration = require_rust_binding("bead_needs_size_check_relax_migration")
    if not needs_migration(_create_table_sql(conn)):
        return

    migration_sql = require_rust_binding("bead_size_check_relax_migration_sql")
    conn.executescript(migration_sql())


def _migrate_task_ready(conn: sqlite3.Connection) -> None:
    """Admit task beads and ready status using the Rust migration policy."""
    needs_migration = require_rust_binding("bead_needs_task_ready_migration")
    if not needs_migration(_create_table_sql(conn)):
        return

    migration_sql = require_rust_binding("bead_task_ready_migration_sql")
    conn.executescript(migration_sql())


def _migrate_add_tier(conn: sqlite3.Connection) -> None:
    """Add plan-tier metadata to a pre-existing issues table."""
    columns = _columns(conn)
    if not columns or "tier" in columns:
        return
    conn.execute(
        "ALTER TABLE issues ADD COLUMN tier TEXT CHECK(tier IN ('plan','epic'))"
    )
    conn.execute(
        "UPDATE issues SET tier = 'epic' "
        "WHERE issue_type = 'plan' "
        "AND id IN (SELECT DISTINCT parent_id FROM issues WHERE issue_type = 'phase')"
    )
    conn.execute(
        "UPDATE issues SET tier = 'plan' WHERE issue_type = 'plan' AND tier IS NULL"
    )
    conn.commit()


def _migrate_add_resolution(conn: sqlite3.Connection) -> None:
    """Add close-resolution metadata using the Rust migration policy."""
    needs_migration = require_rust_binding("bead_needs_resolution_migration")
    if not needs_migration(_create_table_sql(conn)):
        return

    migration_sql = require_rust_binding("bead_resolution_migration_sql")
    conn.execute(migration_sql())
    conn.commit()


def _migrate_issue_types(conn: sqlite3.Connection) -> None:
    """Migrate from epic/child to plan/phase schema if needed."""
    create_table_sql = _create_table_sql(conn)
    if create_table_sql is None or "'plan'" in create_table_sql:
        return  # No table yet or already migrated

    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute(
        "CREATE TABLE _issues_new ("
        "  id TEXT PRIMARY KEY, title TEXT NOT NULL,"
        "  status TEXT NOT NULL DEFAULT 'open'"
        "    CHECK(status IN ('open','in_progress','closed')),"
        "  issue_type TEXT NOT NULL DEFAULT 'phase'"
        "    CHECK(issue_type IN ('plan','phase')),"
        "  tier TEXT CHECK(tier IN ('plan','epic')),"
        "  parent_id TEXT, owner TEXT, assignee TEXT,"
        "  created_at TEXT NOT NULL, created_by TEXT,"
        "  updated_at TEXT NOT NULL, closed_at TEXT,"
        "  close_reason TEXT, description TEXT, notes TEXT, design TEXT,"
        "  CHECK((issue_type='phase' AND parent_id IS NOT NULL)"
        "    OR (issue_type='plan')),"
        "  CHECK(issue_type='plan' OR tier IS NULL)"
        ")"
    )
    conn.execute(
        "INSERT INTO _issues_new "
        "SELECT id, title, status,"
        "  CASE issue_type"
        "    WHEN 'epic' THEN 'plan' WHEN 'child' THEN 'phase'"
        "    ELSE issue_type END,"
        "  CASE issue_type"
        "    WHEN 'epic' THEN 'epic'"
        "    WHEN 'plan' THEN 'epic'"
        "    ELSE NULL END,"
        "  parent_id, owner, assignee, created_at, created_by,"
        "  updated_at, closed_at, close_reason, description, notes, design "
        "FROM issues"
    )
    conn.execute("DROP TABLE issues")
    conn.execute("ALTER TABLE _issues_new RENAME TO issues")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_issues_status ON issues(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_issues_type ON issues(issue_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_issues_tier ON issues(tier)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_issues_parent ON issues(parent_id)")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.commit()


def _migrate_flag_type(conn: sqlite3.Connection) -> None:
    """Admit the flag issue type and its payload column using Rust policy.

    The type is constrained by a CHECK, so this rebuilds the table; the
    copied column list includes ``snooze`` and ``close_history``, which is why
    the caller runs this after those columns exist and after the snoozed
    status migration's own rebuild.
    """
    needs_migration = require_rust_binding("bead_needs_flag_type_migration")
    if not needs_migration(_create_table_sql(conn)):
        return

    migration_sql = require_rust_binding("bead_flag_type_migration_sql")
    conn.executescript(migration_sql())


def run_migrations(conn: sqlite3.Connection) -> None:
    """Bring a pre-existing issues table up to the current schema.

    Order matters, so the call sequence lives here rather than at the caller.
    """
    _migrate_issue_types(conn)
    _migrate_add_is_ready_to_work(conn)
    _migrate_add_patch_metadata(conn)
    _migrate_notes_default(conn)
    _migrate_add_tier(conn)
    _migrate_add_model(conn)
    _migrate_add_refs(conn)
    _migrate_add_size(conn)
    _migrate_add_resolution(conn)
    _migrate_add_plus_one_evidence(conn)
    # Rebuilding migrations below copy this column explicitly, so the column
    # must exist before they run on older stores.
    _migrate_external_ref(conn)
    _migrate_task_ready(conn)
    _migrate_relax_size_check(conn)
    # Runs after the table-rebuilding migrations above: those copy an explicit
    # legacy column list, so a column added before them would be dropped.
    _migrate_add_close_history(conn)
    # Runs last: its rebuild copies close_history, so that column must exist.
    _migrate_snoozed_status(conn)
    # Runs after snoozed status: its rebuild copies the snooze column, which
    # that migration is what creates.
    _migrate_flag_type(conn)
    # After every rebuild: those copy an explicit legacy column list that
    # predates task_type, so a column added before them would be dropped.
    _migrate_add_task_type(conn)
    # Runs last: its rebuild copies task_type and drops the retired flag
    # type, column, and CHECKs.
    _migrate_drop_flag_type(conn)
    # After drop-flag: leftover ``issue_type != 'flag'`` predicates are safe
    # to strip only once those rows are gone.
    _migrate_external_ref_index(conn)


def _migrate_add_task_type(conn: sqlite3.Connection) -> None:
    """Add optional task-type columns using the Rust migration policy."""
    needs_migration = require_rust_binding("bead_needs_task_type_migration")
    if not needs_migration(_create_table_sql(conn)):
        return
    migration_sql = require_rust_binding("bead_task_type_migration_sql")
    conn.executescript(migration_sql())


def _migrate_drop_flag_type(conn: sqlite3.Connection) -> None:
    """Drop the retired flag issue type using the Rust migration policy."""
    needs_migration = require_rust_binding("bead_needs_drop_flag_type_migration")
    if not needs_migration(_create_table_sql(conn)):
        return
    migration_sql = require_rust_binding("bead_drop_flag_type_migration_sql")
    conn.executescript(migration_sql())
