"""Tests for SQLite database schema migrations.

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests.test_bead.test_db_migrations_adds_column import TestMigrationAddsColumn
from tests.test_bead.test_db_migrations_rebuild import (
    TestIssueTypeRebuildRestartability,
    TestSizeConstraintMigration,
    TestStatusConstraintMigration,
)

__test__ = False

__all__ = [
    "TestIssueTypeRebuildRestartability",
    "TestMigrationAddsColumn",
    "TestSizeConstraintMigration",
    "TestStatusConstraintMigration",
]
