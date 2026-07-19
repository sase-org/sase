"""Shared chezmoi deploy helpers for ``sase init`` commands."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
import subprocess
import sys

from sase.config.core import CHEZMOI_HOME
from sase.git_lock_retry import run_with_git_lock_retry


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

    def add(
        self,
        paths: Iterable[Path],
        *,
        chezmoi_home: Path = CHEZMOI_HOME,
    ) -> None:
        new_paths = list(paths)
        if not self.paths and new_paths:
            self.chezmoi_home = chezmoi_home
        self.paths.extend(new_paths)


_DEFERRED_DEPLOY: ContextVar[_DeferredChezmoiDeploy | None] = ContextVar(
    "_DEFERRED_DEPLOY",
    default=None,
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
            from sase.workflows.commit.runtime_tags import apply_auto_commit_type_tag

            commit_message = apply_auto_commit_type_tag(
                commit_message,
                behavior.auto_commit_type,
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
def defer_chezmoi_deploy() -> Iterator[_DeferredChezmoiDeploy]:
    """Collect handler chezmoi deploy requests for one later deploy."""
    deferred = _DeferredChezmoiDeploy()
    token = _DEFERRED_DEPLOY.set(deferred)
    try:
        yield deferred
    finally:
        _DEFERRED_DEPLOY.reset(token)


def defer_chezmoi_paths(
    written_paths: Iterable[Path],
    *,
    chezmoi_home: Path = CHEZMOI_HOME,
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
            apply_when_nothing_staged=True,
            print_nothing_to_commit=False,
        ),
    )


__all__ = [
    "ChezmoiDeployBehavior",
    "defer_chezmoi_deploy",
    "defer_chezmoi_paths",
    "deploy_deferred_chezmoi",
    "deploy_to_chezmoi",
    "skip_pull_push_without_upstream",
]
