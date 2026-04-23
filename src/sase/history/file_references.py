"""Rolling history of file-path references extracted from submitted prompts."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from pathlib import Path

_HISTORY_FILE = Path.home() / ".sase" / "file_reference_history.json"

# Narrowed from the display-side _FILE_PATH_RE in
# sase.ace.tui.widgets.prompt_panel._file_path_hints: only absolute paths
# (``/...`` or ``~/...``) and ``@``-prefixed paths are recorded.  Bare
# relative paths without an ``@`` prefix are ignored.
_FILE_REF_RE = re.compile(
    r"(?<![/\w@.])"
    r"(@?)"
    r"("
    # Absolute paths: /foo/bar or ~/foo/bar
    r"(?:~?/[\w.+\-][\w.+\-/]*)"
    r"|"
    # Relative paths with explicit prefix: ./foo or ../foo
    r"(?:\.{1,2}/[\w.+\-][\w.+\-/]*)"
    r"|"
    # Dot-directory paths: .sase/foo.ext
    r"(?:\.[\w\-]+/[\w.+\-][\w.+\-/]*)"
    r"|"
    # Bare relative paths with extension: dir/file.ext
    r"(?:[\w\-]+/[\w.+\-/]*\.[\w]+)"
    r")"
)


def _is_local_sase_path(path: str) -> bool:
    """True if *path* points into a project-local ``.sase/`` directory."""
    return path.startswith(".sase/")


def extract_recordable_file_refs(text: str) -> list[str]:
    """Extract file-path references suitable for recording in history.

    Keeps only two kinds of tokens, in prompt order:

    - ``@``-prefixed paths: the ``@`` is stripped from the stored value.
    - Absolute paths: tokens beginning with ``/`` or ``~/``.

    Bare relative paths (e.g. ``src/foo.py``) that the display-side regex
    also matches are filtered out — they are typically ambient mentions
    rather than intentional file references.  Paths pointing into a
    project-local ``.sase/`` directory are also filtered out — they are
    agent-managed state the user never re-references.

    Paths are returned as the user typed them; ``~`` is not expanded so
    history matches the user's writing style.
    """
    if not text:
        return []

    results: list[str] = []
    for match in _FILE_REF_RE.finditer(text):
        at_prefix = match.group(1)
        path = match.group(2)
        if _is_local_sase_path(path):
            continue
        if at_prefix:
            results.append(path)
        elif path.startswith(("/", "~/")):
            results.append(path)
    return results


def load_file_references() -> list[str]:
    """Load the recency-ordered file-reference history from disk.

    Returns:
        Ordered list of paths, most recently referenced first.  Empty
        list if the file is missing or cannot be parsed.
    """
    if not _HISTORY_FILE.exists():
        return []
    try:
        with open(_HISTORY_FILE, encoding="utf-8") as f:
            data = json.load(f)
        paths = data.get("paths", [])
        return [p for p in paths if isinstance(p, str) and not _is_local_sase_path(p)]
    except (OSError, json.JSONDecodeError):
        return []


def _write_history(paths: list[str]) -> None:
    """Atomically overwrite the history file with *paths*."""
    try:
        _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = _HISTORY_FILE.with_suffix(_HISTORY_FILE.suffix + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump({"paths": paths}, f, indent=2)
        os.replace(tmp_path, _HISTORY_FILE)
    except OSError:
        pass


def record_file_references(refs: Iterable[str]) -> None:
    """Prepend *refs* to the on-disk history, dedup, and atomically save.

    The last entry in *refs* ends up at index 0 in the saved list.  Any
    prior occurrence of the same path (earlier in *refs* or already on
    disk) is removed so each path appears once.
    """
    new_refs = [r for r in refs if r]
    if not new_refs:
        return

    existing = load_file_references()
    # Prepend each ref in order so the *last* ref ends up at index 0.
    combined: list[str] = []
    for ref in new_refs:
        combined.insert(0, ref)
    combined.extend(existing)

    seen: set[str] = set()
    deduped: list[str] = []
    for ref in combined:
        if ref in seen:
            continue
        seen.add(ref)
        deduped.append(ref)

    _write_history(deduped)


def remove_file_reference(path: str) -> None:
    """Remove *path* from the on-disk history, atomically.

    Silent no-op if the history file is missing or corrupt, or if *path*
    is not present. Exact-match comparison: the caller must pass the
    stored form (``@`` already stripped, ``~`` not expanded) — which is
    exactly what :func:`load_file_references` returns.
    """
    if not _HISTORY_FILE.exists():
        return
    try:
        with open(_HISTORY_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return
    raw_paths = data.get("paths", [])
    existing = [p for p in raw_paths if isinstance(p, str)]
    remaining = [p for p in existing if p != path]
    if len(remaining) == len(existing):
        return
    _write_history(remaining)
