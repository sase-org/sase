"""External bead-store sync and reconcile diagnostics for ``builtin@commit``."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from sase.llm_provider.commit_finalizer_git import normalize_path
from sase.llm_provider.commit_finalizer_types import BeadStateSyncOutcome

_logger = logging.getLogger(__name__)

_WORKSPACE_NUM_ENV_VARS: tuple[str, ...] = (
    "SASE_AGENT_WORKSPACE_NUM",
    "SASE_GIT_WORKSPACE_NUM",
)


def auto_commit_separate_sdd_store_if_possible(
    project_dir: str, artifacts_dir: Path | None = None
) -> BeadStateSyncOutcome:
    """Commit and publish machine-managed external bead state.

    Committing is not enough on its own: the configured push policy may be
    queued, detached, or aimed at a different checkout than the one holding the
    commit, so a finalizer-created bead commit is verified as published and the
    failure is reported rather than left to die with the workspace.
    The outcome keeps the sidecar path, remaining files, and the underlying
    commit, lock, integrity, or publication failure so callers can report an
    actionable diagnostic instead of a bare dirty-state failure.
    """

    beads_root, reconcile_error, reconcile_kind = _auto_commit_bead_state(
        project_dir, artifacts_dir
    )
    if beads_root is None and reconcile_error is None:
        return BeadStateSyncOutcome()
    if beads_root is None:
        return BeadStateSyncOutcome(
            committed=False,
            reconcile_error=reconcile_error,
            reconcile_error_kind=reconcile_kind,
        )
    publication_error = _unpublished_bead_state_error(beads_root)
    remaining = _bead_remaining_files(beads_root) if publication_error else ()
    if reconcile_error is not None:
        remaining = remaining or _bead_remaining_files(beads_root)
        return BeadStateSyncOutcome(
            committed=False,
            publication_error=publication_error,
            beads_root=str(beads_root),
            remaining_files=tuple(remaining),
            reconcile_error=reconcile_error,
            reconcile_error_kind=reconcile_kind,
        )
    if publication_error is not None:
        return BeadStateSyncOutcome(
            committed=True,
            publication_error=publication_error,
            beads_root=str(beads_root),
            remaining_files=tuple(remaining or _bead_remaining_files(beads_root)),
            reconcile_error_kind="publication",
        )
    return BeadStateSyncOutcome(
        committed=True,
        beads_root=str(beads_root),
    )


def bead_sidecar_reconcile_diagnostic(outcome: BeadStateSyncOutcome) -> str | None:
    """Render the actionable diagnostic for an unreconciled bead sidecar."""

    if outcome.reconcile_error is None and outcome.publication_error is None:
        if not outcome.remaining_files and outcome.beads_root is None:
            return None
        if not outcome.remaining_files:
            return None
    lines: list[str] = []
    sidecar = outcome.beads_root or "(unknown bead sidecar)"
    lines.append(f"bead sidecar {sidecar} could not be reconciled")
    if outcome.remaining_files:
        listed = ", ".join(outcome.remaining_files[:20])
        if len(outcome.remaining_files) > 20:
            listed += f", ... ({len(outcome.remaining_files)} total)"
        lines.append(f"remaining files: {listed}")
    kind = outcome.reconcile_error_kind or (
        "publication" if outcome.publication_error else None
    )
    detail = outcome.reconcile_error or outcome.publication_error
    if kind:
        lines.append(f"reason ({kind}): {detail or 'see logs'}")
    elif detail:
        lines.append(f"reason: {detail}")
    lines.append(
        "Recovery: inspect `git status --short --branch` in the sidecar, "
        "resolve the lock/integrity/push failure, then re-run the commit; "
        "no primary stitch was retried and no sidecar file was deleted."
    )
    return "\n".join(lines)


def _bead_remaining_files(beads_root: Path) -> tuple[str, ...]:
    """List bead files still dirty in *beads_root* for a diagnostic."""

    try:
        from sase.llm_provider.commit_finalizer_git import git_changed_files

        return tuple(git_changed_files(str(beads_root)))
    except Exception:
        return ()


def _classify_bead_commit_failure(exc: BaseException) -> str:
    """Classify a bead auto-commit failure for the typed diagnostic."""

    integrity_errors: tuple[type[BaseException], ...] = ()
    try:
        from sase.bead._stream_integrity import BeadStreamIntegrityError

        integrity_errors = (BeadStreamIntegrityError,)
    except Exception:
        pass

    health_errors: tuple[type[BaseException], ...] = ()
    try:
        from sase.sdd._repository_transaction import SddRepositoryHealthError

        health_errors = (SddRepositoryHealthError,)
    except Exception:
        pass

    git_errors: tuple[type[BaseException], ...] = ()
    try:
        from sase.sdd._git_contention import SddGitCommandError

        git_errors = (SddGitCommandError,)
    except Exception:
        pass

    if integrity_errors and isinstance(exc, integrity_errors):
        return "integrity"
    if health_errors and isinstance(exc, health_errors):
        text = str(exc).lower()
        return "lock" if "lock" in text else "commit"
    if git_errors and isinstance(exc, git_errors):
        return "commit"
    text = str(exc).lower()
    if "lock" in text:
        return "lock"
    if "integrity" in text or "rewrite" in text or "shrink" in text:
        return "integrity"
    return "commit"


def _auto_commit_bead_state(
    project_dir: str, artifacts_dir: Path | None
) -> tuple[Path | None, str | None, str | None]:
    """Commit leftover bead state; return the store plus typed failure.

    Returns ``(beads_root, error, kind)`` where ``beads_root`` is the sidecar
    checkout that held the commit (or the dirty sidecar when the commit
    failed), ``error`` is the underlying commit, lock, or integrity failure,
    and ``kind`` is one of ``lock``, ``integrity``, or ``commit``. A clean
    store returns ``(None, None, None)``. The reason is returned, never
    swallowed, so the finalizer can report the sidecar path, remaining
    files, and recovery path.
    """

    beads_root: Path | None = None
    try:
        if not _separate_sdd_store_repo_may_exist(project_dir):
            return None, None, None

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
            return None, None, None
        repo_roots = (
            [store.repo_root_for_kind(role) for role in store.split_sidecar_roles()]
            if store.is_sidecar_storage
            else [store.repo_root]
        )
        if not any((root / ".git").exists() for root in repo_roots):
            return None, None, None
        beads_root = store.kind_root("beads")
        from sase.bead.sync import bead_state_is_clean

        if bead_state_is_clean(beads_root):
            return None, None, None
        committed = commit_sdd_store_files(
            store,
            "chore(beads): sync bead state",
            auto_commit_type="beads",
            paths=[beads_root],
            artifacts_dir=artifacts_dir,
        )
        if committed:
            return beads_root, None, None
        # No commit was created while bead state looked dirty: keep the
        # sidecar path and remaining files in the typed diagnostic.
        try:
            if bead_state_is_clean(beads_root):
                return None, None, None
        except Exception:
            pass
        remaining = _bead_remaining_files(beads_root)
        detail = (
            "bead auto-commit created no commit while "
            f"{len(remaining)} file(s) remain dirty: "
            + (", ".join(remaining[:10]) if remaining else "unknown files")
        )
        _logger.warning(
            "Failed to auto-commit separate SDD store during finalization: %s",
            detail,
        )
        return beads_root, detail, "commit"
    except Exception as exc:
        kind = _classify_bead_commit_failure(exc)
        detail = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
        _logger.warning(
            "Failed to auto-commit separate SDD store during finalization",
            exc_info=True,
        )
        return beads_root, detail, kind


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
