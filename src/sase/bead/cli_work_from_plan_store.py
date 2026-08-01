"""Store discovery and persistence for plan-file bead work."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
import fcntl
import hashlib
import json
import logging
import math
import os
import random
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

from sase.bead.cli_common import (
    find_beads_location,
    init_beads,
    resolve_beads_location,
)
from sase.bead.project import BEADS_DIRNAME
from sase.sdd.store import SDD_STORAGE_IN_TREE, SddStore

_logger = logging.getLogger(__name__)

EPIC_PLAN_LAUNCH_LOCK_FILENAME = "sase-epic-plan-launch.lock"
ENV_EPIC_PLAN_LAUNCH_LOCK_TIMEOUT = "SASE_EPIC_PLAN_LAUNCH_LOCK_TIMEOUT"
DEFAULT_EPIC_PLAN_LAUNCH_LOCK_TIMEOUT_SECONDS = 900.0
_EPIC_PLAN_LAUNCH_LOCK_INITIAL_BACKOFF_SECONDS = 0.005
_EPIC_PLAN_LAUNCH_LOCK_MAX_BACKOFF_SECONDS = 0.25
_EPIC_PLAN_LAUNCH_LOCK_BACKOFF_MULTIPLIER = 1.7


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
    if (
        not dry_run
        and location is not None
        and bool(getattr(location, "read_only", False))
    ):
        raise RuntimeError(
            f"Refusing bead work from a plain checkout: {location.beads_dir} "
            "was discovered through a checkout-local .sase/sdd-store.json "
            "record and is available for reads only."
        )
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

    # This preflight gates plan and bead worktree mutations, so it waits on the
    # same bound they do; a 10s bound would reject a burst that the mutation it
    # guards would have survived.
    with store_git_write_lock(
        repo_root,
        op="bead.plan_store_preflight",
        mutates_worktree=True,
    ) as acquired:
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


@contextmanager
def epic_plan_launch_lock(
    repo_root: Path,
    *,
    plan_file: str | Path | None = None,
    timeout: float | None = None,
) -> Iterator[None]:
    """Serialize complete approved-plan launches for one canonical store.

    This lock is deliberately distinct from ``store_git_write_lock``. Lock
    ordering is always launch lock first, then the short-lived store write lock
    used by nested commits. Keeping the launch lock outermost lets archive,
    bead, rollback, and terminal-push operations form one transaction without
    self-deadlocking. Acquisition is bounded so a wedged launch cannot leave
    every later launch blocked forever.
    """
    from sase.bead.cli_work_from_plan_types import PlanFileWorkError

    lock_path = _epic_plan_launch_lock_path(repo_root)
    timeout_seconds = (
        _epic_plan_launch_lock_timeout() if timeout is None else max(0.0, timeout)
    )
    waiting_plan = str(plan_file) if plan_file is not None else None
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        started = time.monotonic()
        acquired = _acquire_epic_plan_launch_lock(
            lock_file.fileno(),
            timeout=timeout_seconds,
        )
        if not acquired:
            holder = _read_lock_holder(lock_file)
            waited_seconds = time.monotonic() - started
            holder_detail = _format_epic_plan_launch_holder(holder)
            resume_command = (
                shlex.join(["sase", "bead", "work", waiting_plan])
                if waiting_plan is not None
                else None
            )
            resume_hint = (
                f" Resume with `{resume_command}` after the holder finishes."
                if resume_command is not None
                else " Retry the same `sase bead work` command after the holder finishes."
            )
            raise PlanFileWorkError(
                f"Timed out after {waited_seconds:.3f}s waiting for epic plan "
                f"launch lock {lock_path}; {holder_detail}.{resume_hint}",
                resume_command=resume_command,
            )

        _write_lock_holder(
            lock_file,
            {
                "pid": os.getpid(),
                "plan_file": waiting_plan or "<unknown>",
                "started_at": datetime.now(UTC).isoformat(),
            },
        )
        try:
            yield
        finally:
            try:
                _clear_lock_holder(lock_file)
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _epic_plan_launch_lock_timeout() -> float:
    raw = os.environ.get(ENV_EPIC_PLAN_LAUNCH_LOCK_TIMEOUT)
    if raw is None:
        return DEFAULT_EPIC_PLAN_LAUNCH_LOCK_TIMEOUT_SECONDS
    try:
        timeout = float(raw)
    except ValueError:
        return DEFAULT_EPIC_PLAN_LAUNCH_LOCK_TIMEOUT_SECONDS
    if not math.isfinite(timeout) or timeout <= 0:
        return DEFAULT_EPIC_PLAN_LAUNCH_LOCK_TIMEOUT_SECONDS
    return timeout


def _acquire_epic_plan_launch_lock(fd: int, *, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    backoff = _EPIC_PLAN_LAUNCH_LOCK_INITIAL_BACKOFF_SECONDS
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except InterruptedError:
            continue
        except BlockingIOError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            jittered_backoff = random.uniform(backoff * 0.75, backoff * 1.25)
            time.sleep(min(remaining, jittered_backoff))
            backoff = min(
                _EPIC_PLAN_LAUNCH_LOCK_MAX_BACKOFF_SECONDS,
                backoff * _EPIC_PLAN_LAUNCH_LOCK_BACKOFF_MULTIPLIER,
            )


def _read_lock_holder(lock_file: Any) -> dict[str, Any] | None:
    try:
        lock_file.seek(0)
        raw = lock_file.read().strip()
        value = json.loads(raw)
    except (OSError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _write_lock_holder(lock_file: Any, holder: dict[str, Any]) -> None:
    try:
        lock_file.seek(0)
        lock_file.truncate()
        json.dump(holder, lock_file, sort_keys=True)
        lock_file.flush()
    except OSError:
        _logger.debug("Failed to write epic plan launch lock holder", exc_info=True)


def _clear_lock_holder(lock_file: Any) -> None:
    try:
        lock_file.seek(0)
        lock_file.truncate()
        lock_file.flush()
    except OSError:
        _logger.debug("Failed to clear epic plan launch lock holder", exc_info=True)


def _format_epic_plan_launch_holder(holder: dict[str, Any] | None) -> str:
    if holder is None:
        return "the current holder did not record its identity"
    return (
        f"holder pid {holder.get('pid', 'unknown')} is launching "
        f"{holder.get('plan_file', '<unknown>')} "
        f"(started {holder.get('started_at', 'at an unknown time')})"
    )


def _epic_plan_launch_lock_path(repo_root: Path) -> Path:
    """Return an untracked lock path keyed by the canonical store root."""
    canonical_root = repo_root.expanduser().resolve(strict=False)
    try:
        from sase.sdd._git import run_sdd_git

        result = run_sdd_git(
            ["rev-parse", "--git-dir"],
            cwd=canonical_root,
            op="sdd.epic_plan_launch_lock.git_dir",
            check=False,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        result = None
    if result is not None and result.returncode == 0:
        raw_git_dir = result.stdout.strip()
        if raw_git_dir:
            git_dir = Path(raw_git_dir)
            if not git_dir.is_absolute():
                git_dir = canonical_root / git_dir
            return git_dir.resolve(strict=False) / EPIC_PLAN_LAUNCH_LOCK_FILENAME

    # Supported local stores need not be Git repositories. Keep their lock out
    # of durable plan/bead content while preserving one identity across
    # processes that resolve the same canonical root.
    identity = hashlib.sha256(os.fsencode(canonical_root)).hexdigest()
    from sase.core.paths import sase_subdir

    return sase_subdir("locks") / "epic-plan-launches" / f"{identity}.lock"


def commit_plan_file(
    store: SddStore,
    *,
    workspace_dir: Path,
    plan_path: Path,
    message: str,
    already_locked: bool = False,
) -> bool:
    from sase.sdd.files import commit_sdd_store_files

    commit_store = _plan_commit_store(store, workspace_dir=workspace_dir)
    return commit_sdd_store_files(
        commit_store,
        message,
        paths=[plan_path],
        push_after_commit=False,
        already_locked=already_locked,
    )


def write_and_commit_plan_file(
    store: SddStore,
    *,
    workspace_dir: Path,
    plan_path: Path,
    content: str,
    message: str,
) -> bool:
    """Replace and commit one approved plan inside a single store lock span."""
    from sase.sdd._git_contention import store_git_write_lock
    from sase.sdd._repository_transaction import SddRepositoryHealthError

    commit_store = _plan_commit_store(store, workspace_dir=workspace_dir)
    with store_git_write_lock(
        commit_store.repo_root,
        op="bead.approved_plan_update",
        mutates_worktree=True,
    ) as acquired:
        if not acquired:
            raise SddRepositoryHealthError(
                f"SDD repository {commit_store.repo_root.resolve()} could not "
                "acquire its store write lock; the approved plan was not changed"
            )
        plan_path.write_text(content, encoding="utf-8")
        return commit_plan_file(
            store,
            workspace_dir=workspace_dir,
            plan_path=plan_path,
            message=message,
            already_locked=True,
        )


def _plan_commit_store(store: SddStore, *, workspace_dir: Path) -> SddStore:
    if store.is_in_tree:
        return replace(store, repo_root=workspace_dir)
    return store


def push_store_after_launch(store: SddStore, *, no_push: bool) -> None:
    if no_push:
        return
    from sase.sdd._commit_store import push_sdd_store_after_commit

    try:
        push_sdd_store_after_commit(store, push_after_commit=True)
    except Exception:
        _logger.warning(
            "Failed to synchronize SDD store after approved epic launch",
            exc_info=True,
        )


def publish_epic_graph_before_launch(store: SddStore, *, no_push: bool) -> bool:
    """Make a committed epic graph visible to detached worker workspaces.

    Returns ``True`` when a remote publication completed and ``False`` when
    the authoritative store is shared by the launch context and needs no
    remote barrier. Unlike ordinary post-commit synchronization, publication
    failures are fatal because workers cannot safely claim unpublished beads.
    """
    if not _store_requires_remote_publication(store):
        return False
    if no_push:
        raise RuntimeError(
            "--no-push cannot launch workers from this detached bead store; "
            "the graph was committed locally and no agents were spawned. "
            "Resume without --no-push to publish it"
        )

    from sase.bead.sync import push_bead_work_launch

    outcome = push_bead_work_launch(store.kind_root("beads"))
    if outcome.pushed:
        return True
    if outcome.error is not None:
        raise RuntimeError(outcome.error)
    raise RuntimeError(
        "the detached bead store has no push remote; configure its remote "
        "before launching workers"
    )


def publish_epic_rollback(store: SddStore) -> bool:
    """Publish a compensating zero-spawn rollback when workers use clones."""
    if not _store_requires_remote_publication(store):
        return False

    from sase.bead.sync import push_bead_work_launch

    outcome = push_bead_work_launch(store.kind_root("beads"))
    if outcome.pushed:
        return True
    if outcome.error is not None:
        raise RuntimeError(outcome.error)
    raise RuntimeError("the detached bead store has no push remote")


def _store_requires_remote_publication(store: SddStore) -> bool:
    """Return whether fresh workers obtain this store from a remote clone."""
    return not store.is_in_tree and bool(store.remote_url)
