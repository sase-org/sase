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


@dataclass(frozen=True)
class ChezmoiDeployBehavior:
    """Behavior switches for one chezmoi deploy call."""

    command_label: str
    commit_message: str
    chezmoi_home: Path = CHEZMOI_HOME
    no_commit: bool = False
    no_push: bool = False
    no_apply: bool = False
    pull_push: bool = True
    apply_force: bool = False
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
    apply_force: bool = False

    def add(
        self,
        paths: Iterable[Path],
        *,
        apply_force: bool = False,
        chezmoi_home: Path = CHEZMOI_HOME,
    ) -> None:
        new_paths = list(paths)
        if not self.paths and new_paths:
            self.chezmoi_home = chezmoi_home
        self.paths.extend(new_paths)
        self.apply_force = self.apply_force or apply_force


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
        repo_check = subprocess.run(
            ["git", "-C", str(git_root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
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
        add = subprocess.run(
            ["git", "-C", str(git_root), "add", "--", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if add.returncode != 0:
            print(
                f"{behavior.command_label}: git add failed for {path}: "
                f"{add.stderr.strip()}",
                file=sys.stderr,
            )
            return 1

    staged = subprocess.run(
        ["git", "-C", str(git_root), "diff", "--cached", "--quiet"],
        capture_output=True,
        text=True,
        check=False,
    )
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
        commit = subprocess.run(
            ["git", "-C", str(git_root), "commit", "-m", behavior.commit_message],
            capture_output=True,
            text=True,
            check=False,
        )
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
        print("Pulling...")
        pull = subprocess.run(
            ["git", "-C", str(git_root), "pull", "--rebase"],
            capture_output=True,
            text=True,
            check=False,
        )
        if pull.returncode != 0:
            print(
                f"{behavior.command_label}: pull failed: {pull.stderr.strip()}",
                file=sys.stderr,
            )
            return 1
        if pull.stdout.strip():
            print(f"  {pull.stdout.strip().splitlines()[0]}")

        print("Pushing...")
        push = subprocess.run(
            ["git", "-C", str(git_root), "push"],
            capture_output=True,
            text=True,
            check=False,
        )
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

    apply_cmd = ["chezmoi", "apply"]
    if behavior.apply_force:
        apply_cmd.append("--force")

    if behavior.print_applying:
        print("Applying chezmoi...")
    try:
        apply = subprocess.run(
            apply_cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        print(f"{behavior.command_label}: chezmoi not found on PATH", file=sys.stderr)
        return 1 if behavior.chezmoi_missing_is_error else 0
    if apply.returncode != 0:
        apply_label = "chezmoi apply --force failed"
        if not behavior.apply_force:
            apply_label = "chezmoi apply failed"
        print(
            f"{behavior.command_label}: {apply_label}: {apply.stderr.strip()}",
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
    apply_force: bool = False,
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
        apply_force=apply_force,
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
            chezmoi_home=deferred.chezmoi_home,
            apply_force=deferred.apply_force,
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
]
