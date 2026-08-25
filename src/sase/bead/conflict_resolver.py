"""Resolve mechanical git conflicts in the version-controlled bead store."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from sase.bead.ids import issue_id_for_counter, max_counter_in_ids
from sase.bead.project import (
    BEADS_DIRNAME,
    BEADS_DIRNAME_NON_VC,
    BEADS_DIRNAME_ROOT,
)
from sase.bead_pages.paths import BEAD_PAGES_DIRNAME
from sase.core.bead_conflict_facade import (
    event_store_manifest,
    merge_event_streams_with_relocation,
    reduce_event_streams,
)
from sase.bead.relocation import BeadIdRelocation, normalize_bead_relocations
from sase.git_lock_retry import run_with_git_lock_retry
from sase.sdd._git import sdd_git_command


@dataclass(frozen=True)
class _BeadConflictResolution:
    ok: bool
    message: str
    resolved_files: tuple[str, ...] = ()
    bead_relocations: tuple[BeadIdRelocation, ...] = ()


class _GitProbeFailure(RuntimeError):
    """A resolver probe could not answer, which is not the same as "clean"."""


_BEAD_STORE_ENTRIES = frozenset(
    {"events", "issues.jsonl", "metadata.json", "config.json"}
)


def resolve_bead_conflicts(
    cwd: str | Path = ".",
    *,
    beads_dir: str | Path | None = None,
) -> _BeadConflictResolution:
    try:
        return _resolve_bead_conflicts(Path(cwd), beads_dir)
    except _GitProbeFailure as error:
        # Reporting a failed probe as success is what let an unresolved or
        # unstaged conflict reach ``git rebase --continue``.
        return _BeadConflictResolution(False, str(error))


def _resolve_bead_conflicts(
    cwd: Path,
    beads_dir: str | Path | None,
) -> _BeadConflictResolution:
    repo_root = _repo_root(cwd)
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
    if bead_prefix == BEADS_DIRNAME_ROOT:
        bead_prefix = ""

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

    regenerable_conflicts = [
        path for path in bead_conflicts if _is_regenerable_bead_path(path, bead_prefix)
    ]
    regenerable_conflict_set = set(regenerable_conflicts)
    store_conflicts = [
        path for path in bead_conflicts if path not in regenerable_conflict_set
    ]
    unsupported = [
        path
        for path in store_conflicts
        if not _is_mergeable_bead_path(path, bead_prefix)
    ]
    if unsupported:
        return _BeadConflictResolution(
            False,
            "unsupported bead conflicts: " + ", ".join(unsupported),
        )
    if not store_conflicts:
        resolved_paths = _resolve_regenerable_conflicts(
            repo_root,
            regenerable_conflicts,
        )
        return _BeadConflictResolution(
            True,
            "resolved bead conflicts: " + ", ".join(resolved_paths),
            tuple(resolved_paths),
        )

    streams = _load_worktree_streams(
        resolved_beads_dir,
        repo_root,
        set(store_conflicts),
    )
    conflicted_streams = sorted(
        path for path in store_conflicts if _is_event_stream_path(path, bead_prefix)
    )
    relocation_ids = _RelocationIds(
        resolved_beads_dir,
        set(streams) | {Path(path).stem for path in conflicted_streams},
    )
    merged_stream_ids: set[str] = set()
    relocated_beads: list[BeadIdRelocation] = []
    for path in conflicted_streams:
        stream_id = Path(path).stem
        stages = _unmerged_stages(repo_root, path)
        base = _read_stage_stream(repo_root, path, 1, stream_id, stages)
        upstream_stage, local_stage = _upstream_and_local_stages(repo_root)
        upstream = _read_stage_stream(
            repo_root, path, upstream_stage, stream_id, stages
        )
        local = _read_stage_stream(repo_root, path, local_stage, stream_id, stages)
        raw_events = _raw_event_candidates_by_id(
            _streams_in_raw_event_preference_order(
                base=base,
                upstream=upstream,
                upstream_stage=upstream_stage,
                local=local,
                local_stage=local_stage,
            )
        )
        # Reserve the relocation id up front, and for every conflicted stream,
        # so the id a collision lands on depends only on the store's contents
        # and not on which side of the rebase this clone happens to be.
        outcome = merge_event_streams_with_relocation(
            base, local, upstream, relocation_ids.allocate()
        )
        streams[stream_id] = _with_raw_equivalent_events(
            outcome["merged"],
            raw_events,
        )
        merged_stream_ids.add(stream_id)
        relocated = outcome.get("relocated")
        if relocated:
            relocated = _with_raw_equivalent_events(relocated, raw_events)
            relocated_id = str(relocated["stream_id"])
            streams[relocated_id] = relocated
            merged_stream_ids.add(relocated_id)
        relocated_beads.extend(normalize_bead_relocations(outcome))

    ordered_streams = [streams[key] for key in sorted(streams)]
    issues = reduce_event_streams(ordered_streams)
    manifest = event_store_manifest(ordered_streams)

    resolved_paths = _write_resolved_store(
        resolved_beads_dir,
        repo_root,
        ordered_streams,
        issues,
        manifest,
        merged_stream_ids,
    )
    staged_paths = _resolve_regenerable_conflicts(repo_root, regenerable_conflicts)
    resolved_paths.extend(
        path for path in store_conflicts if path not in resolved_paths
    )
    resolved_paths.extend(staged_paths)
    resolved_paths = sorted(dict.fromkeys(resolved_paths))
    _git_add(repo_root, [path for path in resolved_paths if path not in staged_paths])

    message = "resolved bead conflicts: " + ", ".join(resolved_paths)
    if relocated_beads:
        message += "; relocated duplicate beads: " + ", ".join(
            f"{relocation.old_id} -> {relocation.new_id}"
            for relocation in relocated_beads
        )
    return _BeadConflictResolution(
        True,
        message,
        tuple(resolved_paths),
        tuple(relocated_beads),
    )


class _RelocationIds:
    """Hand out top-level bead ids no stream in this store already owns.

    Two clones minting from their own ``next_counter`` can allocate the same
    id, and the loser of that collision has to move somewhere. Only the
    resolver can see the whole store, so it — not the per-stream merge — owns
    picking the free id.
    """

    def __init__(self, beads_dir: Path, taken_ids: set[str]) -> None:
        from sase.bead.config import load_config

        config = load_config(beads_dir)
        self._prefix = str(config.get("issue_prefix", "beads"))
        raw_counter = config.get("next_counter", 1)
        minimum = raw_counter if isinstance(raw_counter, int) else 1
        self._counter = max(minimum, max_counter_in_ids(self._prefix, taken_ids) + 1)
        self._taken = set(taken_ids)

    def allocate(self) -> str:
        while True:
            candidate = issue_id_for_counter(self._prefix, self._counter)
            self._counter += 1
            if candidate not in self._taken:
                self._taken.add(candidate)
                return candidate


def _run_git(cwd: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run one resolver git command under the shared git-lock retry policy.

    The resolver's probes are not lock-free: ``git diff`` refreshes the index
    and therefore takes ``index.lock``, so a concurrent bead-store writer can
    fail a probe that has nothing to do with the conflict being resolved.
    """
    result, _outcome = run_with_git_lock_retry(
        lambda: subprocess.run(
            sdd_git_command(args),
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        ),
        cwd=cwd,
    )
    return result


def _probe_failure(message: str, result: subprocess.CompletedProcess[str]) -> str:
    detail = (result.stderr or result.stdout or "").strip()
    return f"{message}: {detail}" if detail else f"{message} (exit {result.returncode})"


def _repo_root(cwd: Path) -> Path | None:
    result = _run_git(cwd, ["rev-parse", "--show-toplevel"])
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip())


def _conflicted_files(repo_root: Path) -> list[str]:
    result = _run_git(repo_root, ["diff", "--name-only", "--diff-filter=U"])
    if result.returncode != 0:
        raise _GitProbeFailure(
            _probe_failure("could not list conflicted bead files", result)
        )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def resolve_beads_dir(
    repo_root: Path, beads_dir: str | Path | None = None
) -> Path | None:
    root = repo_root.expanduser().resolve()
    canonical_relpaths = {
        BEADS_DIRNAME,
        BEADS_DIRNAME_NON_VC,
        BEADS_DIRNAME_ROOT,
    }
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
    if (root / "config.json").is_file():
        candidates.append(root)
    return candidates[0] if len(set(candidates)) == 1 else None


def _is_bead_path(path: str, bead_prefix: str) -> bool:
    if not bead_prefix:
        return bool(Path(path).parts) and (
            Path(path).parts[0] in _BEAD_STORE_ENTRIES
            or _is_regenerable_bead_path(path, bead_prefix)
        )
    return path == bead_prefix or path.startswith(f"{bead_prefix}/")


def _is_regenerable_bead_path(path: str, bead_prefix: str) -> bool:
    parts = Path(path).parts
    return not bead_prefix and len(parts) > 1 and parts[0] == BEAD_PAGES_DIRNAME


def _is_event_stream_path(path: str, bead_prefix: str) -> bool:
    prefix = f"{_store_path(bead_prefix, 'events/streams')}/"
    return path.startswith(prefix) and path.endswith(".jsonl")


def _is_mergeable_bead_path(path: str, bead_prefix: str) -> bool:
    return path in {
        _store_path(bead_prefix, "issues.jsonl"),
        _store_path(bead_prefix, "events/manifest.json"),
    } or _is_event_stream_path(path, bead_prefix)


def _store_path(prefix: str, rest: str) -> str:
    """Join one store-relative path without a leading slash at repo root."""

    return f"{prefix}/{rest}" if prefix else rest


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


def _unmerged_stages(repo_root: Path, path: str) -> frozenset[int]:
    """Return which conflict stages *path* actually has in the index.

    Knowing this up front is what lets :func:`_read_stage_stream` treat a
    ``git show`` failure as an error instead of silently substituting an empty
    stream, which would drop one side of the merge.
    """
    result = _run_git(repo_root, ["ls-files", "--unmerged", "-z", "--", path])
    if result.returncode != 0:
        raise _GitProbeFailure(
            _probe_failure(f"could not read conflict stages for {path}", result)
        )
    stages: set[int] = set()
    for entry in result.stdout.split("\0"):
        head, _, _ = entry.partition("\t")
        fields = head.split()
        if len(fields) == 3 and fields[2].isdigit():
            stages.add(int(fields[2]))
    return frozenset(stages)


def _read_stage_stream(
    repo_root: Path,
    path: str,
    stage: int,
    stream_id: str,
    stages: frozenset[int],
) -> dict[str, Any]:
    if stage not in stages:
        # A genuinely absent stage (add/add conflicts have no base) is empty.
        return _empty_stream(stream_id)
    result = _run_git(repo_root, ["show", f":{stage}:{path}"])
    if result.returncode != 0:
        raise _GitProbeFailure(
            _probe_failure(f"could not read stage {stage} of {path}", result)
        )
    return _parse_stream_text(result.stdout, stream_id)


def _resolve_regenerable_conflicts(repo_root: Path, paths: list[str]) -> list[str]:
    resolved: list[str] = []
    for path in sorted(paths):
        _resolve_regenerable_conflict(repo_root, path)
        resolved.append(path)
    return resolved


def _resolve_regenerable_conflict(repo_root: Path, path: str) -> None:
    upstream_stage, _local_stage = _upstream_and_local_stages(repo_root)
    stages = _unmerged_stages(repo_root, path)
    if upstream_stage not in stages:
        _git_rm(repo_root, path)
        return

    result = _run_git(repo_root, ["show", f":{upstream_stage}:{path}"])
    if result.returncode != 0:
        raise _GitProbeFailure(
            _probe_failure(f"could not read stage {upstream_stage} of {path}", result)
        )
    target = repo_root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(result.stdout, encoding="utf-8")
    _git_add(repo_root, [path])


def _parse_stream_text(text: str, stream_id: str) -> dict[str, Any]:
    events = [json.loads(line) for line in text.splitlines() if line.strip()]
    return {"stream_id": stream_id, "root_issue_id": stream_id, "events": events}


def _empty_stream(stream_id: str) -> dict[str, Any]:
    return {"stream_id": stream_id, "root_issue_id": stream_id, "events": []}


def _streams_in_raw_event_preference_order(
    *,
    base: dict[str, Any],
    upstream: dict[str, Any],
    upstream_stage: int,
    local: dict[str, Any],
    local_stage: int,
) -> tuple[dict[str, Any], ...]:
    stages = {1: base, upstream_stage: upstream, local_stage: local}
    # Stage 2 is "ours", the current HEAD whose ancestor bytes the
    # append-only guard compares against after the resolver writes the merge.
    return tuple(stages[stage] for stage in (2, 3, 1) if stage in stages)


def _raw_event_candidates_by_id(
    streams: Iterable[dict[str, Any]],
) -> dict[str, tuple[dict[str, Any], ...]]:
    candidates: dict[str, list[dict[str, Any]]] = {}
    for stream in streams:
        events = stream.get("events")
        if not isinstance(events, list):
            continue
        for event in events:
            if not isinstance(event, dict):
                continue
            event_id = event.get("event_id")
            if isinstance(event_id, str):
                candidates.setdefault(event_id, []).append(event)
    return {event_id: tuple(events) for event_id, events in candidates.items()}


def _with_raw_equivalent_events(
    stream: dict[str, Any],
    raw_events_by_id: dict[str, tuple[dict[str, Any], ...]],
) -> dict[str, Any]:
    events = stream.get("events")
    if not isinstance(events, list):
        return stream

    stream_id = str(stream["stream_id"])
    preserved: list[Any] = []
    changed = False
    for event in events:
        raw_event = _raw_equivalent_event(event, stream_id, raw_events_by_id)
        if raw_event is None:
            preserved.append(event)
            continue
        preserved.append(raw_event)
        changed = changed or raw_event is not event
    if not changed:
        return stream
    updated = dict(stream)
    updated["events"] = preserved
    return updated


def _raw_equivalent_event(
    merged_event: Any,
    stream_id: str,
    raw_events_by_id: dict[str, tuple[dict[str, Any], ...]],
) -> dict[str, Any] | None:
    if not isinstance(merged_event, dict):
        return None
    event_id = merged_event.get("event_id")
    if not isinstance(event_id, str):
        return None
    for raw_event in raw_events_by_id.get(event_id, ()):
        if _normalized_raw_event(raw_event, stream_id) == merged_event:
            return raw_event
    return None


def _normalized_raw_event(
    event: dict[str, Any], stream_id: str
) -> dict[str, Any] | None:
    stream = {
        "stream_id": stream_id,
        "root_issue_id": stream_id,
        "events": [event],
    }
    try:
        outcome = merge_event_streams_with_relocation(
            _empty_stream(stream_id),
            stream,
            stream,
            None,
        )
    except Exception:
        return None
    events = outcome.get("merged", {}).get("events", [])
    if len(events) != 1 or not isinstance(events[0], dict):
        return None
    return events[0]


def _upstream_and_local_stages(repo_root: Path) -> tuple[int, int]:
    git_dir = _git_dir(repo_root)
    if (git_dir / "rebase-merge").is_dir() or (git_dir / "rebase-apply").is_dir():
        return (2, 3)
    return (3, 2)


def _git_dir(repo_root: Path) -> Path:
    # A failure here must not fall back to the merge stage order: during a
    # rebase that silently swaps "ours" and "theirs" in the semantic merge.
    result = _run_git(repo_root, ["rev-parse", "--git-dir"])
    if result.returncode != 0:
        raise _GitProbeFailure(_probe_failure("could not locate the git dir", result))
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


def _git_add(repo_root: Path, paths: list[str]) -> None:
    if paths:
        result = _run_git(repo_root, ["add", "--", *paths])
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(detail or f"git add failed with {result.returncode}")


def _git_rm(repo_root: Path, path: str) -> None:
    result = _run_git(repo_root, ["rm", "-r", "-f", "--", path])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(detail or f"git rm failed with {result.returncode}")


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
