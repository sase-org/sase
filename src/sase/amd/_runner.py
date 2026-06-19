"""Command application for ``sase amd init``."""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from pathlib import Path
import subprocess
import sys

from sase.workflows.commit.precommit_hooks import run_precommit
from sase.workflows.commit.runtime_tags import apply_auto_commit_type_tag

from ._planner import build_amd_init_plan, plan_amd_init_for_check
from ._shared import COMMAND_LABEL, apply_planned_delete
from .constants import AMD_COMMIT_MESSAGE


def _print_blockers(blockers: tuple[str, ...]) -> None:
    for blocker in blockers:
        print(f"{COMMAND_LABEL}: {blocker}", file=sys.stderr)


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


def _git_root_for_path(path: Path) -> tuple[Path | None, str | None]:
    """Return the owning git toplevel for *path* and any hard error."""
    try:
        result = subprocess.run(
            ["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None, "git not found on PATH"
    if result.returncode != 0 or not result.stdout.strip():
        return None, None
    return Path(result.stdout.strip()), None


def _commit_amd_repo(git_root: Path, paths: Sequence[Path]) -> int:
    """Run precommit, stage only *paths*, and commit them in *git_root*."""
    if not run_precommit(str(git_root)):
        return 1

    for path in paths:
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
    commit_message = apply_auto_commit_type_tag(AMD_COMMIT_MESSAGE, "amd")
    commit = subprocess.run(
        ["git", "-C", str(git_root), "commit", "-m", commit_message],
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
    return 0


def _commit_amd_changes(paths: Sequence[Path]) -> int:
    """Group AMD-changed *paths* by owning git repo and commit each locally."""
    groups: dict[Path, list[Path]] = {}
    ungrouped: list[Path] = []
    for path in _unique_paths(paths):
        git_root, error = _git_root_for_path(path)
        if error is not None:
            print(f"{COMMAND_LABEL}: {error}", file=sys.stderr)
            return 1
        if git_root is None:
            ungrouped.append(path)
            continue
        groups.setdefault(git_root, []).append(path)

    exit_code = 0
    for git_root in sorted(groups, key=str):
        repo_exit = _commit_amd_repo(git_root, groups[git_root])
        if repo_exit != 0:
            exit_code = repo_exit

    for path in ungrouped:
        print(
            f"{COMMAND_LABEL}: {path} is not inside a git repo",
            file=sys.stderr,
        )
        exit_code = 1
    return exit_code


def run_amd_init(args: argparse.Namespace) -> int:
    """Apply ``sase amd init`` and return a process exit code."""
    if getattr(args, "check", False):
        from sase.main.init_onboarding import run_init_check
        from sase.main.init_registry import InitCommandSpec

        return run_init_check(
            args,
            specs=(
                InitCommandSpec(
                    name="amd",
                    label="AMD",
                    plan=plan_amd_init_for_check,
                    run=run_amd_init,
                ),
            ),
        )

    onboarding = bool(getattr(args, "onboarding", False))
    built = build_amd_init_plan(explicit=not onboarding, onboarding=onboarding)
    if built.plan.blockers:
        _print_blockers(built.plan.blockers)
        return 1

    written: list[Path] = []
    deleted: list[Path] = []
    for write in built.writes:
        write.path.parent.mkdir(parents=True, exist_ok=True)
        write.path.write_text(write.content, encoding="utf-8")
        written.append(write.path)
    for delete in built.deletes:
        did_delete, delete_error = apply_planned_delete(delete)
        if delete_error is not None:
            print(f"{COMMAND_LABEL}: {delete_error}", file=sys.stderr)
            return 1
        if did_delete:
            deleted.append(delete.path)

    if written or deleted:
        print(f"{COMMAND_LABEL}: initialized agent markdown documents")
        for path in written:
            print(f"  {path}")
        for path in deleted:
            print(f"  deleted {path}")
    else:
        print(f"{COMMAND_LABEL}: agent markdown documents are current")

    if bool(getattr(args, "no_commit", False)):
        return 0

    changed_paths = (*written, *deleted)
    if not changed_paths:
        return 0
    return _commit_amd_changes(changed_paths)
