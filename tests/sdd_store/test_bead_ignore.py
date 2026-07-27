"""Gitignore coverage for embedded and repository-root bead stores."""

from pathlib import Path

from sase.sdd._bead_ignore import (
    bead_store_gitignore_patterns,
    ensure_bead_store_gitignore,
)


def test_bead_store_gitignore_patterns_support_both_layouts() -> None:
    assert bead_store_gitignore_patterns("beads") == (
        "beads/beads.db",
        "beads/beads.db-shm",
        "beads/beads.db-wal",
    )
    assert bead_store_gitignore_patterns("") == (
        "beads.db",
        "beads.db-shm",
        "beads.db-wal",
    )


def test_root_store_gitignore_preserves_existing_entries(tmp_path: Path) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("assets/cache/\n", encoding="utf-8")

    assert ensure_bead_store_gitignore(tmp_path, prefix="") == gitignore
    assert gitignore.read_text(encoding="utf-8") == (
        "assets/cache/\nbeads.db\nbeads.db-shm\nbeads.db-wal\n"
    )
    assert ensure_bead_store_gitignore(tmp_path, prefix="") is None
