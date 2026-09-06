"""Resolve mechanical git conflicts in the version-controlled bead store."""

from __future__ import annotations

from dataclasses import dataclass
import sys
from pathlib import Path

from sase.bead.config import load_config, save_config
from sase.bead.ids import issue_id_for_counter, max_counter_in_ids
from sase.bead.project import BEADS_DIRNAME_ROOT
from sase.bead.relocation import BeadIdRelocation, normalize_bead_relocations
from sase.core.bead_conflict_facade import (
    event_store_manifest,
    merge_event_streams_with_relocation,
    reduce_event_streams,
)

from .conflict_resolver_config import (
    config_with_allocated_counter as _config_with_allocated_counter,
    merged_conflicted_config as _merged_conflicted_config,
)
from .conflict_resolver_git import (
    GitProbeFailure as _GitProbeFailure,
    conflicted_files as _conflicted_files,
    git_add as _git_add,
    git_repo_root as _git_repo_root,
    unmerged_stages as _unmerged_stages,
    upstream_and_local_stages as _upstream_and_local_stages,
)
from .conflict_resolver_paths import (
    is_bead_path as _is_bead_path,
    is_event_stream_path as _is_event_stream_path,
    is_mergeable_bead_path as _is_mergeable_bead_path,
    is_regenerable_bead_path as _is_regenerable_bead_path,
    resolve_beads_dir,
    store_path as _store_path,
)
from .conflict_resolver_raw_events import (
    raw_event_candidates_by_id as _raw_event_candidates_by_id,
    streams_in_raw_event_preference_order as _streams_in_raw_event_preference_order,
    with_raw_equivalent_events as _with_raw_equivalent_events,
)
from .conflict_resolver_store_writer import (
    write_resolved_store as _write_resolved_store,
)
from .conflict_resolver_streams import (
    load_worktree_streams as _load_worktree_streams,
    read_stage_stream as _read_stage_stream,
    resolve_regenerable_conflicts as _resolve_regenerable_conflicts,
)


@dataclass(frozen=True)
class _BeadConflictResolution:
    ok: bool
    message: str
    resolved_files: tuple[str, ...] = ()
    bead_relocations: tuple[BeadIdRelocation, ...] = ()


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
    repo_root = _git_repo_root(cwd)
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
    config_path = _store_path(bead_prefix, "config.json")
    merged_config: dict[str, object] | None = None
    if config_path in store_conflicts:
        # load_config json.loads the worktree file; conflict markers raise.
        merged_config = _merged_conflicted_config(repo_root, config_path)
        if merged_config is None:
            return _BeadConflictResolution(
                False,
                "unsupported bead conflicts: " + config_path,
            )
        save_config(resolved_beads_dir, merged_config)
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

    if merged_config is not None:
        merged_config = _config_with_allocated_counter(
            merged_config, relocation_ids.next_counter
        )
        save_config(resolved_beads_dir, merged_config)

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
        config = load_config(beads_dir)
        self._prefix = str(config.get("issue_prefix", "beads"))
        raw_counter = config.get("next_counter", 1)
        minimum = raw_counter if isinstance(raw_counter, int) else 1
        self._counter = max(minimum, max_counter_in_ids(self._prefix, taken_ids) + 1)
        self._taken = set(taken_ids)

    @property
    def next_counter(self) -> int:
        return self._counter

    def allocate(self) -> str:
        while True:
            candidate = issue_id_for_counter(self._prefix, self._counter)
            self._counter += 1
            if candidate not in self._taken:
                self._taken.add(candidate)
                return candidate


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
