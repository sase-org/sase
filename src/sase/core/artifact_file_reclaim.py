"""Lossless conversion of stored automatic artifacts to durable VCS references."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast

from sase._repo_inventory_models import RepoInventory, RepoRecord
from sase.core.artifact_capture_policy import GitVcsProbe, VcsProbe
from sase.core.artifact_file_explicit import (
    read_artifact_file_index,
    store_default_artifact_file,
)
from sase.core.artifact_file_helpers import artifact_file_id
from sase.core.artifact_file_trash import TrashEntry, trash_artifact_files
from sase.core.artifact_file_types import (
    ArtifactFile,
    ArtifactFileAssociation,
    default_artifact_files_index_path,
)
from sase.repo_inventory import collect_repo_inventory


DEFAULT_RECLAIM_MAX_HISTORY_SCAN = 100
_DEFAULT_RECLAIM_GIT_TIMEOUT_SECONDS = 120.0


@dataclass(frozen=True)
class _ReclaimItem:
    """One stored row whose exact bytes exist on a durable VCS ref."""

    old_id: str
    new_id: str
    label: str
    kind: str
    project: str | None
    size_bytes: int
    vcs_repo: str
    vcs_sha: str
    vcs_relpath: str
    checkout_path: str
    row: ArtifactFile

    def to_json_dict(self) -> dict[str, object]:
        """Return the stable, user-facing projection of this item."""

        return {
            "old_id": self.old_id,
            "new_id": self.new_id,
            "label": self.label,
            "kind": self.kind,
            "project": self.project,
            "size_bytes": self.size_bytes,
            "vcs_repo": self.vcs_repo,
            "vcs_sha": self.vcs_sha,
            "vcs_relpath": self.vcs_relpath,
        }


@dataclass(frozen=True)
class _UnresolvedReclaimItem:
    """One row reclaim deliberately left untouched."""

    id: str
    label: str
    project: str | None
    reason: str

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ReclaimPlan:
    """A read-only digest-verified reclaim plan."""

    verified: tuple[_ReclaimItem, ...]
    unresolved: tuple[_UnresolvedReclaimItem, ...]
    reclaimable_bytes: int
    truncated: int

    @property
    def unresolved_counts(self) -> Mapping[str, int]:
        """Return unresolved rows grouped by stable reason."""

        return dict(sorted(Counter(item.reason for item in self.unresolved).items()))

    def to_json_dict(self) -> dict[str, object]:
        return {
            "verified": [item.to_json_dict() for item in self.verified],
            "unresolved": [item.to_json_dict() for item in self.unresolved],
            "unresolved_counts": dict(self.unresolved_counts),
            "verified_rows": len(self.verified),
            "reclaimable_bytes": self.reclaimable_bytes,
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class _ReclaimedArtifactFile:
    """One successful old-row to VCS-row conversion."""

    old_id: str
    new_id: str
    vcs_repo: str
    vcs_sha: str
    vcs_relpath: str
    size_bytes: int
    trash_entry_id: str

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ReclaimResult:
    """Applied reclaim conversions."""

    reclaimed: tuple[_ReclaimedArtifactFile, ...]
    rows_reclaimed: int
    bytes_moved_to_trash: int
    trash_root: str | None

    def to_json_dict(self) -> dict[str, object]:
        return {
            "reclaimed": [item.to_json_dict() for item in self.reclaimed],
            "rows_reclaimed": self.rows_reclaimed,
            "bytes_moved_to_trash": self.bytes_moved_to_trash,
            "trash_root": self.trash_root,
        }


@dataclass
class _CandidateContext:
    row: ArtifactFile
    record: RepoRecord
    checkout_path: str
    relpath: str
    commits: tuple[str, ...] = ()
    matching_commit: str | None = None
    failure_reason: str | None = None


def plan_artifact_file_reclaim(
    *,
    protected_ids: frozenset[str] = frozenset(),
    max_history_scan: int = DEFAULT_RECLAIM_MAX_HISTORY_SCAN,
    limit: int | None = None,
    project: str | None = None,
    index_path: Path | str | None = None,
    inventory: RepoInventory | None = None,
    probe: VcsProbe | None = None,
) -> ReclaimPlan:
    """Find stored rows exactly reproducible from durable remote-tracking refs."""

    if max_history_scan < 1:
        raise ValueError("max_history_scan must be at least 1")
    if limit is not None and limit < 1:
        raise ValueError("limit must be at least 1 when provided")

    rows = read_artifact_file_index(index_path)
    selected_probe = probe or GitVcsProbe(
        timeout_seconds=_DEFAULT_RECLAIM_GIT_TIMEOUT_SECONDS
    )
    unresolved: list[_UnresolvedReclaimItem] = []
    candidate_rows: list[ArtifactFile] = []
    for row in rows:
        if project is not None and row.project != project:
            continue
        reason = _ineligible_reason(row, protected_ids)
        if reason is None:
            candidate_rows.append(row)
        else:
            unresolved.append(_unresolved(row, reason))

    if not candidate_rows:
        return ReclaimPlan((), tuple(unresolved), 0, 0)

    try:
        if inventory is not None:
            resolved_inventory = inventory
        elif project is None:
            resolved_inventory = collect_repo_inventory()
        else:
            resolved_inventory = collect_repo_inventory(project=project)
    except Exception:  # noqa: BLE001 - reclaim must fail safe.
        unresolved.extend(
            _unresolved(row, "inventory_unavailable") for row in candidate_rows
        )
        return ReclaimPlan((), tuple(unresolved), 0, 0)

    contexts: list[_CandidateContext] = []
    for row in candidate_rows:
        try:
            resolved = _resolve_candidate(row, resolved_inventory)
        except Exception:  # noqa: BLE001 - reclaim must fail safe.
            resolved = "repo_resolution_failed"
        if isinstance(resolved, str):
            unresolved.append(_unresolved(row, resolved))
            continue
        contexts.append(resolved)

    by_path: dict[tuple[str, str], list[_CandidateContext]] = defaultdict(list)
    for context in contexts:
        by_path[(context.checkout_path, context.relpath)].append(context)
    for (checkout_path, relpath), path_contexts in by_path.items():
        try:
            commits = selected_probe.durable_candidate_commits(
                checkout_path,
                relpath,
                max_history_scan=max_history_scan,
            )
        except Exception:  # noqa: BLE001 - reclaim must fail safe.
            commits = None
        if commits is None:
            for context in path_contexts:
                context.failure_reason = "vcs_probe_failed"
        elif not commits:
            for context in path_contexts:
                context.failure_reason = "digest_not_found"
        else:
            for context in path_contexts:
                context.commits = commits

    _match_durable_digests(contexts, selected_probe)
    verified: list[_ReclaimItem] = []
    for context in contexts:
        if context.failure_reason is not None:
            unresolved.append(_unresolved(context.row, context.failure_reason))
            continue
        if context.matching_commit is None:
            unresolved.append(_unresolved(context.row, "digest_not_found"))
            continue
        assert context.row.size_bytes is not None
        verified.append(
            _ReclaimItem(
                old_id=context.row.id,
                new_id=_replacement_id(
                    context.row,
                    vcs_repo=context.record.name,
                    vcs_relpath=context.relpath,
                ),
                label=context.row.label,
                kind=context.row.kind,
                project=context.row.project,
                size_bytes=context.row.size_bytes,
                vcs_repo=context.record.name,
                vcs_sha=context.matching_commit,
                vcs_relpath=context.relpath,
                checkout_path=context.checkout_path,
                row=context.row,
            )
        )

    truncated = 0
    if limit is not None and len(verified) > limit:
        truncated = len(verified) - limit
        verified = verified[:limit]
    return ReclaimPlan(
        verified=tuple(verified),
        unresolved=tuple(unresolved),
        reclaimable_bytes=sum(item.size_bytes for item in verified),
        truncated=truncated,
    )


def execute_artifact_file_reclaim(
    plan: ReclaimPlan,
    *,
    index_path: Path | str | None = None,
    now: str | None = None,
) -> ReclaimResult:
    """Write each VCS row before moving its redundant stored row to trash."""

    idx = Path(
        default_artifact_files_index_path() if index_path is None else index_path
    ).expanduser()
    reclaimed: list[_ReclaimedArtifactFile] = []
    trash_root: str | None = None
    for item in plan.verified:
        row = item.row
        assert row.source_path is not None
        association = ArtifactFileAssociation(
            agent_artifacts_dir=row.agent_artifacts_dir or "",
            project=row.project,
            workflow=row.workflow,
            raw_timestamp=row.raw_timestamp,
            agent_name=row.agent_name,
        )
        replacement = store_default_artifact_file(
            row.source_path,
            row.agent_artifacts_dir or "",
            label=row.label,
            kind=row.kind,
            artifact_files_root=idx.parent,
            index_path=idx,
            workspace_dir=row.workspace_dir,
            created_at=row.created_at,
            vcs_repo=item.vcs_repo,
            vcs_sha=item.vcs_sha,
            vcs_relpath=item.vcs_relpath,
            sha256=row.sha256,
            size_bytes=row.size_bytes,
            mime_type=row.mime_type,
            artifact_association=association,
        )
        if replacement is None:  # Reference mode must not depend on a live source.
            raise RuntimeError(f"failed to write VCS replacement for {row.id}")
        if replacement.id != item.new_id:
            raise RuntimeError(
                f"VCS replacement id changed for {row.id}: "
                f"expected {item.new_id}, got {replacement.id}"
            )
        trash = trash_artifact_files(
            [row],
            reason="reclaimed",
            now=now,
            index_path=idx,
        )
        [entry] = trash.entries
        trash_root = trash.trash_root
        reclaimed.append(_execution_item(item, replacement, entry))

    return ReclaimResult(
        reclaimed=tuple(reclaimed),
        rows_reclaimed=len(reclaimed),
        bytes_moved_to_trash=sum(item.size_bytes for item in reclaimed),
        trash_root=trash_root,
    )


def _ineligible_reason(
    row: ArtifactFile,
    protected_ids: frozenset[str],
) -> str | None:
    if row.explicit:
        return "explicit"
    if row.id in protected_ids:
        return "referenced"
    if row.path is None:
        return "already_vcs_backed"
    if not row.sha256:
        return "missing_sha256"
    if row.size_bytes is None:
        return "missing_size"
    if not row.workspace_dir:
        return "missing_workspace_dir"
    if not row.source_path:
        return "missing_source_path"
    workspace = Path(row.workspace_dir).expanduser().resolve(strict=False)
    source = Path(row.source_path).expanduser().resolve(strict=False)
    if not source.is_relative_to(workspace):
        return "source_outside_workspace"
    return None


def _resolve_candidate(
    row: ArtifactFile,
    inventory: RepoInventory,
) -> _CandidateContext | str:
    assert row.workspace_dir is not None
    assert row.source_path is not None
    workspace = Path(row.workspace_dir).expanduser().resolve(strict=False)
    source = Path(row.source_path).expanduser().resolve(strict=False)
    records = [
        record
        for record in inventory.records
        if row.project in {record.project, record.project_key}
    ]
    if not records:
        return "unknown_project"

    relative = source.relative_to(workspace)
    if relative.parts[:2] == ("sase", "repos"):
        nested = [
            (record, root)
            for record in records
            for root in _record_checkout_paths(record)
            if record.kind != "primary"
            and root.is_relative_to(workspace)
            and source.is_relative_to(root)
        ]
        if not nested:
            return "unknown_repo"
        selected_record, recorded_root = max(
            nested,
            key=lambda pair: len(pair[1].parts),
        )
        relpath = source.relative_to(recorded_root).as_posix()
    else:
        primary_record = next(
            (item for item in records if item.kind == "primary"),
            None,
        )
        if primary_record is None:
            return "unknown_repo"
        selected_record = primary_record
        relpath = relative.as_posix()

    checkout = _live_checkout(selected_record)
    if checkout is None:
        return "missing_checkout"
    return _CandidateContext(
        row=row,
        record=selected_record,
        checkout_path=str(checkout),
        relpath=relpath,
    )


def _record_checkout_paths(record: RepoRecord) -> tuple[Path, ...]:
    raw = [record.path, *(clone.path for clone in record.clones)]
    return tuple(
        dict.fromkeys(
            Path(path).expanduser().resolve(strict=False) for path in raw if path
        )
    )


def _live_checkout(record: RepoRecord) -> Path | None:
    try:
        cwd: Path | None = Path.cwd().resolve(strict=False)
    except OSError:
        cwd = None
    paths = _record_checkout_paths(record)
    ordered = sorted(
        paths,
        key=lambda path: (
            0 if cwd is not None and (cwd == path or cwd.is_relative_to(path)) else 1,
            0 if path == Path(record.path).expanduser().resolve(strict=False) else 1,
        ),
    )
    return next((path for path in ordered if path.is_dir()), None)


def _match_durable_digests(
    contexts: Sequence[_CandidateContext],
    probe: VcsProbe,
) -> None:
    by_checkout: dict[str, list[_CandidateContext]] = defaultdict(list)
    for context in contexts:
        if context.commits and context.failure_reason is None:
            by_checkout[context.checkout_path].append(context)
    for checkout, candidates in by_checkout.items():
        specs = [
            f"{commit}:{context.relpath}"
            for context in candidates
            for commit in context.commits
        ]
        try:
            digests = probe.blob_content_digests(checkout, specs)
        except Exception:  # noqa: BLE001 - reclaim must fail safe.
            digests = None
        if digests is None:
            for context in candidates:
                context.failure_reason = "vcs_probe_failed"
            continue
        digest_map = cast(Mapping[str, str | None], digests)
        for context in candidates:
            context.matching_commit = next(
                (
                    commit
                    for commit in context.commits
                    if digest_map.get(f"{commit}:{context.relpath}")
                    == context.row.sha256
                ),
                None,
            )


def _unresolved(row: ArtifactFile, reason: str) -> _UnresolvedReclaimItem:
    return _UnresolvedReclaimItem(row.id, row.label, row.project, reason)


def _execution_item(
    item: _ReclaimItem,
    replacement: ArtifactFile,
    entry: TrashEntry,
) -> _ReclaimedArtifactFile:
    return _ReclaimedArtifactFile(
        old_id=item.old_id,
        new_id=replacement.id,
        vcs_repo=item.vcs_repo,
        vcs_sha=item.vcs_sha,
        vcs_relpath=item.vcs_relpath,
        size_bytes=item.size_bytes,
        trash_entry_id=entry.entry_id,
    )


def _replacement_id(
    row: ArtifactFile,
    *,
    vcs_repo: str,
    vcs_relpath: str,
) -> str:
    association = ArtifactFileAssociation(
        agent_artifacts_dir=row.agent_artifacts_dir or "",
        project=row.project,
        workflow=row.workflow,
        raw_timestamp=row.raw_timestamp,
        agent_name=row.agent_name,
    )
    return artifact_file_id(
        "default",
        association,
        None,
        row.label,
        vcs_repo=vcs_repo,
        vcs_relpath=vcs_relpath,
        sha256=row.sha256,
    )


__all__ = [
    "DEFAULT_RECLAIM_MAX_HISTORY_SCAN",
    "ReclaimPlan",
    "ReclaimResult",
    "execute_artifact_file_reclaim",
    "plan_artifact_file_reclaim",
]
