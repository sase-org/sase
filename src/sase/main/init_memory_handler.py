"""Handler for memory initialization commands."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from sase.config.core import CHEZMOI_HOME, CONFIG_DIR, get_use_chezmoi
from sase.workflows.commit.precommit_hooks import run_precommit

from ._init_chezmoi_deploy import (
    ChezmoiDeployBehavior,
    defer_chezmoi_paths,
    deploy_to_chezmoi,
    skip_pull_push_without_upstream,
)
from .init_plan import InitAction, InitPlan
from .init_project_scope import is_project_directory
from .init_memory.config import (
    enable_project_memory as _enable_project_memory,
    primary_workspace_root_for_memory as _primary_workspace_root_for_memory,
    project_config_path as _project_config_path,
    project_memory_enabled as _project_memory_enabled,
    project_memory_name as _project_memory_name,
    linked_entries_from_config as _linked_entries_from_config,
)
from .init_memory.commit_message import build_fold_commit_message
from .init_memory.constants import (
    COMMAND_LABEL,
    MEMORY_FOLD_DEFAULT_PREFIX,
    PROJECT_COMMIT_MESSAGE,
)
from .init_memory.git_state import (
    DirtyPath,
    PreInitGitState,
    classify as _classify_git_state,
    dirty_path_label,
    parse_status_z,
)
from .init_memory.inventory import print_validation_errors as _print_validation_errors
from .init_memory.models import (
    MemoryRootPlan as _MemoryRootPlan,
    MemoryRootResult as _MemoryRootResult,
    LinkedRepoMemoryEntry as _LinkedRepoMemoryEntry,
)
from .init_memory.roots import initialize_memory_root as _initialize_memory_root
from .init_memory.roots import plan_memory_root as _plan_memory_root


@dataclass(frozen=True)
class _MemoryInitInputs:
    use_chezmoi: bool
    no_commit: bool
    is_project_dir: bool
    project_memory_enabled: bool
    global_config: Path
    project_root: Path
    home_root: Path
    project_name: str | None
    project_entries: tuple[_LinkedRepoMemoryEntry, ...]
    home_entries: tuple[_LinkedRepoMemoryEntry, ...]
    config_errors: tuple[str, ...]


def _home_root_path(use_chezmoi: bool) -> Path:
    """Return the home-level root for the active config mode."""
    if use_chezmoi:
        return CHEZMOI_HOME
    return Path.home()


def _home_memory_path(use_chezmoi: bool) -> Path:
    """Return the home-level short memory target for the active config mode."""
    return _sase_memory_path(_home_root_path(use_chezmoi))


def _sase_memory_path(root: Path) -> Path:
    """Return the generated SASE memory path for ``root``."""
    return root / "memory" / "sase.md"


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


def _stdin_is_tty() -> bool:
    return sys.stdin.isatty()


def _load_memory_inputs(args: argparse.Namespace) -> _MemoryInitInputs:
    use_chezmoi = get_use_chezmoi()
    project_root = Path.cwd()
    is_project_dir = is_project_directory(project_root)
    primary_root = _primary_workspace_root_for_memory(project_root)
    project_config = _project_config_path()
    global_config = _global_config_path(use_chezmoi)

    project_entries: tuple[_LinkedRepoMemoryEntry, ...]
    project_errors: tuple[str, ...]
    if is_project_dir:
        project_enabled, project_enabled_error = _project_memory_enabled(project_config)
        if project_enabled_error is not None:
            project_entries = ()
            project_errors = (project_enabled_error,)
        elif project_enabled:
            project_entries, project_errors = _linked_entries_from_config(
                project_config, label="project", primary_root=primary_root
            )
        else:
            project_entries = ()
            project_errors = ()
    else:
        project_enabled = False
        project_entries = ()
        project_errors = ()
    home_entries, home_errors = _linked_entries_from_config(
        global_config, label="home", primary_root=primary_root
    )
    config_errors = (*project_errors, *home_errors)
    project_name = (
        None
        if config_errors or not is_project_dir or not project_enabled
        else _project_memory_name(project_root)
    )
    return _MemoryInitInputs(
        use_chezmoi=use_chezmoi,
        no_commit=bool(getattr(args, "no_commit", False)),
        is_project_dir=is_project_dir,
        project_memory_enabled=project_enabled,
        global_config=global_config,
        project_root=project_root,
        home_root=_home_root_path(use_chezmoi),
        project_name=project_name,
        project_entries=project_entries,
        home_entries=home_entries,
        config_errors=config_errors,
    )


def _capture_pre_init_git_state(project_root: Path) -> PreInitGitState | None:
    try:
        repo_check = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None

    if repo_check.returncode != 0 or not repo_check.stdout.strip():
        return None

    git_root = Path(repo_check.stdout.strip())
    try:
        status = subprocess.run(
            [
                "git",
                "-C",
                str(git_root),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "-z",
            ],
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return None

    if status.returncode != 0:
        return None

    entries = parse_status_z(status.stdout)
    memory_dirty, other_dirty = _classify_git_state(entries, "memory")
    return PreInitGitState(
        git_root=git_root,
        memory_dirty=memory_dirty,
        other_dirty=other_dirty,
    )


def prepare_project_memory_opt_in(args: argparse.Namespace) -> bool:
    """Apply ``--enable-project-memory`` once, before init planning or writes."""
    if not getattr(args, "enable_project_memory", False):
        return True
    if getattr(args, "_project_memory_opt_in_prepared", False):
        return True
    if getattr(args, "check", False):
        print(
            f"{COMMAND_LABEL}: --enable-project-memory cannot be combined with --check",
            file=sys.stderr,
        )
        return False

    project_root = Path.cwd()
    if not is_project_directory(project_root):
        print(
            f"{COMMAND_LABEL}: --enable-project-memory requires a version-controlled project directory",
            file=sys.stderr,
        )
        return False

    no_commit = bool(getattr(args, "no_commit", False))
    git_state = None if no_commit else _capture_pre_init_git_state(project_root)
    config_path = _project_config_path()
    config_existed = config_path.exists()
    changed, error = _enable_project_memory(config_path)
    if error is not None:
        print(error, file=sys.stderr)
        return False

    args._project_memory_opt_in_prepared = True
    args._project_config_changed = changed
    args._project_config_git_state = git_state
    if changed:
        args._project_config_operation = "update" if config_existed else "create"
        print(
            f"{COMMAND_LABEL}: {args._project_config_operation}d {config_path} "
            "with memory.enabled: true"
        )
    return True


def _display_dirty_path(dirty_path: DirtyPath) -> str:
    return f"{dirty_path.path} ({dirty_path_label(dirty_path.status)})"


def _print_foreign_dirty_refusal(other_dirty: Iterable[DirtyPath]) -> None:
    print(
        f"{COMMAND_LABEL}: refusing to commit - uncommitted changes outside "
        "memory/ would be left behind:",
        file=sys.stderr,
    )
    for dirty_path in other_dirty:
        print(f"  - {_display_dirty_path(dirty_path)}", file=sys.stderr)
    print(
        "Commit or stash these changes and re-run `sase memory init`, or pass "
        "--no-commit to skip the git commit/push step. The regenerated memory "
        "files have been written but not committed.",
        file=sys.stderr,
    )


def _print_fold_prompt(memory_dirty: Iterable[DirtyPath]) -> None:
    body = Text()
    body.append(
        "These memory/ edits will be committed together with the\n"
        "regenerated AGENTS.md and provider shims:\n\n"
    )
    for dirty_path in memory_dirty:
        body.append(f"  - {_display_dirty_path(dirty_path)}\n")
    Console(stderr=True).print(
        Panel(body, title="Uncommitted memory changes", border_style="cyan")
    )
    default_tag = MEMORY_FOLD_DEFAULT_PREFIX.strip()
    print(
        f"A `{default_tag}` tag is added automatically if you omit one.",
        file=sys.stderr,
    )


def _resolve_fold_commit_message(
    memory_dirty: tuple[DirtyPath, ...],
    message: str | None,
) -> str | None:
    raw_subject = message
    if raw_subject is None:
        if not _stdin_is_tty():
            print(
                f"{COMMAND_LABEL}: memory/ has uncommitted changes to fold into "
                "the commit, but no commit message was provided and stdin is "
                'not a TTY. Re-run with --message "<subject>", or --no-commit '
                "to skip committing.",
                file=sys.stderr,
            )
            return None
        _print_fold_prompt(memory_dirty)
        print("Commit message > ", end="", flush=True, file=sys.stderr)
        try:
            raw_subject = input()
        except EOFError:
            print(
                f"{COMMAND_LABEL}: commit message entry reached EOF; aborting.",
                file=sys.stderr,
            )
            return None
        except KeyboardInterrupt:
            print("", file=sys.stderr)
            print(
                f"{COMMAND_LABEL}: commit message entry cancelled; aborting.",
                file=sys.stderr,
            )
            return None

    if raw_subject.strip() == "":
        print(f"{COMMAND_LABEL}: empty commit message; aborting.", file=sys.stderr)
        return None

    commit_message = build_fold_commit_message(raw_subject)
    subject = commit_message.splitlines()[0]
    print(f"{COMMAND_LABEL}: committing as: {subject}")
    return commit_message


def _deploy_to_project_repo(
    project_result: _MemoryRootResult,
    *,
    no_commit: bool,
    manage_memory: bool = True,
    git_state: PreInitGitState | None = None,
    message: str | None = None,
    owned_paths: Iterable[Path] = (),
) -> int:
    owned_paths = tuple(owned_paths)
    if no_commit:
        return 0

    if git_state is None:
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
        memory_dirty: tuple[DirtyPath, ...] = ()
        other_dirty: tuple[DirtyPath, ...] = ()
    else:
        git_root = git_state.git_root
        memory_dirty = git_state.memory_dirty
        other_dirty = git_state.other_dirty

    init_changed = bool(
        project_result.written_paths or project_result.deleted_paths or owned_paths
    )
    if other_dirty:
        if init_changed or memory_dirty:
            _print_foreign_dirty_refusal(other_dirty)
            return 1
        print(f"{COMMAND_LABEL}: nothing to commit in {git_root}")
        return 0

    if not init_changed and not memory_dirty:
        print(f"{COMMAND_LABEL}: nothing to commit in {git_root}")
        return 0

    fold_commit_message: str | None = None
    if memory_dirty:
        fold_commit_message = _resolve_fold_commit_message(memory_dirty, message)
        if fold_commit_message is None:
            return 1

    if not run_precommit(str(git_root)):
        return 1

    stage_paths = _unique_paths(
        (
            *project_result.written_paths,
            *project_result.deleted_paths,
            *owned_paths,
            *((_sase_memory_path(project_result.root),) if manage_memory else ()),
            *(git_root / dirty_path.path for dirty_path in memory_dirty),
        )
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

    if fold_commit_message is None:
        commit_message = apply_auto_commit_type_tag(PROJECT_COMMIT_MESSAGE, "memory")
    else:
        commit_message = fold_commit_message
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

    if skip_pull_push_without_upstream(git_root, COMMAND_LABEL):
        return 0

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
            apply_when_nothing_staged=True,
            commit_failed_label="chezmoi commit failed",
            print_committing=False,
            print_nothing_to_commit=False,
            print_applying=False,
            print_apply_done=False,
        ),
    )


def _memory_root_plans(inputs: _MemoryInitInputs) -> tuple[_MemoryRootPlan, ...]:
    chezmoi_home_roots = (inputs.home_root,) if inputs.use_chezmoi else ()
    root_plans: list[_MemoryRootPlan] = []
    if inputs.is_project_dir:
        root_plans.append(
            _plan_memory_root(
                inputs.project_root,
                inputs.project_entries,
                project_name=inputs.project_name,
                manage_memory=inputs.project_memory_enabled,
                enable_amd=True,
                derive_project_title=inputs.project_memory_enabled,
                chezmoi_home_roots=chezmoi_home_roots,
                include_project_agent_docs=True,
            )
        )
    home_plan = _plan_memory_root(
        inputs.home_root,
        inputs.home_entries,
        enable_amd=True,
        chezmoi_home_roots=chezmoi_home_roots,
    )
    root_plans.append(home_plan)
    return tuple(root_plans)


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
    if getattr(args, "_project_config_changed", False):
        config_action = InitAction(
            path=_project_config_path(),
            operation=getattr(args, "_project_config_operation", "update"),
            detail="enable project memory in sase.yml",
        )
        actions = (config_action, *actions)
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
    if not prepare_project_memory_opt_in(args):
        return 1

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

    git_state = getattr(args, "_project_config_git_state", None)
    if inputs.is_project_dir and not inputs.no_commit:
        if not getattr(args, "_project_memory_opt_in_prepared", False):
            git_state = _capture_pre_init_git_state(inputs.project_root)
        if git_state is not None and not inputs.project_memory_enabled:
            git_state = PreInitGitState(
                git_root=git_state.git_root,
                memory_dirty=(),
                other_dirty=(*git_state.other_dirty, *git_state.memory_dirty),
            )

    project_result: _MemoryRootResult | None = None
    if inputs.is_project_dir:
        project_result = _initialize_memory_root(
            inputs.project_root,
            inputs.project_entries,
            project_name=inputs.project_name,
            manage_memory=inputs.project_memory_enabled,
            enable_amd=True,
            derive_project_title=inputs.project_memory_enabled,
            chezmoi_home_roots=(inputs.home_root,) if inputs.use_chezmoi else (),
            include_project_agent_docs=True,
        )
    home_result = _initialize_memory_root(
        inputs.home_root,
        inputs.home_entries,
        enable_amd=True,
        chezmoi_home_roots=(inputs.home_root,) if inputs.use_chezmoi else (),
    )
    results = tuple(
        result for result in (project_result, home_result) if result is not None
    )

    if any(result.unreferenced for result in results):
        _print_validation_errors(results)
        return 1

    print(f"{COMMAND_LABEL}: initialized memory")
    if inputs.is_project_dir and inputs.project_memory_enabled:
        print(f"  project memory target: {_sase_memory_path(inputs.project_root)}")
    print(f"  home memory target: {_home_memory_path(inputs.use_chezmoi)}")
    print(f"  global config source: {inputs.global_config}")

    exit_code = 0
    if project_result is not None:
        project_exit_code = _deploy_to_project_repo(
            project_result,
            no_commit=inputs.no_commit,
            manage_memory=inputs.project_memory_enabled,
            git_state=git_state,
            message=getattr(args, "message", None),
            owned_paths=(
                (_project_config_path(),)
                if getattr(args, "_project_config_changed", False)
                else ()
            ),
        )
        if project_exit_code != 0:
            exit_code = project_exit_code

    if inputs.use_chezmoi:
        home_changed_paths = (*home_result.written_paths, *home_result.deleted_paths)
        if defer_chezmoi_paths(
            home_changed_paths,
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
