"""Shared legacy-index fixtures for dismissed bundle index tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _create_legacy_index(path: Path, *, version: int, obsolete: bool) -> None:
    """Create a legacy SQLite file separately for Rust migration tests."""

    script = """
import sqlite3
import sys

path, version, obsolete = sys.argv[1], int(sys.argv[2]), sys.argv[3] == "1"
connection = sqlite3.connect(path)
connection.execute(
    "CREATE TABLE dismissed_bundle_index_meta "
    "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
)
connection.execute(
    "INSERT INTO dismissed_bundle_index_meta(key, value) VALUES ('schema_version', ?)",
    (str(version),),
)
if obsolete:
    connection.execute(
        "CREATE TABLE dismissed_bundle_summaries "
        "(bundle_path TEXT PRIMARY KEY, obsolete_col INTEGER)"
    )
else:
    connection.execute(
        "CREATE TABLE dismissed_bundle_summaries "
        "(bundle_path TEXT PRIMARY KEY, mtime_ns INTEGER, size_bytes INTEGER)"
    )
    connection.execute("CREATE TABLE legacy_data (value TEXT)")
    connection.execute("INSERT INTO legacy_data VALUES ('keep')")
connection.commit()
connection.close()
"""
    subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(path),
            str(version),
            "1" if obsolete else "0",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
