"""Handler for memory initialization commands."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys

from sase.config.core import CHEZMOI_HOME, CONFIG_DIR, get_use_chezmoi
from sase.workflows.commit.precommit_hooks import run_precommit

from ._init_chezmoi_deploy import (
    ChezmoiDeployBehavior,
    defer_chezmoi_paths,
    deploy_to_chezmoi,
)
from .init_plan import InitAction, InitPlan
from .init_memory.config import (
    primary_workspace_root_for_memory as _primary_workspace_root_for_memory,
    project_config_path as _project_config_path,
    project_memory_name as _project_memory_name,
    sibling_entries_from_config as _sibling_entries_from_config,
)
from .init_memory.constants import COMMAND_LABEL, PROJECT_COMMIT_MESSAGE
from .init_memory.inventory import print_validation_errors as _print_validation_errors
from .init_memory.models import (
    MemoryRootPlan as _MemoryRootPlan,
    MemoryRootResult as _MemoryRootResult,
    SiblingMemoryEntry as _SiblingMemoryEntry,
)
from .init_memory.roots import initialize_memory_root as _initialize_memory_root
from .init_memory.roots import plan_memory_root as _plan_memory_root


@dataclass(frozen=True)
class _MemoryInitInputs:
    use_chezmoi: bool
    no_commit: bool
    global_config: Path
    project_root: Path
    home_root: Path
    project_name: str | None
    project_entries: tuple[_SiblingMemoryEntry, ...]
    home_entries: tuple[_SiblingMemoryEntry, ...]
    config_errors: tuple[str, ...]


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


def _load_memory_inputs(args: argparse.Namespace) -> _MemoryInitInputs:
    use_chezmoi = get_use_chezmoi()
    project_root = Path.cwd()
    primary_root = _primary_workspace_root_for_memory(project_root)
    project_config = _project_config_path()
    global_config = _global_config_path(use_chezmoi)

    project_entries, project_errors = _sibling_entries_from_config(
        project_config, label="project", primary_root=primary_root
    )
    home_entries, home_errors = _sibling_entries_from_config(
        global_config, label="home", primary_root=primary_root
    )
    config_errors = (*project_errors, *home_errors)
    project_name = None if config_errors else _project_memory_name(project_root)
    return _MemoryInitInputs(
        use_chezmoi=use_chezmoi,
        no_commit=bool(getattr(args, "no_commit", False)),
        global_config=global_config,
        project_root=project_root,
        home_root=_home_root_path(use_chezmoi),
        project_name=project_name,
        project_entries=project_entries,
        home_entries=home_entries,
        config_errors=config_errors,
    )


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
    stage_paths = _unique_paths(
        (*project_result.written_paths, *project_result.deleted_paths, memory_path)
    )
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
    from sase.workflows.commit.runtime_tags import apply_auto_commit_type_tag

    commit_message = apply_auto_commit_type_tag(PROJECT_COMMIT_MESSAGE, "memory")
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
    return deploy_to_chezmoi(
        written_paths,
        ChezmoiDeployBehavior(
            command_label=COMMAND_LABEL,
            commit_message="chore: initialize sase memory",
            auto_commit_type="memory",
            chezmoi_home=CHEZMOI_HOME,
            pull_push=False,
            apply_force=True,
            apply_when_nothing_staged=True,
            commit_failed_label="chezmoi commit failed",
            print_committing=False,
            print_nothing_to_commit=False,
            print_applying=False,
            print_apply_done=False,
        ),
    )


def _memory_root_plans(inputs: _MemoryInitInputs) -> tuple[_MemoryRootPlan, ...]:
    home_equivalent_roots = (inputs.home_root,)
    chezmoi_home_roots = (inputs.home_root,) if inputs.use_chezmoi else ()
    project_plan = _plan_memory_root(
        inputs.project_root,
        inputs.project_entries,
        project_name=inputs.project_name,
        enable_amd=True,
        home_equivalent_roots=home_equivalent_roots,
        chezmoi_home_roots=chezmoi_home_roots,
    )
    home_plan = _plan_memory_root(
        inputs.home_root,
        inputs.home_entries,
        home_equivalent_roots=home_equivalent_roots,
        chezmoi_home_roots=chezmoi_home_roots,
    )
    return (project_plan, home_plan)


def _format_unreferenced_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root.resolve(strict=False)))
    except ValueError:
        return str(path)


def _memory_plan_blockers(
    root_plans: Iterable[_MemoryRootPlan],
) -> tuple[str, ...]:
    blockers: list[str] = []
    for root_plan in root_plans:
        blockers.extend(root_plan.blockers)
        for path in root_plan.unreferenced:
            display = _format_unreferenced_path(root_plan.root, path)
            blockers.append(f"{root_plan.root}: unreferenced memory file {display}")
    return tuple(blockers)


def _memory_root_plan_blockers(
    root_plans: Iterable[_MemoryRootPlan],
) -> tuple[str, ...]:
    return tuple(blocker for root_plan in root_plans for blocker in root_plan.blockers)


def _summarize_memory_actions(actions: tuple[InitAction, ...]) -> str:
    if not actions:
        return "memory files are current"
    operations = {action.operation for action in actions}
    if len(actions) == 1:
        action = actions[0]
        return f"{action.operation} {action.detail}"
    if operations == {"create"}:
        verb = "create"
    elif operations == {"update"}:
        verb = "update"
    elif operations == {"overwrite"}:
        verb = "overwrite"
    else:
        verb = "refresh"
    return f"{verb} {len(actions)} memory files and provider shims"


def plan_init_memory(args: argparse.Namespace) -> InitPlan:
    """Return a read-only plan for generated memory files."""
    inputs = _load_memory_inputs(args)
    if inputs.config_errors:
        return InitPlan(
            command="memory",
            label="Memory",
            summary="cannot generate memory until configuration is fixed",
            actions=(),
            blockers=inputs.config_errors,
        )

    root_plans = _memory_root_plans(inputs)
    actions = tuple(
        InitAction(
            path=change.path,
            operation=change.operation,
            detail=change.detail,
        )
        for root_plan in root_plans
        for change in root_plan.changes
    )
    blockers = _memory_plan_blockers(root_plans)
    return InitPlan(
        command="memory",
        label="Memory",
        summary=_summarize_memory_actions(actions),
        actions=actions,
        blockers=blockers,
    )


def run_init_memory(args: argparse.Namespace) -> int:
    """Apply ``sase memory init`` and return a process exit code."""
    if getattr(args, "check", False):
        from .init_onboarding import run_init_check
        from .init_registry import InitCommandSpec

        return run_init_check(
            args,
            specs=(
                InitCommandSpec(
                    name="memory",
                    label="Memory",
                    plan=plan_init_memory,
                    run=run_init_memory,
                ),
            ),
        )

    inputs = _load_memory_inputs(args)
    if inputs.config_errors:
        _print_config_errors(inputs.config_errors)
        return 1

    root_plans = _memory_root_plans(inputs)
    root_plan_blockers = _memory_root_plan_blockers(root_plans)
    if root_plan_blockers:
        _print_config_errors(root_plan_blockers)
        return 1

    project_result = _initialize_memory_root(
        inputs.project_root,
        inputs.project_entries,
        project_name=inputs.project_name,
        enable_amd=True,
        home_equivalent_roots=(inputs.home_root,),
        chezmoi_home_roots=(inputs.home_root,) if inputs.use_chezmoi else (),
    )
    home_result = _initialize_memory_root(
        inputs.home_root,
        inputs.home_entries,
        home_equivalent_roots=(inputs.home_root,),
        chezmoi_home_roots=(inputs.home_root,) if inputs.use_chezmoi else (),
    )
    results = (project_result, home_result)

    if any(result.unreferenced for result in results):
        _print_validation_errors(results)
        return 1

    print(f"{COMMAND_LABEL}: initialized memory")
    print(f"  project memory target: {Path.cwd() / 'memory' / 'short' / 'sase.md'}")
    print(f"  home memory target: {_home_memory_path(inputs.use_chezmoi)}")
    print(f"  global config source: {inputs.global_config}")

    exit_code = 0
    project_exit_code = _deploy_to_project_repo(
        project_result,
        no_commit=inputs.no_commit,
    )
    if project_exit_code != 0:
        exit_code = project_exit_code

    if inputs.use_chezmoi:
        home_changed_paths = (*home_result.written_paths, *home_result.deleted_paths)
        if defer_chezmoi_paths(
            home_changed_paths,
            apply_force=True,
            chezmoi_home=CHEZMOI_HOME,
        ):
            chezmoi_exit_code = 0
        else:
            chezmoi_exit_code = _deploy_to_chezmoi(home_changed_paths)
        if chezmoi_exit_code != 0:
            exit_code = chezmoi_exit_code
    return exit_code


def handle_memory_init_command(args: argparse.Namespace) -> None:
    """Handle the ``sase memory init`` command."""
    sys.exit(run_init_memory(args))


def handle_init_memory_command(args: argparse.Namespace) -> None:
    """Compatibility wrapper for ``sase init memory``."""
    handle_memory_init_command(args)
