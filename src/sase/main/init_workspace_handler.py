"""Initialize project workspace ignore rules."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

from sase.workflows.commit.commit_hooks import run_before_commit_hook

from .init_plan import InitAction, InitPlan
from .init_project_scope import is_project_directory

LINKED_REPO_GITIGNORE_PATTERN = "/sase/repos/"
COMMAND_LABEL = "init workspace"


def _git_root(path: Path | None = None) -> Path | None:
    cwd = Path.cwd() if path is None else path
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return Path(result.stdout.strip()).resolve(strict=False)


def _updated_gitignore_content(existing: str) -> str:
    lines = {line.strip() for line in existing.splitlines()}
    if LINKED_REPO_GITIGNORE_PATTERN in lines:
        return existing
    if existing:
        prefix = existing if existing.endswith("\n") else f"{existing}\n"
        return f"{prefix}{LINKED_REPO_GITIGNORE_PATTERN}\n"
    return f"{LINKED_REPO_GITIGNORE_PATTERN}\n"


def _workspace_gitignore_plan() -> tuple[Path, str, str] | None:
    if not is_project_directory():
        return None
    root = _git_root()
    if root is None:
        return None
    gitignore = root / ".gitignore"
    try:
        existing = gitignore.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing = ""
    except OSError:
        return None
    updated = _updated_gitignore_content(existing)
    return gitignore, existing, updated


def plan_init_workspace(_args: argparse.Namespace) -> InitPlan:
    """Return a read-only plan for the root linked-repo ignore rule."""

    planned = _workspace_gitignore_plan()
    if planned is None:
        return InitPlan(
            command="workspace",
            label="Workspace",
            summary="workspace ignore rules are not applicable",
            actions=(),
        )
    gitignore, existing, updated = planned
    actions: tuple[InitAction, ...] = ()
    if updated != existing:
        actions = (
            InitAction(
                path=gitignore,
                operation="update" if gitignore.exists() else "create",
                detail="ignore host-scoped linked repository clones",
                new_content=updated,
            ),
        )
    return InitPlan(
        command="workspace",
        label="Workspace",
        summary=(
            "add /sase/repos/ to the project .gitignore"
            if actions
            else "workspace ignore rules are current"
        ),
        actions=actions,
    )


def _ensure_workspace_gitignore() -> Path | None:
    """Append the linked-repo clone rule and return the changed path."""

    planned = _workspace_gitignore_plan()
    if planned is None:
        return None
    gitignore, existing, updated = planned
    if updated == existing:
        return None
    gitignore.write_text(updated, encoding="utf-8")
    return gitignore


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _commit_workspace_gitignore(root: Path, gitignore: Path) -> int:
    """Commit only the init-managed root ``.gitignore`` path."""

    if not run_before_commit_hook(str(root)):
        return 1
    relative = gitignore.relative_to(root).as_posix()
    added = _run_git(root, "add", "--", relative)
    if added.returncode != 0:
        print(
            f"{COMMAND_LABEL}: git add failed: {added.stderr.strip()}",
            file=sys.stderr,
        )
        return 1
    staged = _run_git(root, "diff", "--cached", "--quiet", "--", relative)
    if staged.returncode == 0:
        return 0
    if staged.returncode != 1:
        print(
            f"{COMMAND_LABEL}: staged diff check failed: {staged.stderr.strip()}",
            file=sys.stderr,
        )
        return 1

    from sase.workflows.commit.runtime_tags import apply_auto_commit_type_tag

    message = apply_auto_commit_type_tag(
        "chore: initialize SASE workspace ignores", "init"
    )
    committed = _run_git(root, "commit", "-m", message, "--", relative)
    if committed.returncode != 0:
        print(
            f"{COMMAND_LABEL}: commit failed: {committed.stderr.strip()}",
            file=sys.stderr,
        )
        return 1

    from ._init_chezmoi_deploy import skip_pull_push_without_upstream

    if skip_pull_push_without_upstream(root, COMMAND_LABEL):
        return 0
    pulled = _run_git(root, "pull", "--rebase")
    if pulled.returncode != 0:
        print(
            f"{COMMAND_LABEL}: pull failed: {pulled.stderr.strip()}",
            file=sys.stderr,
        )
        return 1
    pushed = _run_git(root, "push")
    if pushed.returncode != 0:
        print(
            f"{COMMAND_LABEL}: push failed: {pushed.stderr.strip()}",
            file=sys.stderr,
        )
        return 1
    return 0


def run_init_workspace(args: argparse.Namespace) -> int:
    """Apply ``sase init workspace`` and return a process exit code."""

    if getattr(args, "check", False):
        from .init_onboarding import run_init_check
        from .init_registry import InitCommandSpec

        return run_init_check(
            args,
            specs=(
                InitCommandSpec(
                    name="workspace",
                    label="Workspace",
                    plan=plan_init_workspace,
                    run=run_init_workspace,
                ),
            ),
        )
    if getattr(args, "diff", False):
        from .init_preview import preview_console, render_plan_diff

        render_plan_diff(preview_console(sys.stdout), plan_init_workspace(args))

    root = _git_root()
    changed = _ensure_workspace_gitignore()
    if changed is None:
        return 0
    print(f"{COMMAND_LABEL}: updated {changed}")
    if getattr(args, "no_commit", False) or root is None:
        return 0
    return _commit_workspace_gitignore(root, changed)


def handle_init_workspace_command(args: argparse.Namespace) -> None:
    """Handle ``sase init workspace``."""

    sys.exit(run_init_workspace(args))


__all__ = [
    "LINKED_REPO_GITIGNORE_PATTERN",
    "handle_init_workspace_command",
    "plan_init_workspace",
    "run_init_workspace",
]
