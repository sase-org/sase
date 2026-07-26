"""Resolve mechanical git conflicts in the version-controlled bead store."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.bead.project import BEADS_DIRNAME, BEADS_DIRNAME_NON_VC
from sase.core.bead_conflict_facade import (
    event_store_manifest,
    merge_event_streams,
    reduce_event_streams,
)
from sase.git_lock_retry import run_with_git_lock_retry
from sase.sdd._git import sdd_git_command


@dataclass(frozen=True)
class _BeadConflictResolution:
    ok: bool
    message: str
    resolved_files: tuple[str, ...] = ()


def resolve_bead_conflicts(
    cwd: str | Path = ".",
    *,
    beads_dir: str | Path | None = None,
) -> _BeadConflictResolution:
    repo_root = _repo_root(Path(cwd))
    if repo_root is None:
        return _BeadConflictResolution(False, "not inside a git repository")

    conflicted = _conflicted_files(repo_root)
    if not conflicted:
        return _BeadConflictResolution(True, "no conflicted bead files")
    resolved_beads_dir = resolve_beads_dir(repo_root, beads_dir)
    if resolved_beads_dir is None:
        return _BeadConflictResolution(
            False,
            "non-bead conflicts remain: " + ", ".join(conflicted),
        )
    bead_prefix = resolved_beads_dir.relative_to(repo_root).as_posix()

    bead_conflicts = [path for path in conflicted if _is_bead_path(path, bead_prefix)]
    if not bead_conflicts:
        return _BeadConflictResolution(
            False,
            "non-bead conflicts remain: " + ", ".join(conflicted),
        )
    non_bead = [path for path in conflicted if not _is_bead_path(path, bead_prefix)]
    if non_bead:
        return _BeadConflictResolution(
            False,
            "non-bead conflicts remain: " + ", ".join(non_bead),
        )

    unsupported = [
        path
        for path in bead_conflicts
        if not _is_mergeable_bead_path(path, bead_prefix)
    ]
    if unsupported:
        return _BeadConflictResolution(
            False,
            "unsupported bead conflicts: " + ", ".join(unsupported),
        )

    streams = _load_worktree_streams(
        resolved_beads_dir,
        repo_root,
        set(bead_conflicts),
    )
    for path in bead_conflicts:
        if not _is_event_stream_path(path, bead_prefix):
            continue
        stream_id = Path(path).stem
        base = _read_stage_stream(repo_root, path, 1, stream_id)
        upstream_stage, local_stage = _upstream_and_local_stages(repo_root)
        upstream = _read_stage_stream(repo_root, path, upstream_stage, stream_id)
        local = _read_stage_stream(repo_root, path, local_stage, stream_id)
        merged = merge_event_streams(base, local, upstream)
        streams[stream_id] = merged

    ordered_streams = [streams[key] for key in sorted(streams)]
    issues = reduce_event_streams(ordered_streams)
    manifest = event_store_manifest(ordered_streams)

    resolved_paths = _write_resolved_store(
        resolved_beads_dir,
        repo_root,
        ordered_streams,
        issues,
        manifest,
    )
    resolved_paths.extend(path for path in bead_conflicts if path not in resolved_paths)
    resolved_paths = sorted(dict.fromkeys(resolved_paths))
    _git_add(repo_root, resolved_paths)

    return _BeadConflictResolution(
        True,
        "resolved bead conflicts: " + ", ".join(resolved_paths),
        tuple(resolved_paths),
    )


def _repo_root(cwd: Path) -> Path | None:
    # The resolver's direct probes are read-only; only _git_add can contend on
    # index.lock and is routed through the shared retry policy below.
    result = subprocess.run(
        sdd_git_command(["rev-parse", "--show-toplevel"]),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip())


def _conflicted_files(repo_root: Path) -> list[str]:
    result = subprocess.run(
        sdd_git_command(["diff", "--name-only", "--diff-filter=U"]),
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def resolve_beads_dir(
    repo_root: Path, beads_dir: str | Path | None = None
) -> Path | None:
    root = repo_root.expanduser().resolve()
    canonical_relpaths = {BEADS_DIRNAME, BEADS_DIRNAME_NON_VC}
    if beads_dir is not None:
        resolved = Path(beads_dir).expanduser().resolve()
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError:
            return None
        if relative not in canonical_relpaths or not resolved.is_dir():
            return None
        return resolved
    candidates = [
        (root / dirname).resolve()
        for dirname in (BEADS_DIRNAME, BEADS_DIRNAME_NON_VC)
        if (root / dirname).is_dir()
    ]
    return candidates[0] if len(candidates) == 1 else None


def _is_bead_path(path: str, bead_prefix: str) -> bool:
    return path == bead_prefix or path.startswith(f"{bead_prefix}/")


def _is_event_stream_path(path: str, bead_prefix: str) -> bool:
    prefix = f"{bead_prefix}/events/streams/"
    return path.startswith(prefix) and path.endswith(".jsonl")


def _is_mergeable_bead_path(path: str, bead_prefix: str) -> bool:
    return path in {
        f"{bead_prefix}/issues.jsonl",
        f"{bead_prefix}/events/manifest.json",
    } or _is_event_stream_path(path, bead_prefix)


def _load_worktree_streams(
    beads_dir: Path,
    repo_root: Path,
    conflicted_paths: set[str],
) -> dict[str, dict[str, Any]]:
    streams_dir = beads_dir / "events" / "streams"
    streams: dict[str, dict[str, Any]] = {}
    if not streams_dir.is_dir():
        return streams
    for path in sorted(streams_dir.glob("*.jsonl")):
        rel = path.relative_to(repo_root).as_posix()
        if rel in conflicted_paths:
            continue
        streams[path.stem] = _parse_stream_text(
            path.read_text(encoding="utf-8"), path.stem
        )
    return streams


def _read_stage_stream(
    repo_root: Path, path: str, stage: int, stream_id: str
) -> dict[str, Any]:
    result = subprocess.run(
        sdd_git_command(["show", f":{stage}:{path}"]),
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return _empty_stream(stream_id)
    return _parse_stream_text(result.stdout, stream_id)


def _parse_stream_text(text: str, stream_id: str) -> dict[str, Any]:
    events = [json.loads(line) for line in text.splitlines() if line.strip()]
    return {"stream_id": stream_id, "root_issue_id": stream_id, "events": events}


def _empty_stream(stream_id: str) -> dict[str, Any]:
    return {"stream_id": stream_id, "root_issue_id": stream_id, "events": []}


def _upstream_and_local_stages(repo_root: Path) -> tuple[int, int]:
    git_dir = _git_dir(repo_root)
    if git_dir and (
        (git_dir / "rebase-merge").is_dir() or (git_dir / "rebase-apply").is_dir()
    ):
        return (2, 3)
    return (3, 2)


def _git_dir(repo_root: Path) -> Path | None:
    result = subprocess.run(
        sdd_git_command(["rev-parse", "--git-dir"]),
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    path = Path(result.stdout.strip())
    if path.is_absolute():
        return path
    return repo_root / path


def _write_resolved_store(
    beads_dir: Path,
    repo_root: Path,
    streams: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> list[str]:
    streams_dir = beads_dir / "events" / "streams"
    streams_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for stream in streams:
        stream_id = str(stream["stream_id"])
        path = streams_dir / f"{stream_id}.jsonl"
        text = "".join(
            json.dumps(event, separators=(",", ":")) + "\n"
            for event in stream.get("events", [])
        )
        path.write_text(text, encoding="utf-8")
        written.append(path.relative_to(repo_root).as_posix())

    manifest_path = beads_dir / "events" / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    written.append(manifest_path.relative_to(repo_root).as_posix())

    issues_path = beads_dir / "issues.jsonl"
    issues_path.write_text(
        "".join(json.dumps(issue, separators=(",", ":")) + "\n" for issue in issues),
        encoding="utf-8",
    )
    written.append(issues_path.relative_to(repo_root).as_posix())
    return written


def _git_add(repo_root: Path, paths: list[str]) -> None:
    if paths:
        result, _outcome = run_with_git_lock_retry(
            lambda: subprocess.run(
                sdd_git_command(["add", "--", *paths]),
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=False,
            ),
            cwd=repo_root,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(detail or f"git add failed with {result.returncode}")


def handle_resolve_conflicts_command() -> int:
    beads_dir: Path | None = None
    cwd = Path.cwd()
    try:
        from sase.bead.cli_common import resolve_beads_location

        location = resolve_beads_location(require_existing=True)
        if location is not None:
            cwd = location.root
            beads_dir = location.beads_dir
    except Exception:
        pass
    result = resolve_bead_conflicts(cwd, beads_dir=beads_dir)
    stream = sys.stdout if result.ok else sys.stderr
    print(result.message, file=stream)
    return 0 if result.ok else 1


__all__ = [
    "handle_resolve_conflicts_command",
    "resolve_beads_dir",
    "resolve_bead_conflicts",
]
