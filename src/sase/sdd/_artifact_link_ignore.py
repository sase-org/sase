"""Ignore rules for local artifact-link lock sentinels."""

from __future__ import annotations

from pathlib import Path


ARTIFACT_LINK_LOCK_GITIGNORE_PATTERN = "/links/**/*.lock"


def ensure_artifact_link_lock_gitignore(repo_root: str | Path) -> Path | None:
    """Ensure ``links/**/*.lock`` sentinels are ignored in a document sidecar.

    Preserves existing ``.gitignore`` content and appends only the missing
    rooted pattern. Returns the ``.gitignore`` path when it was created or
    amended. Does not delete lock files or untrack historically committed
    sentinels.
    """

    gitignore = Path(repo_root) / ".gitignore"
    try:
        existing = gitignore.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing = ""
    except OSError:
        existing = ""

    patterns = (ARTIFACT_LINK_LOCK_GITIGNORE_PATTERN,)
    existing_lines = {line.strip() for line in existing.splitlines()}
    missing = [pattern for pattern in patterns if pattern not in existing_lines]
    if not missing and gitignore.exists():
        return None

    if existing:
        updated = existing if existing.endswith("\n") else f"{existing}\n"
        updated += "\n".join(missing) + "\n"
    else:
        updated = "\n".join(patterns) + "\n"

    gitignore.parent.mkdir(parents=True, exist_ok=True)
    gitignore.write_text(updated, encoding="utf-8")
    return gitignore


__all__ = [
    "ARTIFACT_LINK_LOCK_GITIGNORE_PATTERN",
    "ensure_artifact_link_lock_gitignore",
]
