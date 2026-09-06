"""Machine-owned commit reconciliation helpers for ``builtin@commit``.

These used to live on the deprecated ``run_commit_finalizer`` orchestrator.
The generic controller still needs auto-commit, bead publication, and
clean-result classification, so they sit behind this built-in-finalizer API.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.core.finalizer_wire import FinalizerAttemptWire
from sase.finalizers import declaration_store as _declaration_store
from sase.finalizers.commit_repair import (
    load_commit_results,
    marker_matches_repo,
    new_commit_markers,
)
from sase.finalizers.commit_types import (
    BuiltinCommitFinalizerError,
    failed_result,
)
from sase.finalizers.ledger import InstanceLedger
from sase.llm_provider.commit_finalizer_git import (
    auto_commit_done_sdd_plan_status,
    auto_commit_sdd_bead_reprojection_candidate,
    auto_commit_sdd_prompt_qa_candidate,
    dirty_path_fingerprints,
    normalize_path,
    sdd_bead_reprojection_auto_commit_candidates,
    sdd_prompt_qa_auto_commit_candidates,
)
from sase.llm_provider.commit_finalizer_git_paths import normalize_status_path
from sase.llm_provider.commit_finalizer_state import collect_dirty_state
from sase.llm_provider.commit_finalizer_types import (
    BeadStateSyncOutcome,
    DirtyRepo,
    DirtyState,
)
from sase.llm_provider.types import InvokeResult

if TYPE_CHECKING:
    from sase.sdd.store import SddStore

_logger = logging.getLogger(__name__)

_WORKSPACE_NUM_ENV_VARS: tuple[str, ...] = (
    "SASE_AGENT_WORKSPACE_NUM",
    "SASE_GIT_WORKSPACE_NUM",
)


@dataclass(frozen=True)
class PreparedCommitDirtyState:
    """Dirty-state snapshot after machine-owned auto-commits.

    ``dirty_state_before`` and ``fingerprints_before`` are the worktree as it
    existed before bead, plan-status, Q&A, or artifact-link auto-commits.
    Declaration staleness is checked against that snapshot; stitches run
    against ``dirty_state``.
    """

    dirty_state: DirtyState
    done_plan_auto_committed: bool = False
    sdd_prompt_qa_auto_committed: bool = False
    sdd_bead_projection_auto_committed: bool = False
    sdd_store_auto_committed: bool = False
    artifact_links_auto_committed: bool = False
    bead_publication_error: str | None = None
    artifact_link_publication_error: str | None = None
    dirty_state_before: DirtyState | None = None
    fingerprints_before: Mapping[str, Mapping[str, tuple[str, str | None]]] | None = (
        None
    )


def prepare_commit_dirty_state(
    project_dir: str,
    artifacts: Path | None,
) -> PreparedCommitDirtyState:
    """Auto-commit machine-owned SDD/bead work, then rescan remaining dirt."""

    dirty_before = collect_dirty_state(project_dir, artifact_root=artifacts)
    fingerprints_before = {
        normalize_path(repo.path): dict(dirty_path_fingerprints(repo.path))
        for repo in dirty_before.repos
    }
    _, bead_projection_auto_committed = auto_commit_sdd_bead_reprojection_if_possible(
        project_dir,
        dirty_before,
        artifacts,
    )
    bead_sync = auto_commit_separate_sdd_store_if_possible(project_dir, artifacts)
    dirty_state = collect_dirty_state(project_dir, artifact_root=artifacts)
    dirty_state, qa_auto_committed = auto_commit_external_sdd_prompt_qa_if_possible(
        project_dir,
        dirty_state,
        artifacts,
    )
    dirty_state, done_auto_committed = auto_commit_done_plan_status_if_possible(
        project_dir,
        dirty_state,
        artifacts,
    )
    dirty_state, links_auto_committed, link_publication_error = (
        _auto_commit_artifact_link_indexes_if_possible(
            project_dir,
            dirty_state,
            artifacts,
        )
    )
    return PreparedCommitDirtyState(
        dirty_state=dirty_state,
        done_plan_auto_committed=done_auto_committed,
        sdd_prompt_qa_auto_committed=qa_auto_committed,
        sdd_bead_projection_auto_committed=bead_projection_auto_committed,
        sdd_store_auto_committed=bead_sync.committed,
        artifact_links_auto_committed=links_auto_committed,
        bead_publication_error=bead_sync.publication_error,
        artifact_link_publication_error=link_publication_error,
        dirty_state_before=dirty_before,
        fingerprints_before=fingerprints_before,
    )


def pre_reconciliation_dirty_state(state: PreparedCommitDirtyState) -> DirtyState:
    if state.dirty_state_before is not None:
        return state.dirty_state_before
    return state.dirty_state


def pre_reconciliation_fingerprints(
    state: PreparedCommitDirtyState,
    repo: DirtyRepo,
) -> Mapping[str, tuple[str, str | None]] | None:
    snapshots = state.fingerprints_before
    if not snapshots:
        return None
    key = normalize_path(repo.path)
    if key in snapshots:
        return snapshots[key]
    return snapshots.get(repo.path)


def reject_unproven_reconciliation_transition(
    before: DirtyState,
    after: DirtyState,
    *,
    fingerprints_before: Mapping[str, Mapping[str, tuple[str, str | None]]] | None,
    artifacts: Path | None,
    ledger_before: Sequence[Mapping[str, Any]],
    instance_id: str,
    attempt: int,
    ledger: InstanceLedger | None,
    invoke_result: InvokeResult,
) -> None:
    """Fail closed when mixed auto-commits are not attributable."""

    after_by_id = {
        _declaration_store.repository_obligation_id(repo): repo for repo in after.repos
    }
    new_markers = new_commit_markers(ledger_before, load_commit_results(artifacts))
    for repo in before.repos:
        after_repo = after_by_id.get(_declaration_store.repository_obligation_id(repo))
        if after_repo is None:
            continue
        before_paths = set(repo.changed_files)
        after_paths = set(after_repo.changed_files)
        removed = before_paths - after_paths
        added = after_paths - before_paths
        remaining = before_paths & after_paths
        if added:
            _raise_stale_repository_changed(
                repo,
                instance_id,
                attempt=attempt,
                ledger=ledger,
                invoke_result=invoke_result,
            )
        if removed and not any(
            marker_matches_repo(marker, repo) for marker in new_markers
        ):
            if ledger is not None:
                attempt = ledger.allocate_attempt()
            message_text = (
                "Commit finalizer failed: dirty work vanished without an "
                f"attributable commit in {repo.name}"
            )
            raise BuiltinCommitFinalizerError(
                message_text,
                result=failed_result(
                    instance_id,
                    "dirty_work_discarded",
                    message_text,
                    attempts=[
                        FinalizerAttemptWire(
                            attempt=attempt,
                            status="failed",
                            diagnostic_code="dirty_work_discarded",
                        )
                    ],
                ),
                invoke_result=invoke_result,
            )
        if not remaining or fingerprints_before is None:
            continue
        before_fp = fingerprints_before.get(
            normalize_path(repo.path), fingerprints_before.get(repo.path)
        )
        if before_fp is None:
            continue
        after_fp = _declaration_store.dirty_path_fingerprints(repo.path)
        if any(
            _path_fingerprint(before_fp, path) != _path_fingerprint(after_fp, path)
            for path in remaining
        ):
            _raise_stale_repository_changed(
                repo,
                instance_id,
                attempt=attempt,
                ledger=ledger,
                invoke_result=invoke_result,
            )


def _path_fingerprint(
    fingerprints: Mapping[str, tuple[str, str | None]],
    path: str,
) -> tuple[str, str | None] | None:
    if path in fingerprints:
        return fingerprints[path]
    return fingerprints.get(normalize_status_path(path))


def _raise_stale_repository_changed(
    repo: DirtyRepo,
    instance_id: str,
    *,
    attempt: int,
    ledger: InstanceLedger | None,
    invoke_result: InvokeResult,
) -> None:
    if ledger is not None:
        attempt = ledger.allocate_attempt()
    message_text = (
        f"commit declaration is stale; repository {repo.name} changed after submit"
    )
    raise BuiltinCommitFinalizerError(
        message_text,
        result=failed_result(
            instance_id,
            "stale_commit_declaration",
            message_text,
            attempts=[
                FinalizerAttemptWire(
                    attempt=attempt,
                    status="failed",
                    diagnostic_code="stale_commit_declaration",
                )
            ],
        ),
        invoke_result=invoke_result,
    )


def _auto_commit_artifact_link_indexes_if_possible(
    project_dir: str,
    dirty_state: DirtyState,
    artifact_root: Path | None,
) -> tuple[DirtyState, bool, str | None]:
    """Commit machine-owned artifact-link indexes left by implicit reads."""

    indexes, lock_only_roots = _artifact_link_dirty_candidates(dirty_state)
    if not indexes and not lock_only_roots:
        return dirty_state, False, None

    try:
        from sase.sdd._artifact_link_commit import commit_artifact_link_indexes

        store = _resolve_finalizer_sdd_store(project_dir)
        extra: dict[Path, list[Path]] = {root: [] for root in lock_only_roots}
        result = commit_artifact_link_indexes(
            indexes,
            store=store,
            repo_roots=tuple(Path(repo.path) for repo in dirty_state.repos),
            artifacts_dir=artifact_root,
            extra_paths_by_root=extra or None,
            verify_publication=True,
        )
    except Exception:
        _logger.warning(
            "Failed to auto-commit artifact-link indexes during finalization",
            exc_info=True,
        )
        return dirty_state, False, None

    if not result.committed and not result.publication_error:
        return dirty_state, False, None
    refreshed = collect_dirty_state(project_dir, artifact_root=artifact_root)
    return refreshed, result.committed, result.publication_error


def auto_commit_done_plan_status_if_possible(
    project_dir: str,
    dirty_state: DirtyState,
    artifact_root: Path | None,
) -> tuple[DirtyState, bool]:
    """Commit an SDD plan whose only remaining edit is a done-status flip."""

    if not dirty_state.repos:
        return dirty_state, False
    if not auto_commit_done_sdd_plan_status(dirty_state):
        return dirty_state, False
    refreshed = collect_dirty_state(project_dir, artifact_root=artifact_root)
    return refreshed, True


def auto_commit_sdd_bead_reprojection_if_possible(
    project_dir: str,
    dirty_state: DirtyState,
    artifact_root: Path | None,
) -> tuple[DirtyState, bool]:
    """Best-effort safety net for proven beads ``issues.jsonl`` reprojections."""

    candidates = sdd_bead_reprojection_auto_commit_candidates(dirty_state)
    if not candidates:
        return dirty_state, False

    committed_any = False
    for candidate in candidates:
        try:
            committed_any = (
                auto_commit_sdd_bead_reprojection_candidate(
                    candidate,
                    artifacts_dir=artifact_root,
                )
                or committed_any
            )
        except Exception:
            _logger.warning(
                "Failed to auto-commit beads-sidecar issues.jsonl reprojection in %s",
                candidate.repo_dir,
                exc_info=True,
            )

    if not committed_any:
        return dirty_state, False
    refreshed = collect_dirty_state(project_dir, artifact_root=artifact_root)
    return refreshed, True


def auto_commit_external_sdd_prompt_qa_if_possible(
    project_dir: str,
    dirty_state: DirtyState,
    artifact_root: Path | None,
) -> tuple[DirtyState, bool]:
    """Best-effort safety net for proven Q&A-only external prompt edits."""

    candidates = sdd_prompt_qa_auto_commit_candidates(dirty_state)
    if not candidates:
        return dirty_state, False

    committed_any = False
    for candidate in candidates:
        try:
            committed_any = (
                auto_commit_sdd_prompt_qa_candidate(candidate) or committed_any
            )
        except Exception:
            _logger.warning(
                "Failed to auto-commit agents-sidecar prompt Q&A in %s",
                candidate.repo_dir,
                exc_info=True,
            )

    if not committed_any:
        return dirty_state, False
    refreshed = collect_dirty_state(project_dir, artifact_root=artifact_root)
    return refreshed, True


def auto_commit_separate_sdd_store_if_possible(
    project_dir: str, artifacts_dir: Path | None = None
) -> BeadStateSyncOutcome:
    """Commit and publish machine-managed external bead state.

    Committing is not enough on its own: the configured push policy may be
    queued, detached, or aimed at a different checkout than the one holding the
    commit, so a finalizer-created bead commit is verified as published and the
    failure is reported rather than left to die with the workspace.
    """

    beads_root = _auto_commit_bead_state(project_dir, artifacts_dir)
    if beads_root is None:
        return BeadStateSyncOutcome()
    return BeadStateSyncOutcome(
        committed=True,
        publication_error=_unpublished_bead_state_error(beads_root),
    )


def clean_result_reason(
    *,
    done_plan_auto_committed: bool,
    sdd_prompt_qa_auto_committed: bool,
    sdd_store_auto_committed: bool,
    sdd_bead_projection_auto_committed: bool = False,
    artifact_links_auto_committed: bool = False,
) -> str:
    """Classify a clean commit outcome after machine-owned auto-commits."""

    auto_committed: list[str] = []
    if done_plan_auto_committed:
        auto_committed.append("done_plan_status")
    if sdd_prompt_qa_auto_committed:
        auto_committed.append("sdd_prompt_qa")
    if sdd_bead_projection_auto_committed:
        auto_committed.append("sdd_bead_projection")
    if sdd_store_auto_committed:
        auto_committed.append("sdd_store")
    if artifact_links_auto_committed:
        auto_committed.append("artifact_links")
    if not auto_committed:
        return "no_changes"
    return "auto_committed_" + "_and_".join(auto_committed)


def _artifact_link_dirty_candidates(
    dirty_state: DirtyState,
) -> tuple[list[Path], list[Path]]:
    """Return eligible link indexes and roots whose only link dirt is locks."""

    from sase.sdd._artifact_link_files import (
        ArtifactLinkRepoFileKind,
        classify_artifact_link_repo_file,
    )

    indexes: list[Path] = []
    lock_only_roots: list[Path] = []
    for repo in dirty_state.repos:
        repo_root = Path(repo.path)
        has_index = False
        has_lock = False
        for rel in repo.changed_files:
            path = repo_root / _porcelain_path(rel)
            kind = classify_artifact_link_repo_file(path, repo_root)
            if kind is ArtifactLinkRepoFileKind.INDEX:
                indexes.append(path)
                has_index = True
            elif kind is ArtifactLinkRepoFileKind.LOCK:
                has_lock = True
        if has_lock and not has_index:
            lock_only_roots.append(repo_root)
    return indexes, lock_only_roots


def _porcelain_path(relative: str) -> str:
    raw = relative.strip()
    if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
        raw = raw[1:-1]
    if " -> " in raw:
        raw = raw.split(" -> ", 1)[1].strip().strip('"')
    return raw


def _resolve_finalizer_sdd_store(project_dir: str) -> SddStore | None:
    """Resolve the workspace SDD store used by machine-owned auto-commits."""

    from sase.sdd.store import (
        SDD_STORAGE_SEPARATE_REPO,
        SDD_STORAGE_SIDECAR_REPOS,
        resolve_sdd_store,
    )

    workspace_num = _finalizer_workspace_num(project_dir)
    store = resolve_sdd_store(project_dir, workspace_num)
    if store.storage not in {SDD_STORAGE_SEPARATE_REPO, SDD_STORAGE_SIDECAR_REPOS}:
        return None
    return store


def _auto_commit_bead_state(
    project_dir: str, artifacts_dir: Path | None
) -> Path | None:
    """Best-effort commit of leftover bead state; returns the store committed."""

    try:
        if not _separate_sdd_store_repo_may_exist(project_dir):
            return None

        from sase.sdd.files import commit_sdd_store_files
        from sase.sdd.store import (
            SDD_STORAGE_SEPARATE_REPO,
            SDD_STORAGE_SIDECAR_REPOS,
            resolve_sdd_store,
        )

        workspace_num = _finalizer_workspace_num(project_dir)
        store = resolve_sdd_store(project_dir, workspace_num)
        if store.storage not in {
            SDD_STORAGE_SEPARATE_REPO,
            SDD_STORAGE_SIDECAR_REPOS,
        }:
            return None
        repo_roots = (
            [store.repo_root_for_kind(role) for role in store.split_sidecar_roles()]
            if store.is_sidecar_storage
            else [store.repo_root]
        )
        if not any((root / ".git").exists() for root in repo_roots):
            return None
        beads_root = store.kind_root("beads")
        from sase.bead.sync import bead_state_is_clean

        if bead_state_is_clean(beads_root):
            return None
        committed = commit_sdd_store_files(
            store,
            "chore(beads): sync bead state",
            auto_commit_type="beads",
            paths=[beads_root],
            artifacts_dir=artifacts_dir,
        )
        return beads_root if committed else None
    except Exception:
        _logger.warning(
            "Failed to auto-commit separate SDD store during finalization",
            exc_info=True,
        )
        return None


def _unpublished_bead_state_error(beads_root: Path) -> str | None:
    """Publish the finalizer's bead commit; report it when it stayed local."""

    from sase.bead.cli_common import (
        BeadPublicationError,
        ensure_bead_mutation_published,
    )

    try:
        ensure_bead_mutation_published(
            beads_root,
            description="finalizer bead-state sync commit",
        )
    except BeadPublicationError as exc:
        return exc.diagnostic
    except Exception:
        _logger.warning(
            "Failed to verify publication of the finalizer bead-state commit",
            exc_info=True,
        )
    return None


def _separate_sdd_store_repo_may_exist(project_dir: str) -> bool:
    """Return whether a legacy or split external SDD clone is present."""

    project_path = Path(project_dir).expanduser()
    primary_candidates = [project_path]

    try:
        from sase.workspace_provider.marker import find_marker_from_cwd

        found = find_marker_from_cwd(str(project_path))
    except Exception:
        found = None
    if found is not None and found[1].primary_workspace_dir:
        primary_candidates.append(Path(found[1].primary_workspace_dir))

    workspace_num = _workspace_num_from_env()
    if workspace_num is not None and workspace_num > 1:
        suffix_primary = _suffix_stripped_primary_workspace(project_path, workspace_num)
        if suffix_primary is not None:
            primary_candidates.append(suffix_primary)

    if any(
        (candidate / ".sase" / "sdd" / ".git").exists()
        for candidate in primary_candidates
    ):
        return True

    try:
        from sase.linked_repos import sidecar_repo_clone_dir
        from sase.sdd.store import read_sdd_store_record

        for primary in primary_candidates:
            record = read_sdd_store_record(primary)
            if record is None or not record.is_sidecar_storage:
                continue
            for kind in record.sidecars:
                clone = Path(sidecar_repo_clone_dir(project_path, kind))
                if (clone / ".git").exists():
                    return True
    except Exception:
        return False
    return False


def _suffix_stripped_primary_workspace(
    project_path: Path,
    workspace_num: int,
) -> Path | None:
    suffix = f"_{workspace_num}"
    parts = list(project_path.parts)
    for index in range(len(parts) - 1, -1, -1):
        if parts[index].endswith(suffix):
            parts[index] = parts[index][: -len(suffix)]
            return Path(*parts)
    return None


def _finalizer_workspace_num(project_dir: str) -> int:
    project_file = os.environ.get("SASE_AGENT_PROJECT_FILE")
    if project_file:
        workspace_num = _workspace_num_for_project_file(project_file, project_dir)
        if workspace_num is not None:
            return workspace_num

    workspace_num = _workspace_num_from_env()
    if workspace_num is not None:
        return workspace_num
    return 1


def _workspace_num_for_project_file(project_file: str, project_dir: str) -> int | None:
    env_num = _workspace_num_from_env()
    if env_num is not None:
        return env_num

    try:
        from sase.workspace_provider.utils import parse_workspace_dir

        primary_dir = parse_workspace_dir(project_file)
    except Exception:
        return None

    if not primary_dir:
        return None

    primary_path = Path(normalize_path(primary_dir))
    project_path = Path(normalize_path(project_dir))
    if project_path == primary_path:
        return 0
    if project_path.parent != primary_path.parent:
        return None

    prefix = f"{primary_path.name}_"
    if not project_path.name.startswith(prefix):
        return None
    suffix = project_path.name[len(prefix) :]
    if not suffix.isdigit():
        return None
    return int(suffix)


def _workspace_num_from_env() -> int | None:
    for key in _WORKSPACE_NUM_ENV_VARS:
        raw = os.environ.get(key)
        if not raw:
            continue
        try:
            return int(raw)
        except ValueError:
            continue
    return None


__all__ = [
    "PreparedCommitDirtyState",
    "auto_commit_done_plan_status_if_possible",
    "auto_commit_external_sdd_prompt_qa_if_possible",
    "auto_commit_sdd_bead_reprojection_if_possible",
    "auto_commit_separate_sdd_store_if_possible",
    "clean_result_reason",
    "pre_reconciliation_dirty_state",
    "pre_reconciliation_fingerprints",
    "prepare_commit_dirty_state",
    "reject_unproven_reconciliation_transition",
]
