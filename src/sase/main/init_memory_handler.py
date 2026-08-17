"""Handler for memory initialization commands."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
from typing import TextIO

from sase.config.core import CHEZMOI_HOME, CONFIG_DIR, get_use_chezmoi
from sase.workflows.commit.command_hooks import run_before_commit_hook

from ._init_chezmoi_deploy import (
    ChezmoiDeployBehavior,
    defer_chezmoi_paths,
    deploy_to_chezmoi,
)
from .init_plan import InitAction, InitPlan
from .init_project_scope import is_project_directory
from .init_memory.config import (
    primary_workspace_root_for_memory as _primary_workspace_root_for_memory,
    project_config_path as _project_config_path,
    project_memory_name as _project_memory_name,
    linked_entries_from_config as _linked_entries_from_config,
    project_config_read_path as _project_config_read_path,
)
from .init_memory.glossary import (
    GeneratedGlossaryMemory as _GeneratedGlossaryMemory,
    load_project_glossary_memory as _load_project_glossary_memory,
)
from sase.memory.paths import memory_write_root
from sase.project_management import enable_sase_management, project_management_status
from .init_memory.constants import COMMAND_LABEL
from .init_memory.git_state import PreInitGitState
from .init_memory.inventory import print_validation_errors as _print_validation_errors
from .init_memory.models import (
    MemoryRootPlan as _MemoryRootPlan,
    MemoryRootResult as _MemoryRootResult,
    LinkedRepoMemoryEntry as _LinkedRepoMemoryEntry,
)
from .init_memory.roots import initialize_memory_root as _initialize_memory_root
from .init_memory.roots import plan_memory_root as _plan_memory_root
from .init_memory.project_deploy import (
    capture_pre_init_git_state as _capture_git_state,
    deploy_to_project_repo as _deploy_project_repo,
)
from .init_memory.staleness import (
    workspace_pinned_sase_mismatch_warning as _workspace_pinned_sase_mismatch_warning,
)


@dataclass(frozen=True)
class _MemoryInitInputs:
    use_chezmoi: bool
    no_commit: bool
    is_project_dir: bool
    is_sase_managed: bool
    global_config: Path
    project_root: Path
    home_root: Path
    project_name: str | None
    project_entries: tuple[_LinkedRepoMemoryEntry, ...]
    project_glossary: _GeneratedGlossaryMemory | None
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
    return memory_write_root(root) / "sase.md"


def _global_config_path(use_chezmoi: bool) -> Path:
    """Return the global config source path for the active config mode."""
    if use_chezmoi:
        return CHEZMOI_HOME / "dot_config" / "sase" / "sase.yml"
    return CONFIG_DIR / "sase.yml"


def _print_config_errors(errors: Iterable[str]) -> None:
    for error in errors:
        print(error, file=sys.stderr)


def _stdin_is_tty() -> bool:
    return sys.stdin.isatty()


def _load_memory_inputs(args: argparse.Namespace) -> _MemoryInitInputs:
    use_chezmoi = get_use_chezmoi()
    project_root = Path.cwd()
    is_project_dir = is_project_directory(project_root)
    primary_root = _primary_workspace_root_for_memory(project_root)
    project_config = _project_config_read_path()
    global_config = _global_config_path(use_chezmoi)

    project_entries: tuple[_LinkedRepoMemoryEntry, ...]
    project_errors: tuple[str, ...]
    project_glossary: _GeneratedGlossaryMemory | None = None
    glossary_errors: tuple[str, ...] = ()
    project_name: str | None = None
    if is_project_dir:
        management = project_management_status(project_config)
        project_managed = management.is_sase_managed
        if management.error is not None:
            project_entries = ()
            project_errors = (management.error,)
        elif project_managed:
            project_name = _project_memory_name(project_root)
            project_entries, project_errors = _linked_entries_from_config(
                project_config,
                label="project",
                primary_root=primary_root,
                project_name=project_name,
            )
            project_glossary, glossary_errors = _load_project_glossary_memory(
                project_config
            )
        else:
            project_entries = ()
            project_errors = ()
    else:
        project_managed = False
        project_entries = ()
        project_errors = ()
    home_entries, home_errors = _linked_entries_from_config(
        global_config, label="home", primary_root=primary_root
    )
    config_errors = (*project_errors, *glossary_errors, *home_errors)
    if config_errors or not is_project_dir or not project_managed:
        project_name = None
        project_glossary = None
    return _MemoryInitInputs(
        use_chezmoi=use_chezmoi,
        no_commit=bool(getattr(args, "no_commit", False)),
        is_project_dir=is_project_dir,
        is_sase_managed=project_managed,
        global_config=global_config,
        project_root=project_root,
        home_root=_home_root_path(use_chezmoi),
        project_name=project_name,
        project_entries=project_entries,
        project_glossary=project_glossary,
        home_entries=home_entries,
        config_errors=config_errors,
    )


def _capture_pre_init_git_state(project_root: Path) -> PreInitGitState | None:
    return _capture_git_state(project_root)


def prepare_project_memory_opt_in(args: argparse.Namespace) -> bool:
    """Apply the compatibility opt-in flag before init planning or writes."""
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
    config_source_path = _project_config_read_path()
    config_existed = config_path.exists()
    migrated_config = config_source_path != config_path and config_source_path.is_file()
    if migrated_config:
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_bytes(config_source_path.read_bytes())
        except OSError as exc:
            print(
                f"{COMMAND_LABEL}: failed to migrate {config_source_path} "
                f"to {config_path}: {exc}",
                file=sys.stderr,
            )
            return False
    update = enable_sase_management(config_path)
    if update.error is not None:
        if migrated_config:
            config_path.unlink(missing_ok=True)
        print(update.error, file=sys.stderr)
        return False
    if migrated_config:
        try:
            config_source_path.unlink()
        except OSError as exc:
            config_path.unlink(missing_ok=True)
            print(
                f"{COMMAND_LABEL}: failed to remove migrated config "
                f"{config_source_path}: {exc}",
                file=sys.stderr,
            )
            return False

    args._project_memory_opt_in_prepared = True
    args._project_config_changed = update.changed or migrated_config
    args._project_config_git_state = git_state
    args._project_config_migrated_from = config_source_path if migrated_config else None
    if update.changed or migrated_config:
        args._project_config_operation = "update" if config_existed else "create"
        print(
            f"{COMMAND_LABEL}: {args._project_config_operation}d {config_path} "
            "with is_sase_managed: true"
        )
    return True


def _deploy_to_project_repo(
    project_result: _MemoryRootResult,
    *,
    no_commit: bool,
    manage_memory: bool = True,
    git_state: PreInitGitState | None = None,
    message: str | None = None,
    owned_paths: Iterable[Path] = (),
    input_func: Callable[[str], str] | None = None,
    stdin: TextIO | None = None,
) -> int:
    stdin_is_tty = _stdin_is_tty if stdin is None else stdin.isatty
    return _deploy_project_repo(
        project_result,
        no_commit=no_commit,
        run_before_commit_hook=run_before_commit_hook,
        stdin_is_tty=stdin_is_tty,
        input_func=input_func,
        manage_memory=manage_memory,
        git_state=git_state,
        message=message,
        owned_paths=owned_paths,
    )


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
                generated_glossary=inputs.project_glossary,
                manage_memory=inputs.is_sase_managed,
                enable_amd=True,
                derive_project_title=inputs.is_sase_managed,
                chezmoi_home_roots=chezmoi_home_roots,
                include_project_agent_docs=True,
                include_project_memory=True,
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


def _memory_plan_warnings(inputs: _MemoryInitInputs) -> tuple[str, ...]:
    if not inputs.is_project_dir:
        return ()
    warning = _workspace_pinned_sase_mismatch_warning(inputs.project_root)
    return () if warning is None else (warning,)


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
    warnings = _memory_plan_warnings(inputs)
    if inputs.config_errors:
        return InitPlan(
            command="memory",
            label="Memory",
            summary="cannot generate memory until configuration is fixed",
            actions=(),
            warnings=warnings,
            blockers=inputs.config_errors,
        )

    root_plans = _memory_root_plans(inputs)
    actions = tuple(
        InitAction(
            path=change.path,
            operation=change.operation,
            detail=change.detail,
            new_content=change.new_content,
        )
        for root_plan in root_plans
        for change in root_plan.changes
    )
    if getattr(args, "_project_config_changed", False):
        config_action = InitAction(
            path=_project_config_path(),
            operation=getattr(args, "_project_config_operation", "update"),
            detail="mark repository as SASE-managed in sase.yml",
        )
        actions = (config_action, *actions)
    blockers = _memory_plan_blockers(root_plans)
    return InitPlan(
        command="memory",
        label="Memory",
        summary=_summarize_memory_actions(actions),
        actions=actions,
        warnings=warnings,
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
    for warning in _memory_plan_warnings(inputs):
        print(f"{COMMAND_LABEL}: warning: {warning}", file=sys.stderr)
    if inputs.config_errors:
        _print_config_errors(inputs.config_errors)
        return 1

    if getattr(args, "diff", False):
        from .init_preview import preview_console, render_plan_diff

        render_plan_diff(preview_console(sys.stdout), plan_init_memory(args))

    root_plans = _memory_root_plans(inputs)
    root_plan_blockers = _memory_root_plan_blockers(root_plans)
    if root_plan_blockers:
        _print_config_errors(root_plan_blockers)
        return 1

    git_state = getattr(args, "_project_config_git_state", None)
    if inputs.is_project_dir and not inputs.no_commit:
        if not getattr(args, "_project_memory_opt_in_prepared", False):
            git_state = _capture_pre_init_git_state(inputs.project_root)
        if git_state is not None and not inputs.is_sase_managed:
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
            generated_glossary=inputs.project_glossary,
            manage_memory=inputs.is_sase_managed,
            enable_amd=True,
            derive_project_title=inputs.is_sase_managed,
            chezmoi_home_roots=(inputs.home_root,) if inputs.use_chezmoi else (),
            include_project_agent_docs=True,
            include_project_memory=True,
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
    if inputs.is_project_dir and inputs.is_sase_managed:
        print(f"  project memory target: {_sase_memory_path(inputs.project_root)}")
    print(f"  home memory target: {_home_memory_path(inputs.use_chezmoi)}")
    print(f"  global config source: {inputs.global_config}")

    exit_code = 0
    if project_result is not None:
        project_exit_code = _deploy_to_project_repo(
            project_result,
            no_commit=inputs.no_commit,
            manage_memory=inputs.is_sase_managed,
            git_state=git_state,
            message=getattr(args, "message", None),
            owned_paths=(
                tuple(
                    path
                    for path in (
                        _project_config_path(),
                        getattr(args, "_project_config_migrated_from", None),
                    )
                    if path is not None
                )
                if getattr(args, "_project_config_changed", False)
                else ()
            ),
            input_func=getattr(args, "_init_input_func", None),
            stdin=getattr(args, "_init_stdin", None),
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
