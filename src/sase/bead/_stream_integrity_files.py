"""Path predicates and JSONL file IO for bead event streams.

The append-only guards in :mod:`sase.bead._stream_integrity` work on
``events/streams/*.jsonl`` files. This module owns recognizing those paths
and moving events between them and Python objects; it knows nothing about
git or about what makes one version of a stream a valid successor of
another.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_STREAM_DIR_PARTS = ("events", "streams")


def is_event_stream_relpath(path: str) -> bool:
    """Return whether *path* is a canonical ``events/streams/*.jsonl`` file."""
    parts = Path(path).parts
    if len(parts) < 3 or not parts[-1].endswith(".jsonl"):
        return False
    return parts[-3:-1] == _STREAM_DIR_PARTS


def stream_dir_relpath(repo_root: Path, beads_dir: Path) -> str:
    """Return the repo-relative event-stream directory for *beads_dir*."""
    try:
        relative = beads_dir.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return "/".join(_STREAM_DIR_PARTS)
    if relative in {".", ""}:
        return "/".join(_STREAM_DIR_PARTS)
    return f"{relative}/{'/'.join(_STREAM_DIR_PARTS)}"


def parse_stream_text(text: str) -> list[dict[str, Any]]:
    """Parse one JSONL event stream into objects."""
    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            events.append(payload)
    return events


def encode_stream_events(events: list[dict[str, Any]]) -> str:
    """Encode events the way the Rust store writer emits JSONL."""
    return "".join(
        json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n"
        for event in events
    )


def worktree_streams(
    repo_root: Path,
    stream_paths: list[str],
) -> dict[str, list[dict[str, Any]]]:
    """Read every stream living beside *stream_paths* in the worktree."""
    streams: dict[str, list[dict[str, Any]]] = {}
    seen_dirs: set[Path] = set()
    for path in stream_paths:
        stream_dir = (repo_root / path).parent
        if stream_dir in seen_dirs or not stream_dir.is_dir():
            continue
        seen_dirs.add(stream_dir)
        for candidate in sorted(stream_dir.glob("*.jsonl")):
            try:
                streams[candidate.stem] = parse_stream_text(
                    candidate.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                continue
    return streams


def read_worktree_events(repo_root: Path, relpath: str) -> list[dict[str, Any]]:
    """Parse the worktree copy of *relpath*, or ``[]`` when it is absent."""
    path = repo_root / relpath
    if not path.is_file():
        return []
    return parse_stream_text(path.read_text(encoding="utf-8"))


def write_stream_text(repo_root: Path, relpath: str, text: str) -> None:
    """Overwrite the worktree copy of *relpath* with *text*."""
    path = repo_root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
