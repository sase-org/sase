"""Handler for memory initialization commands."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path
import subprocess
import sys

from sase.config.core import CHEZMOI_HOME, CONFIG_DIR, get_use_chezmoi
from sase.workflows.commit.precommit_hooks import run_precommit

from .init_memory.config import (
    project_config_path as _project_config_path,
    project_memory_name as _project_memory_name,
    sibling_entries_from_config as _sibling_entries_from_config,
)
from .init_memory.constants import COMMAND_LABEL, PROJECT_COMMIT_MESSAGE
from .init_memory.inventory import print_validation_errors as _print_validation_errors
from .init_memory.models import MemoryRootResult as _MemoryRootResult
from .init_memory.roots import initialize_memory_root as _initialize_memory_root


def _home_root_path(use_chezmoi: bool) -> Path:
    """Return the home-level root for the active config mode."""
    if use_chezmoi:
        return CHEZMOI_HOME
    return Path.home()


def _home_memory_path(use_chezmoi: bool) -> Path:
    """Return the home-level short memory target for the active config mode."""
    return _home_root_path(use_chezmoi) / "memory" / "short" / "sase.md"


def _global_config_path(use_chezmoi: bool) -> Path:
    """Return the global config source path for the active config mode."""
    if use_chezmoi:
        return CHEZMOI_HOME / "dot_config" / "sase" / "sase.yml"
    return CONFIG_DIR / "sase.yml"


def _print_config_errors(errors: Iterable[str]) -> None:
    for error in errors:
        print(error, file=sys.stderr)


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


def _deploy_to_project_repo(
    project_result: _MemoryRootResult, *, no_commit: bool
) -> int:
    if no_commit:
        return 0

    repo_check: subprocess.CompletedProcess[str]
    try:
        repo_check = subprocess.run(
            ["git", "-C", str(project_result.root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        print(f"{COMMAND_LABEL}: git not found on PATH", file=sys.stderr)
        return 1

    if repo_check.returncode != 0 or not repo_check.stdout.strip():
        detail = repo_check.stderr.strip()
        suffix = f": {detail}" if detail else ""
        print(
            f"{COMMAND_LABEL}: {project_result.root} is not a git repo{suffix}",
            file=sys.stderr,
        )
        return 1

    git_root = Path(repo_check.stdout.strip())
    if not run_precommit(str(git_root)):
        return 1

    memory_path = project_result.root / "memory" / "short" / "sase.md"
    stage_paths = _unique_paths((*project_result.written_paths, memory_path))
    for path in stage_paths:
        add = subprocess.run(
            ["git", "-C", str(git_root), "add", "--", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if add.returncode != 0:
            print(
                f"{COMMAND_LABEL}: git add failed for {path}: {add.stderr.strip()}",
                file=sys.stderr,
            )
            return 1

    staged = subprocess.run(
        ["git", "-C", str(git_root), "diff", "--cached", "--quiet"],
        capture_output=True,
        text=True,
        check=False,
    )
    if staged.returncode == 0:
        print(f"{COMMAND_LABEL}: nothing to commit in {git_root}")
        return 0
    if staged.returncode != 1:
        print(
            f"{COMMAND_LABEL}: staged diff check failed: {staged.stderr.strip()}",
            file=sys.stderr,
        )
        return 1

    print(f"Committing in {git_root}...")
    commit = subprocess.run(
        ["git", "-C", str(git_root), "commit", "-m", PROJECT_COMMIT_MESSAGE],
        capture_output=True,
        text=True,
        check=False,
    )
    if commit.returncode != 0:
        print(
            f"{COMMAND_LABEL}: commit failed: {commit.stderr.strip()}",
            file=sys.stderr,
        )
        return 1
    first_line = commit.stdout.strip().splitlines()[0] if commit.stdout.strip() else ""
    if first_line:
        print(f"  {first_line}")

    print("Pulling...")
    pull = subprocess.run(
        ["git", "-C", str(git_root), "pull", "--rebase"],
        capture_output=True,
        text=True,
        check=False,
    )
    if pull.returncode != 0:
        print(
            f"{COMMAND_LABEL}: pull failed: {pull.stderr.strip()}",
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
            f"{COMMAND_LABEL}: push failed: {push.stderr.strip()}",
            file=sys.stderr,
        )
        return 1
    tail = push.stderr.strip() or push.stdout.strip()
    if tail:
        print(f"  {tail.splitlines()[-1]}")

    return 0


def _deploy_to_chezmoi(written_paths: Iterable[Path]) -> int:
    paths = tuple(written_paths)
    if not paths:
        return 0

    git_root = CHEZMOI_HOME.parent
    repo_check = subprocess.run(
        ["git", "-C", str(git_root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if repo_check.returncode != 0:
        print(
            f"{COMMAND_LABEL}: {git_root} is not a git repo",
            file=sys.stderr,
        )
        return 1

    for path in paths:
        subprocess.run(
            ["git", "-C", str(git_root), "add", "--", str(path)],
            capture_output=True,
            check=False,
        )

    staged = subprocess.run(
        ["git", "-C", str(git_root), "diff", "--cached", "--quiet"],
        capture_output=True,
        check=False,
    )
    if staged.returncode != 0:
        commit = subprocess.run(
            [
                "git",
                "-C",
                str(git_root),
                "commit",
                "-m",
                "chore: initialize sase memory",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if commit.returncode != 0:
            print(
                f"{COMMAND_LABEL}: chezmoi commit failed: {commit.stderr.strip()}",
                file=sys.stderr,
            )
            return 1
        first_line = (
            commit.stdout.strip().splitlines()[0] if commit.stdout.strip() else ""
        )
        if first_line:
            print(f"  {first_line}")

    try:
        apply_result = subprocess.run(
            ["chezmoi", "apply", "--force"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        print(f"{COMMAND_LABEL}: chezmoi not found on PATH", file=sys.stderr)
        return 1

    if apply_result.returncode != 0:
        print(
            f"{COMMAND_LABEL}: chezmoi apply --force failed: "
            f"{apply_result.stderr.strip()}",
            file=sys.stderr,
        )
        return 1
    return 0


def handle_memory_init_command(args: argparse.Namespace) -> None:
    """Handle the ``sase memory init`` command."""
    use_chezmoi = get_use_chezmoi()
    no_commit: bool = getattr(args, "no_commit", False)
    project_config = _project_config_path()
    global_config = _global_config_path(use_chezmoi)

    project_entries, project_errors = _sibling_entries_from_config(
        project_config, label="project"
    )
    home_entries, home_errors = _sibling_entries_from_config(
        global_config, label="home"
    )
    config_errors = (*project_errors, *home_errors)
    if config_errors:
        _print_config_errors(config_errors)
        sys.exit(1)

    project_root = Path.cwd()
    project_result = _initialize_memory_root(
        project_root,
        project_entries,
        project_name=_project_memory_name(project_root),
    )
    home_result = _initialize_memory_root(_home_root_path(use_chezmoi), home_entries)
    results = (project_result, home_result)

    if any(result.unreferenced for result in results):
        _print_validation_errors(results)
        sys.exit(1)

    print(f"{COMMAND_LABEL}: initialized memory")
    print(f"  project memory target: {Path.cwd() / 'memory' / 'short' / 'sase.md'}")
    print(f"  home memory target: {_home_memory_path(use_chezmoi)}")
    print(f"  global config source: {global_config}")

    exit_code = 0
    project_exit_code = _deploy_to_project_repo(project_result, no_commit=no_commit)
    if project_exit_code != 0:
        exit_code = project_exit_code

    if use_chezmoi:
        chezmoi_exit_code = _deploy_to_chezmoi(home_result.written_paths)
        if chezmoi_exit_code != 0:
            exit_code = chezmoi_exit_code
    sys.exit(exit_code)


def handle_init_memory_command(args: argparse.Namespace) -> None:
    """Compatibility wrapper for ``sase init memory``."""
    handle_memory_init_command(args)
