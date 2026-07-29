"""Rolling history of file-path references extracted from submitted prompts."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from pathlib import Path

from sase.core.paths import sase_home

_HISTORY_FILE: Path | None = None

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


def _history_file() -> Path:
    return _HISTORY_FILE or sase_home() / "file_reference_history.json"


def extract_recordable_file_refs(text: str) -> list[str]:
    """Extract file-path references suitable for recording in history.

    Keeps only two kinds of tokens, in prompt order:

    - ``@``-prefixed paths whose stored form does not start with ``/``:
      the ``@`` is stripped from the stored value.
    - ``~/``-rooted paths.

    Bare ``/``-rooted absolute paths (and ``@/...`` tokens that decay to
    them once the ``@`` is stripped) are filtered out — they tend to be
    one-off system-ish references the user does not want resurfacing
    through ``<ctrl+t>`` completion.  Bare relative paths (e.g.
    ``src/foo.py``) are also dropped — they are typically ambient
    mentions rather than intentional file references.  Paths pointing
    into a project-local ``.sase/`` directory are filtered out as well —
    they are agent-managed state the user never re-references.

    Paths are returned as the user typed them; ``~`` is not expanded so
    history matches the user's writing style.
    """
    if not text:
        return []

    from sase.artifact_refs import scan_artifact_refs
    from sase.xprompt._literal_zones import literal_zone_ranges

    byte_to_char = _byte_to_character_offsets(text)
    literal_ranges = literal_zone_ranges(text)
    artifact_spans: list[tuple[int, int]] = []
    results_with_positions: list[tuple[int, str]] = []
    for candidate in scan_artifact_refs(text):
        start = byte_to_char[candidate.candidate_span.start]
        end = byte_to_char[candidate.candidate_span.end]
        artifact_spans.append((start, end))
        if candidate.well_formed and not _overlaps_any(start, end, literal_ranges):
            results_with_positions.append((start, candidate.text))

    for match in _FILE_REF_RE.finditer(text):
        if _overlaps_any(match.start(), match.end(), artifact_spans):
            continue
        at_prefix = match.group(1)
        path = match.group(2)
        if _is_local_sase_path(path):
            continue
        if path.startswith("/"):
            continue
        if at_prefix:
            results_with_positions.append((match.start(), path))
        elif path.startswith("~/"):
            results_with_positions.append((match.start(), path))
    results_with_positions.sort(key=lambda item: item[0])
    return [value for _position, value in results_with_positions]


def _byte_to_character_offsets(text: str) -> dict[int, int]:
    offsets = {0: 0}
    byte_offset = 0
    for character_offset, character in enumerate(text, start=1):
        byte_offset += len(character.encode("utf-8"))
        offsets[byte_offset] = character_offset
    return offsets


def _overlaps_any(
    start: int,
    end: int,
    ranges: list[tuple[int, int]],
) -> bool:
    return any(
        start < range_end and end > range_start for range_start, range_end in ranges
    )


def load_file_references() -> list[str]:
    """Load the recency-ordered file-reference history from disk.

    Returns:
        Ordered list of paths, most recently referenced first.  Empty
        list if the file is missing or cannot be parsed.
    """
    history_file = _history_file()
    if not history_file.exists():
        return []
    try:
        with open(history_file, encoding="utf-8") as f:
            data = json.load(f)
        paths = data.get("paths", [])
        return [p for p in paths if isinstance(p, str) and not _is_local_sase_path(p)]
    except (OSError, json.JSONDecodeError):
        return []


def _write_history(paths: list[str]) -> None:
    """Atomically overwrite the history file with *paths*."""
    try:
        history_file = _history_file()
        history_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = history_file.with_suffix(history_file.suffix + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump({"paths": paths}, f, indent=2)
        os.replace(tmp_path, history_file)
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
    history_file = _history_file()
    if not history_file.exists():
        return
    try:
        with open(history_file, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return
    raw_paths = data.get("paths", [])
    existing = [p for p in raw_paths if isinstance(p, str)]
    remaining = [p for p in existing if p != path]
    if len(remaining) == len(existing):
        return
    _write_history(remaining)
