"""Write the resolver's merged bead-store back to the worktree."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_resolved_store(
    beads_dir: Path,
    repo_root: Path,
    streams: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    manifest: dict[str, Any],
    merged_stream_ids: set[str],
) -> list[str]:
    """Write the resolved store, touching only what the merge actually changed.

    The derived manifest and ``issues.jsonl`` stay authoritative because they
    are reduced from every stream. The per-stream files, however, are inputs
    for all but the conflicted ones, so rewriting them byte-for-byte only
    widens the window in which another writer sees a churning worktree. Even
    conflicted streams keep raw input event dicts when the merge did not change
    that event's meaning, because legacy compatibility fields such as
    ``payload.issue.notes`` are lossy if replayed through the typed wire.

    That skip only holds while this encoding is byte-identical to the Rust
    store writer's, which emits unescaped UTF-8 via ``serde_json``. Without
    ``ensure_ascii=False`` every stream holding non-ASCII re-encodes to
    ``\\uXXXX``, so the comparison never matches and untouched streams get
    rewritten into the rebase commit as fresh merge rejections.
    """
    streams_dir = beads_dir / "events" / "streams"
    streams_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for stream in streams:
        stream_id = str(stream["stream_id"])
        path = streams_dir / f"{stream_id}.jsonl"
        text = "".join(
            json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n"
            for event in stream.get("events", [])
        )
        if stream_id not in merged_stream_ids and _file_text(path) == text:
            continue
        path.write_text(text, encoding="utf-8")
        written.append(path.relative_to(repo_root).as_posix())

    manifest_path = beads_dir / "events" / "manifest.json"
    # No trailing newline: the Rust writer emits ``serde_json::to_vec_pretty``
    # verbatim, so appending one flips manifest.json's last byte back and forth
    # between the two writers of the same file.
    manifest_text = json.dumps(manifest, indent=2, ensure_ascii=False)
    if _file_text(manifest_path) != manifest_text:
        manifest_path.write_text(manifest_text, encoding="utf-8")
    written.append(manifest_path.relative_to(repo_root).as_posix())

    issues_path = beads_dir / "issues.jsonl"
    issues_text = "".join(
        json.dumps(issue, separators=(",", ":"), ensure_ascii=False) + "\n"
        for issue in issues
    )
    if _file_text(issues_path) != issues_text:
        issues_path.write_text(issues_text, encoding="utf-8")
    written.append(issues_path.relative_to(repo_root).as_posix())
    return written


def _file_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None
