"""Path classification helpers for commit finalization."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path
import re

from sase.linked_repos import (
    EXTERNAL_REPO_CLONES_SUBDIR,
    LINKED_REPO_CLONES_SUBDIR,
    SIDECAR_REPO_CLONES_SUBDIR,
)

_EXTERNAL_SDD_PROMPT_PATTERN = re.compile(r"prompts/\d{6}/[^/]+\.md")
_SASE_RESERVED_PATH_PARTS = (
    (".sase",),
    SIDECAR_REPO_CLONES_SUBDIR,
    LINKED_REPO_CLONES_SUBDIR,
    EXTERNAL_REPO_CLONES_SUBDIR,
)


def is_prompt_archive_path(path: str) -> bool:
    """Return whether *path* names a canonical archived prompt."""

    return _EXTERNAL_SDD_PROMPT_PATTERN.fullmatch(path) is not None


def normalize_path(path: str) -> str:
    return str(Path(path).expanduser().resolve(strict=False))


def normalize_status_path(path: str) -> str:
    """Return the destination path of a git status entry, unquoted."""

    target = path.split(" -> ", 1)[-1]
    return _unquote_git_path(target)


def filter_sase_reserved_paths(paths: Iterable[str]) -> list[str]:
    """Remove root-scoped SASE metadata paths from a changed-file list."""

    return [path for path in paths if not is_sase_reserved_status_path(path)]


def is_sase_reserved_status_path(path: str, *, is_rename: bool = False) -> bool:
    """Return whether a git status path names root-scoped SASE metadata."""

    candidates = path.split(" -> ", 1) if is_rename or " -> " in path else [path]
    return any(_is_sase_reserved_path(_unquote_git_path(item)) for item in candidates)


def _unquote_git_path(path: str) -> str:
    normalized = path.strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] == '"':
        try:
            value = ast.literal_eval(normalized)
        except (SyntaxError, ValueError):
            return normalized[1:-1]
        if isinstance(value, str):
            return value
    return normalized


def _is_sase_reserved_path(path: str) -> bool:
    normalized = path[2:] if path.startswith("./") else path
    parts = tuple(part for part in normalized.split("/") if part)
    return any(parts[: len(prefix)] == prefix for prefix in _SASE_RESERVED_PATH_PARTS)
