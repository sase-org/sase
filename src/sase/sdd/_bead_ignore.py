"""Ignore rules for non-version-controlled SDD bead stores."""

from __future__ import annotations

from pathlib import Path

BEAD_STORE_GITIGNORE_PATTERNS: tuple[str, ...] = (
    "beads/beads.db",
    "beads/beads.db-shm",
    "beads/beads.db-wal",
)


def ensure_bead_store_gitignore(sdd_dir: str | Path) -> Path | None:
    """Ensure SQLite bead DB files are ignored in a local SDD git store.

    Returns the ``.gitignore`` path when it was created or amended.
    """

    gitignore = Path(sdd_dir) / ".gitignore"
    try:
        existing = gitignore.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing = ""
    except OSError:
        existing = ""

    existing_lines = {line.strip() for line in existing.splitlines()}
    missing = [
        pattern
        for pattern in BEAD_STORE_GITIGNORE_PATTERNS
        if pattern not in existing_lines
    ]
    if not missing and gitignore.exists():
        return None

    if existing:
        updated = existing if existing.endswith("\n") else f"{existing}\n"
        updated += "\n".join(missing) + "\n"
    else:
        updated = "\n".join(BEAD_STORE_GITIGNORE_PATTERNS) + "\n"

    gitignore.parent.mkdir(parents=True, exist_ok=True)
    gitignore.write_text(updated, encoding="utf-8")
    return gitignore
