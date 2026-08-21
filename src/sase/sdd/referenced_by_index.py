"""Structured tracked ``links/`` index helpers for Referenced By truth."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REFERENCED_BY_LINKS_DIR = "links"
_REFERENCED_BY_BLOCK_START = "<!-- sase:referenced-by:start -->"


def referenced_by_index_relpath(repo_relpath: str) -> str:
    """Return the tracked ``links/`` index path for one artifact document."""

    rel = Path(repo_relpath)
    if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
        raise ValueError(f"unsafe referenced-by artifact path: {repo_relpath!r}")
    index_name = rel.with_suffix(rel.suffix + ".json")
    return (Path(REFERENCED_BY_LINKS_DIR) / index_name).as_posix()


def referenced_by_index_path(repo_root: Path, artifact_id: str) -> Path:
    """Return the structured index path for *artifact_id* inside *repo_root*."""

    provider, separator, repo_relpath = artifact_id.partition(":")
    if not separator or not provider or not repo_relpath:
        raise ValueError(f"invalid referenced-by artifact id: {artifact_id!r}")
    return repo_root / referenced_by_index_relpath(repo_relpath)


def document_has_referenced_by_block(text: str) -> bool:
    """Return whether *text* has an unfenced managed Referenced By block."""

    in_fence = False
    for raw_line in text.splitlines():
        stripped = raw_line.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and raw_line == _REFERENCED_BY_BLOCK_START:
            return True
    return False


def referenced_by_index_schema_version(path: Path) -> int | None:
    """Return the on-disk schema version, or ``None`` when it cannot be read."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    version = payload.get("schema_version")
    return version if isinstance(version, int) else None


__all__ = [
    "REFERENCED_BY_LINKS_DIR",
    "document_has_referenced_by_block",
    "referenced_by_index_path",
    "referenced_by_index_relpath",
    "referenced_by_index_schema_version",
]
