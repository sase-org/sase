"""Shared chezmoi deploy helpers for ``sase init`` commands."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import fcntl
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from sase.config.core import CHEZMOI_HOME
from sase.git_lock_retry import run_with_git_lock_retry
from sase.memory.locks import LockTimeoutError, locked_file

_CHEZMOI_DEPLOY_LOCK_TIMEOUT_SECONDS = 120.0
_CHEZMOI_DEPLOY_LOCK_POLL_INTERVAL_SECONDS = 0.2


@dataclass(frozen=True)
class ChezmoiDeployBehavior:
    """Behavior switches for one chezmoi deploy call."""

    command_label: str
    commit_message: str
    auto_commit_type: str | None = None
    chezmoi_home: Path = CHEZMOI_HOME
    no_commit: bool = False
    no_push: bool = False
    no_apply: bool = False
    pull_push: bool = True
    apply_when_nothing_staged: bool = False
    git_failure_is_error: bool = True
    chezmoi_missing_is_error: bool = True
    commit_tags: dict[str, object] = field(default_factory=dict)
    include_runtime_commit_tags: bool = False
    git_missing_suffix: str = ""
    not_repo_suffix: str = ""
    commit_failed_label: str = "commit failed"
    print_committing: bool = True
    print_nothing_to_commit: bool = True
    print_applying: bool = True
    print_apply_done: bool = True


@dataclass
class _DeferredChezmoiDeploy:
    """Paths written while bare ``sase init`` defers chezmoi deployment."""

    paths: list[Path] = field(default_factory=list)
    chezmoi_home: Path = CHEZMOI_HOME
    commit_tags: dict[str, object] = field(default_factory=dict)
    include_runtime_commit_tags: bool = False

    def add(
        self,
        paths: Iterable[Path],
        *,
        chezmoi_home: Path = CHEZMOI_HOME,
        commit_tags: dict[str, object] | None = None,
        include_runtime_commit_tags: bool = False,
    ) -> None:
        new_paths = list(paths)
        if not self.paths and new_paths:
            self.chezmoi_home = chezmoi_home
        self.paths.extend(new_paths)
        if commit_tags:
            self.commit_tags.update(commit_tags)
        self.include_runtime_commit_tags = (
            self.include_runtime_commit_tags or include_runtime_commit_tags
        )


_DEFERRED_DEPLOY: ContextVar[_DeferredChezmoiDeploy | None] = ContextVar(
    "_DEFERRED_DEPLOY",
    default=None,
)
_HELD_DEPLOY_LOCK_ROOTS: ContextVar[tuple[Path, ...]] = ContextVar(
    "_HELD_DEPLOY_LOCK_ROOTS",
    default=(),
)


def _unique_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        key = path.resolve(strict=False)
        if key in seen:
            continue
        unique.append(path)
        seen.add(key)
    return tuple(unique)


def _git_pathspec(git_root: Path, path: Path) -> str:
    return (
        path.resolve(strict=False)
        .relative_to(git_root.resolve(strict=False))
        .as_posix()
    )


def _run_git(git_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result, _outcome = run_with_git_lock_retry(
        lambda: subprocess.run(
            ["git", "-C", str(git_root), *args],
            capture_output=True,
            text=True,
            check=False,
        ),
        cwd=git_root,
    )
    return result


def _missing_untracked_path(git_root: Path, path: Path) -> bool:
    if path.exists():
        return False
    try:
        pathspec = _git_pathspec(git_root, path)
    except ValueError:
        return False
    tracked = _run_git(git_root, "ls-files", "--error-unmatch", "--", pathspec)
    return tracked.returncode != 0


def _git_branch_has_upstream(git_root: Path) -> bool:
    """Return whether the current branch in ``git_root`` has an upstream."""
    upstream = _run_git(
        git_root,
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{u}",
    )
    return upstream.returncode == 0


def skip_pull_push_without_upstream(git_root: Path, command_label: str) -> bool:
    """Print and return true when pull/push should be skipped for no upstream."""
    if _git_branch_has_upstream(git_root):
        return False
    print(f"{command_label}: no upstream configured; skipping pull/push")
    return True


def deploy_to_chezmoi(
    written_paths: Iterable[Path],
    behavior: ChezmoiDeployBehavior,
) -> int:
    """Stage, optionally commit/push, and apply chezmoi source changes."""
    paths = _unique_paths(written_paths)
    if not paths:
        return 0
    if behavior.no_commit:
        return 0

    git_root = behavior.chezmoi_home.parent
    try:
        repo_check = _run_git(git_root, "rev-parse", "--show-toplevel")
    except FileNotFoundError:
        print(
            f"{behavior.command_label}: git not found on PATH"
            f"{behavior.git_missing_suffix}",
            file=sys.stderr,
        )
        return 1 if behavior.git_failure_is_error else 0

    if repo_check.returncode != 0:
        print(
            f"{behavior.command_label}: {git_root} is not a git repo"
            f"{behavior.not_repo_suffix}",
            file=sys.stderr,
        )
        return 1 if behavior.git_failure_is_error else 0

    try:
        with _chezmoi_deploy_lock(git_root, behavior.command_label):
            return _deploy_to_chezmoi_locked(paths, behavior, git_root)
    except LockTimeoutError as exc:
        print_chezmoi_deploy_lock_timeout(behavior.command_label, exc)
        return 1


def _deploy_to_chezmoi_locked(
    paths: tuple[Path, ...],
    behavior: ChezmoiDeployBehavior,
    git_root: Path,
) -> int:
    for path in paths:
        if _missing_untracked_path(git_root, path):
            continue
        add = _run_git(git_root, "add", "--", str(path))
        if add.returncode != 0:
            print(
                f"{behavior.command_label}: git add failed for {path}: "
                f"{add.stderr.strip()}",
                file=sys.stderr,
            )
            return 1

    staged = _run_git(git_root, "diff", "--cached", "--quiet")
    committed = False
    if staged.returncode == 0:
        if behavior.print_nothing_to_commit:
            print(f"\nNothing to commit in {git_root} (files identical to HEAD).")
        if not behavior.apply_when_nothing_staged:
            return 0
    elif staged.returncode != 1:
        print(
            f"{behavior.command_label}: staged diff check failed: "
            f"{staged.stderr.strip()}",
            file=sys.stderr,
        )
        return 1
    else:
        if behavior.print_committing:
            print(f"\nCommitting in {git_root}...")
        commit_message = behavior.commit_message
        if behavior.auto_commit_type is not None:
            from sase.workflows.commit.runtime_tags import apply_auto_commit_tags

            commit_message = apply_auto_commit_tags(
                commit_message,
                behavior.auto_commit_type,
                extra_tags=behavior.commit_tags,
                include_runtime=behavior.include_runtime_commit_tags,
            )
        elif behavior.commit_tags or behavior.include_runtime_commit_tags:
            from sase.workflows.commit.runtime_tags import apply_commit_tags

            commit_message = apply_commit_tags(
                commit_message,
                extra_tags=behavior.commit_tags,
                include_runtime=behavior.include_runtime_commit_tags,
            )
        commit = _run_git(git_root, "commit", "-m", commit_message)
        if commit.returncode != 0:
            print(
                f"{behavior.command_label}: {behavior.commit_failed_label}: "
                f"{commit.stderr.strip()}",
                file=sys.stderr,
            )
            return 1
        first_line = (
            commit.stdout.strip().splitlines()[0] if commit.stdout.strip() else ""
        )
        if first_line:
            print(f"  {first_line}")
        committed = True

    if behavior.no_push:
        return 0

    if behavior.pull_push and committed:
        if skip_pull_push_without_upstream(git_root, behavior.command_label):
            return 0

        print("Pulling...")
        pull = _run_git(git_root, "pull", "--rebase")
        if pull.returncode != 0:
            print(
                f"{behavior.command_label}: pull failed: {pull.stderr.strip()}",
                file=sys.stderr,
            )
            return 1
        if pull.stdout.strip():
            print(f"  {pull.stdout.strip().splitlines()[0]}")

        print("Pushing...")
        push = _run_git(git_root, "push")
        if push.returncode != 0:
            print(
                f"{behavior.command_label}: push failed: {push.stderr.strip()}",
                file=sys.stderr,
            )
            return 1
        tail = push.stderr.strip() or push.stdout.strip()
        if tail:
            print(f"  {tail.splitlines()[-1]}")

    if behavior.no_apply:
        return 0

    if behavior.print_applying:
        print("Applying chezmoi...")
    try:
        apply = subprocess.run(
            ["chezmoi", "apply", "--force"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        print(f"{behavior.command_label}: chezmoi not found on PATH", file=sys.stderr)
        return 1 if behavior.chezmoi_missing_is_error else 0
    if apply.returncode != 0:
        print(
            f"{behavior.command_label}: chezmoi apply --force failed: "
            f"{apply.stderr.strip()}",
            file=sys.stderr,
        )
        return 1
    if behavior.print_apply_done:
        print("  Done.")
    return 0


@contextmanager
def _chezmoi_deploy_lock(git_root: Path, command_label: str) -> Iterator[None]:
    resolved_root = git_root.resolve(strict=False)
    held_roots = _HELD_DEPLOY_LOCK_ROOTS.get()
    if resolved_root in held_roots:
        yield
        return

    lock_path = _chezmoi_deploy_lock_path(git_root)

    def announce_wait(path: Path) -> None:
        print(f"{command_label}: waiting for exclusive chezmoi deploy lock ({path})...")

    with locked_file(
        lock_path,
        fcntl.LOCK_EX,
        timeout=_CHEZMOI_DEPLOY_LOCK_TIMEOUT_SECONDS,
        poll_interval=_CHEZMOI_DEPLOY_LOCK_POLL_INTERVAL_SECONDS,
        on_wait=announce_wait,
    ):
        token = _HELD_DEPLOY_LOCK_ROOTS.set((*held_roots, resolved_root))
        try:
            yield
        finally:
            _HELD_DEPLOY_LOCK_ROOTS.reset(token)


@contextmanager
def chezmoi_deploy_lock(git_root: Path, command_label: str) -> Iterator[None]:
    """Hold the shared chezmoi deployment lock for a larger mutation span."""
    with _chezmoi_deploy_lock(git_root, command_label):
        yield


def print_chezmoi_deploy_lock_timeout(
    command_label: str,
    exc: LockTimeoutError,
) -> None:
    """Print the standard bounded-lock timeout message."""
    print(
        f"{command_label}: timed out waiting for exclusive chezmoi deploy lock "
        f"after {exc.timeout:g}s ({exc.lock_path})",
        file=sys.stderr,
    )


def _chezmoi_deploy_lock_path(git_root: Path) -> Path:
    lock_root = Path(os.environ.get("SASE_TMPDIR") or tempfile.gettempdir())
    digest = hashlib.sha256(
        str(git_root.resolve(strict=False)).encode("utf-8")
    ).hexdigest()[:16]
    return lock_root / "chezmoi-deploy-locks" / f"{digest}.lock"


@contextmanager
def defer_chezmoi_deploy(
    *,
    chezmoi_home: Path = CHEZMOI_HOME,
    command_label: str = "init",
) -> Iterator[_DeferredChezmoiDeploy]:
    """Collect handler chezmoi deploy requests for one later deploy."""
    with _chezmoi_deploy_lock(chezmoi_home.parent, command_label):
        deferred = _DeferredChezmoiDeploy(chezmoi_home=chezmoi_home)
        token = _DEFERRED_DEPLOY.set(deferred)
        try:
            yield deferred
        finally:
            _DEFERRED_DEPLOY.reset(token)


def defer_chezmoi_paths(
    written_paths: Iterable[Path],
    *,
    chezmoi_home: Path = CHEZMOI_HOME,
    commit_tags: dict[str, object] | None = None,
    include_runtime_commit_tags: bool = False,
) -> bool:
    """Record paths in the active deferral context.

    Returns ``False`` when no deferral context is active.
    """
    deferred = _DEFERRED_DEPLOY.get()
    if deferred is None:
        return False
    deferred.add(
        written_paths,
        chezmoi_home=chezmoi_home,
        commit_tags=commit_tags,
        include_runtime_commit_tags=include_runtime_commit_tags,
    )
    return True


def deploy_deferred_chezmoi(deferred: _DeferredChezmoiDeploy) -> int:
    """Run the consolidated bare ``sase init`` chezmoi deploy."""
    return deploy_to_chezmoi(
        deferred.paths,
        ChezmoiDeployBehavior(
            command_label="init",
            commit_message="chore: run sase init",
            auto_commit_type="init",
            chezmoi_home=deferred.chezmoi_home,
            commit_tags=deferred.commit_tags,
            include_runtime_commit_tags=deferred.include_runtime_commit_tags,
            apply_when_nothing_staged=True,
            print_nothing_to_commit=False,
        ),
    )


__all__ = [
    "ChezmoiDeployBehavior",
    "chezmoi_deploy_lock",
    "defer_chezmoi_deploy",
    "defer_chezmoi_paths",
    "deploy_deferred_chezmoi",
    "deploy_to_chezmoi",
    "print_chezmoi_deploy_lock_timeout",
    "skip_pull_push_without_upstream",
]
