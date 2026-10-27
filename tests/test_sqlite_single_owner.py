"""One SQLite library per database file: stdlib ``sqlite3`` connection allowlist.

Two independent SQLite copies live in one process (stdlib ``sqlite3`` and the
bundled copy inside ``sase_core_rs``). POSIX advisory locks never conflict
within one process, so opening the same WAL database through both copies
truncates or unlinks ``-shm``/``-wal`` under a live mapping, which causes
SIGBUS crashes and index corruption. Every SQLite file therefore has exactly
one owning library; see the "SQLite ownership" section of
``docs/contribute/rust-backend.md``.

This test AST-scans ``src/sase`` for new ``sqlite3.connect`` call sites
(including ``from sqlite3 import connect`` and ``sqlite3.Connection(...)``
construction) and requires the set of modules containing them to stay equal
to ``ALLOWLIST``. Importing ``sqlite3`` only for exception types or
annotations stays allowed. To open a Rust-owned file from Python, add a
``sase_core_rs`` binding instead of extending this list.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src" / "sase"

# Modules allowed to open a stdlib sqlite3 connection, each mapped to the
# Python-owned database it serves.
ALLOWLIST = {
    "bead._db_schema": "beads.db (bead store compatibility mirror)",
    "history.chat_catalog_provenance.cache": "chats_catalog.sqlite",
    "llm_provider._subprocess_agy": "external agy conversation DBs (read-only)",
    "migration_kit.sqlite_backup": (
        "CLI-only migration backup of arbitrary declared roots "
        "(follow-up: also covers Rust-owned files, see PROPOSED FOLLOW-UP "
        "notes on bead sase-1kk.6)"
    ),
}

# Filenames owned by the Rust core: Python must reach them only through
# sase_core_rs bindings, never through stdlib sqlite3.
RUST_OWNED_FILENAME_MARKERS = (
    "agent_artifact_index.sqlite",
    "index.sqlite",
    "runs.sqlite",
    "metrics.sqlite",
    "footprint.sqlite",
    "bead-read-model",
)

_RULE_HELP = (
    "One SQLite library per database file: a WAL database must never be "
    "opened through both stdlib sqlite3 and sase_core_rs in one process "
    "(lost POSIX locks, -shm truncate/unlink, SIGBUS, corruption). "
    "Route new Python access to a Rust-owned file through a sase_core_rs "
    "binding; see docs/contribute/rust-backend.md (SQLite ownership)."
)


def _sqlite_connect_modules() -> set[str]:
    """Return dotted ``sase.<...>`` modules that open a stdlib connection."""
    found: set[str] = set()
    for path in sorted(SRC_ROOT.rglob("*.py")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "sqlite3" not in text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        sqlite_aliases = {"sqlite3"}
        connect_names: set[str] = set()
        connection_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "sqlite3":
                        sqlite_aliases.add(alias.asname or "sqlite3")
            elif isinstance(node, ast.ImportFrom) and node.module == "sqlite3":
                for alias in node.names:
                    local = alias.asname or alias.name
                    if alias.name == "connect":
                        connect_names.add(local)
                    elif alias.name == "Connection":
                        connection_names.add(local)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            opens_connection = False
            if isinstance(func, ast.Attribute) and func.attr == "connect":
                opens_connection = (
                    isinstance(func.value, ast.Name) and func.value.id in sqlite_aliases
                )
            elif isinstance(func, ast.Name) and func.id in connect_names:
                opens_connection = True
            elif isinstance(func, ast.Attribute) and func.attr in connection_names:
                opens_connection = (
                    isinstance(func.value, ast.Name) and func.value.id in sqlite_aliases
                )
            elif isinstance(func, ast.Name) and func.id in connection_names:
                opens_connection = True
            if opens_connection:
                found.add(
                    path.relative_to(SRC_ROOT)
                    .with_suffix("")
                    .as_posix()
                    .replace("/", ".")
                )
                break
    return found


def test_stdlib_sqlite_connections_limited_to_allowlist() -> None:
    found = _sqlite_connect_modules()
    allowed = set(ALLOWLIST)
    extra = sorted(found - allowed)
    missing = sorted(allowed - found)
    assert not extra and not missing, (
        f"{_RULE_HELP} Unexpected stdlib sqlite3 connection sites: {extra}; "
        f"allowlisted modules with no connection site (drop or fix): {missing}."
    )


def test_allowlisted_modules_do_not_name_rust_owned_files() -> None:
    offenders: dict[str, list[str]] = {}
    for module in ALLOWLIST:
        path = SRC_ROOT / Path(*module.split(".")).with_suffix(".py")
        text = path.read_text(encoding="utf-8")
        hits = [m for m in RUST_OWNED_FILENAME_MARKERS if m in text]
        if hits:
            offenders[module] = hits
    assert not offenders, (
        f"{_RULE_HELP} Allowlisted Python-owned modules must not reference "
        f"Rust-owned database files: {offenders}."
    )
