"""Model-visible commit declaration policy and bounded repository evidence."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sase.core.finalizer_wire import (
    FINALIZER_DEFERRAL_REASONS,
    FinalizerContextWire,
    FinalizerObligationWire,
)
from sase.finalizers.commit_validation import protected_baseline_paths
from sase.finalizers.declaration_recovery_evidence import (
    MAX_PATHS_PER_REPO,
    MAX_TOOL_CALL_PATHS,
    direct_written_paths,
    written_paths_from_tool_calls,
)
from sase.finalizers.declaration_store import HostRepositoryRecord
from sase.llm_provider.commit_finalizer_baseline import (
    DirtyBaseline,
    load_dirty_baseline,
)
from sase.llm_provider.commit_finalizer_git import (
    git_changed_files,
    normalize_path,
    split_pre_existing_changed_files,
)

COMMIT_DECLARATION_RULE = (
    "SASE agents work in ephemeral numbered workspace clones, so uncommitted "
    "work is lost work. The host commits your turn's work by default and does "
    "not need the user to ask. Deferral is a safety valve for a tree that must "
    "not be committed, not the polite default."
)

_PROVENANCE_ALREADY_DIRTY = "already_dirty_at_run_start"
_PROVENANCE_CHANGED = "changed_since_run_start"
_PROVENANCE_NEW = "new_since_run_start"
_PROVENANCE_UNKNOWN = "provenance_unknown"


def build_commit_declaration_context(
    *,
    root: Path,
    context: FinalizerContextWire,
    host_records: Sequence[HostRepositoryRecord],
) -> dict[str, Any]:
    """Return model-visible guidance for authoring commit declarations."""

    records_by_id = {record.obligation_id: record for record in host_records}
    baseline = load_dirty_baseline(root)
    written_paths = written_paths_from_tool_calls(root)
    return {
        "rule": COMMIT_DECLARATION_RULE,
        "default_action": "commit",
        "deferral": {
            "purpose": (
                "Use a typed deferral only when the repository tree itself "
                "must not be committed. The host adjudicates deferrals at "
                "submit time."
            ),
            "reasons": list(FINALIZER_DEFERRAL_REASONS),
        },
        "repository_evidence": [
            _repository_evidence(
                obligation,
                record=records_by_id.get(obligation.obligation_id),
                root=root,
                baseline=baseline,
                written_paths=written_paths,
            )
            for obligation in context.obligations
            if obligation.kind == "repository"
        ],
    }


def _repository_evidence(
    obligation: FinalizerObligationWire,
    *,
    record: HostRepositoryRecord | None,
    root: Path,
    baseline: DirtyBaseline | None,
    written_paths: tuple[str, ...],
) -> dict[str, Any]:
    paths = tuple(obligation.paths)
    run_written = direct_written_paths(
        repo_path=record.path if record is not None else None,
        written_paths=written_paths,
        named_paths=paths,
    )
    protected = _protected_paths(
        root=root,
        repo_path=record.path if record is not None else None,
        obligation_paths=paths,
    )
    provenance = _path_provenance_by_path(
        repo_path=record.path if record is not None else None,
        paths=paths,
        baseline=baseline,
    )
    already_dirty = tuple(
        path for path in paths if provenance.get(path) == _PROVENANCE_ALREADY_DIRTY
    )
    full_path_count = _full_path_count(record, paths)
    capped_paths, omitted_paths = _cap(
        paths,
        MAX_PATHS_PER_REPO,
        total_count=full_path_count,
    )
    capped_written, omitted_written = _cap(run_written, MAX_TOOL_CALL_PATHS)
    capped_dirty, omitted_dirty = _cap(already_dirty, MAX_PATHS_PER_REPO)
    capped_protected, omitted_protected = _cap(protected, MAX_PATHS_PER_REPO)

    payload: dict[str, Any] = {
        "repo_id": obligation.obligation_id,
        "display_name": obligation.display_name or obligation.obligation_id,
        "paths": [
            {
                "path": path,
                "provenance": provenance.get(path, _PROVENANCE_UNKNOWN),
                "written_by_this_run": path in set(run_written),
                "protected": path in set(protected),
            }
            for path in capped_paths
        ],
        "run_written_paths": list(capped_written),
        "already_dirty_at_run_start_paths": list(capped_dirty),
        "protected_paths": list(capped_protected),
    }
    _add_omitted(payload, "omitted_path_count", omitted_paths)
    _add_omitted(payload, "omitted_run_written_path_count", omitted_written)
    _add_omitted(payload, "omitted_already_dirty_path_count", omitted_dirty)
    _add_omitted(payload, "omitted_protected_path_count", omitted_protected)
    return payload


def _path_provenance_by_path(
    *,
    repo_path: str | None,
    paths: tuple[str, ...],
    baseline: DirtyBaseline | None,
) -> dict[str, str]:
    if baseline is None or repo_path is None:
        return dict.fromkeys(paths, _PROVENANCE_UNKNOWN)
    fingerprints = baseline.get(normalize_path(repo_path))
    if fingerprints is None:
        return dict.fromkeys(paths, _PROVENANCE_NEW)

    _run_owned, pre_existing = split_pre_existing_changed_files(
        repo_path,
        list(paths),
        fingerprints,
    )
    pre_existing_set = set(pre_existing)
    return {
        path: (
            _PROVENANCE_ALREADY_DIRTY
            if path in pre_existing_set
            else (_PROVENANCE_CHANGED if path in fingerprints else _PROVENANCE_NEW)
        )
        for path in paths
    }


def _protected_paths(
    *,
    root: Path,
    repo_path: str | None,
    obligation_paths: tuple[str, ...],
) -> tuple[str, ...]:
    if repo_path is None:
        return ()
    protected = set(
        protected_baseline_paths(
            root,
            repo_path,
            get_changed_files=git_changed_files,
        )
    )
    return tuple(path for path in obligation_paths if path in protected)


def _full_path_count(
    record: HostRepositoryRecord | None,
    paths: tuple[str, ...],
) -> int:
    if record is not None and record.path_count is not None:
        return max(record.path_count, len(paths))
    return len(paths)


def _cap(
    paths: tuple[str, ...],
    limit: int,
    *,
    total_count: int | None = None,
) -> tuple[tuple[str, ...], int]:
    capped = paths[:limit]
    return capped, (total_count or len(paths)) - len(capped)


def _add_omitted(payload: dict[str, Any], key: str, count: int) -> None:
    if count > 0:
        payload[key] = count


__all__ = [
    "COMMIT_DECLARATION_RULE",
    "build_commit_declaration_context",
]
