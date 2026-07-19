"""Store discovery and persistence for plan-file bead work."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from sase.bead.cli_common import (
    find_beads_location,
    init_beads,
    resolve_beads_location,
)
from sase.bead.project import BEADS_DIRNAME
from sase.sdd.store import SDD_STORAGE_IN_TREE, SddStore

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _FallbackBeadsLocation:
    """Legacy location used only when store discovery has no project context."""

    root: Path
    beads_dirname: str
    store: None = None

    @property
    def beads_dir(self) -> Path:
        return self.root / self.beads_dirname


def resolve_plan_file_context(*, dry_run: bool) -> tuple[Any, SddStore, Path]:
    cwd = Path.cwd().expanduser().resolve()
    location: Any = resolve_beads_location(cwd, materialize=not dry_run)
    if location is None:
        if dry_run:
            location = _FallbackBeadsLocation(
                root=cwd,
                beads_dirname=BEADS_DIRNAME,
            )
        else:
            root, beads_dirname = find_beads_location(materialize=True)
            location = _FallbackBeadsLocation(
                root=root,
                beads_dirname=beads_dirname,
            )

    if not dry_run and not location.beads_dir.is_dir():
        init_beads(location.root, location.beads_dirname)

    store = location.store
    if store is None:
        store = SddStore(
            storage=SDD_STORAGE_IN_TREE,
            sdd_dir=location.root / "sdd",
            repo_root=location.root,
        )
    workspace_dir = location.root if store.is_in_tree else cwd
    return location, store, workspace_dir


def require_plan_store_health(store: SddStore) -> None:
    """Fail before archive or bead mutations when the plans repo is poisoned."""
    repo_root = store.repo_root
    if not (repo_root / ".git").exists():
        return
    from sase.sdd._git_contention import store_git_write_lock
    from sase.sdd._repository_transaction import (
        SddRepositoryHealthError,
        require_sdd_repository_health,
    )

    with store_git_write_lock(repo_root) as acquired:
        if not acquired:
            raise SddRepositoryHealthError(
                f"SDD repository {repo_root.resolve()} could not acquire its store "
                "write lock; no plan or bead files were changed"
            )
        require_sdd_repository_health(repo_root)


def require_epic_launch_store_health(cwd: Path) -> None:
    """Preflight a host-owned launch before detaching its canonical command."""
    location = resolve_beads_location(cwd, materialize=True)
    if location is not None and location.store is not None:
        require_plan_store_health(location.store)


def commit_plan_file(
    store: SddStore,
    *,
    workspace_dir: Path,
    plan_path: Path,
    no_push: bool,
    push_after_commit: bool | Literal["async"] | None,
    message: str,
) -> bool:
    effective_push = False if no_push else push_after_commit
    if store.is_in_tree and effective_push is not False:
        from sase.axe.run_agent_exec_plan_sdd import commit_sdd_files_for_exec_plan

        return commit_sdd_files_for_exec_plan(
            str(workspace_dir),
            plan_path.stem,
            plan_tier="epic",
            logger=_logger,
            subprocess_run=subprocess.run,
        )

    from sase.sdd.files import commit_sdd_store_files

    commit_store = store
    if store.is_in_tree:
        commit_store = replace(store, repo_root=workspace_dir)
    return commit_sdd_store_files(
        commit_store,
        message,
        paths=[plan_path],
        push_after_commit=effective_push,
    )


def push_store_after_launch(store: SddStore, *, no_push: bool) -> None:
    if no_push:
        return
    from sase.sdd._commit_store import push_sdd_store_after_commit

    try:
        push_sdd_store_after_commit(store, push_after_commit="async")
    except Exception:
        _logger.warning("Failed to start deferred SDD store push", exc_info=True)
