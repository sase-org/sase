"""Apply workflow for ``sase memory init`` and its ``sase init memory`` alias."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable, Mapping, Sequence
import os
from pathlib import Path
import sys
from typing import TextIO

from sase.agent.identity import agent_marker_present
from sase.memory.paths import memory_write_root
from sase.project_management import enable_sase_management
from sase.workflows.commit.command_hooks import run_before_commit_hook

from . import _init_memory_support as memory_support
from ._init_chezmoi_deploy import (
    ChezmoiDeployBehavior,
    defer_chezmoi_paths,
    deploy_to_chezmoi as deploy_to_chezmoi_impl,
)
from ._init_memory_plan import plan_init_memory
from ._init_memory_support import (
    load_memory_inputs,
    memory_plan_warnings,
    memory_root_plan_warnings,
    memory_root_plans,
)
from .init_memory.config import project_config_path, project_config_read_path
from .init_memory.constants import COMMAND_LABEL
from .init_memory.git_state import PreInitGitState
from .init_memory.inventory import print_validation_errors
from .init_memory.models import MemoryRootPlan, MemoryRootResult
from .init_memory.project_deploy import (
    capture_pre_init_git_state,
    deploy_to_project_repo as deploy_project_repo,
)
from .init_memory.roots import initialize_memory_root
from .init_project_scope import is_project_directory

HOME_MEMORY_DEPLOY_BYPASS_ENV = "SASE_HOME_MEMORY_DEPLOY_BYPASS"
_GATE_COMMAND_VALUE = "1"
_emitted_home_bypass_reasons: set[str] = set()


def _sase_memory_path(root: Path) -> Path:
    """Return the generated SASE memory path for ``root``."""
    return memory_write_root(root) / "sase.md"


def _print_config_errors(errors: Iterable[str]) -> None:
    for error in errors:
        print(error, file=sys.stderr)


def _stdin_is_tty() -> bool:
    return sys.stdin.isatty()


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
    git_state = None if no_commit else capture_pre_init_git_state(project_root)
    config_path = project_config_path()
    config_source_path = project_config_read_path()
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
    project_result: MemoryRootResult,
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
    exit_code = deploy_project_repo(
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
    if exit_code != 0 or no_commit:
        return exit_code
    try:
        from sase.main.init_memory.tracking import verify_publish_guard_for_root

        problems = verify_publish_guard_for_root(
            project_result.root, include_project_memory=True
        )
    except Exception:  # noqa: BLE001 - the guard never masks a deploy result.
        return exit_code
    if problems:
        for problem in problems:
            print(f"{COMMAND_LABEL}: {problem}", file=sys.stderr)
        return 1
    return exit_code


def _deploy_to_chezmoi(
    written_paths: Iterable[Path],
    delete_targets: Sequence[Path] = (),
) -> int:
    exit_code = deploy_to_chezmoi_impl(
        written_paths,
        ChezmoiDeployBehavior(
            command_label=COMMAND_LABEL,
            commit_message="chore: initialize sase memory",
            auto_commit_type="memory",
            chezmoi_home=memory_support.CHEZMOI_HOME,
            pull_push=False,
            apply_when_nothing_staged=True,
            commit_failed_label="chezmoi commit failed",
            print_committing=False,
            print_nothing_to_commit=False,
            print_applying=False,
            print_apply_done=False,
            delete_targets=tuple(delete_targets),
            delete_target_root=Path.home(),
        ),
    )
    if exit_code != 0:
        return exit_code
    try:
        from sase.main.init_memory.tracking import verify_publish_guard_for_root

        problems = verify_publish_guard_for_root(memory_support.CHEZMOI_HOME)
    except Exception:  # noqa: BLE001 - the guard never masks a deploy result.
        return exit_code
    if problems:
        for problem in problems:
            print(f"{COMMAND_LABEL}: {problem}", file=sys.stderr)
        return 1
    return exit_code


def _memory_root_plan_blockers(
    root_plans: Iterable[MemoryRootPlan],
) -> tuple[str, ...]:
    return tuple(blocker for root_plan in root_plans for blocker in root_plan.blockers)


def _home_memory_deploy_allowed(
    env: Mapping[str, str] | None = None,
    *,
    stderr: TextIO | None = None,
) -> bool:
    """Return whether this process may write or apply the shared home memory root."""
    current = env if env is not None else os.environ
    if not agent_marker_present(current):
        return True
    gate = current.get("SASE_GATE_COMMAND")
    if isinstance(gate, str) and gate.strip() == _GATE_COMMAND_VALUE:
        return True
    bypass = current.get(HOME_MEMORY_DEPLOY_BYPASS_ENV)
    reason = bypass.strip() if isinstance(bypass, str) else ""
    if reason:
        _emit_home_memory_bypass_reason(
            reason, sys.stderr if stderr is None else stderr
        )
        return True
    return False


def _emit_home_memory_bypass_reason(reason: str, stream: TextIO) -> None:
    if reason in _emitted_home_bypass_reasons:
        return
    _emitted_home_bypass_reasons.add(reason)
    print(f"{HOME_MEMORY_DEPLOY_BYPASS_ENV}: {reason}", file=stream)


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

    inputs = load_memory_inputs(args)
    for warning in memory_plan_warnings(inputs):
        print(f"{COMMAND_LABEL}: warning: {warning}", file=sys.stderr)
    if inputs.config_errors:
        _print_config_errors(inputs.config_errors)
        return 1

    if getattr(args, "diff", False):
        from .init_preview import preview_console, render_plan_diff

        render_plan_diff(preview_console(sys.stdout), plan_init_memory(args))

    root_plans = memory_root_plans(inputs)
    for warning in memory_root_plan_warnings(root_plans):
        print(f"{COMMAND_LABEL}: warning: {warning}", file=sys.stderr)
    root_plan_blockers = _memory_root_plan_blockers(root_plans)
    if root_plan_blockers:
        _print_config_errors(root_plan_blockers)
        return 1

    git_state = getattr(args, "_project_config_git_state", None)
    if inputs.is_project_dir and not inputs.no_commit:
        if not getattr(args, "_project_memory_opt_in_prepared", False):
            git_state = capture_pre_init_git_state(inputs.project_root)
        if git_state is not None and not inputs.is_sase_managed:
            git_state = PreInitGitState(
                git_root=git_state.git_root,
                memory_dirty=(),
                other_dirty=(*git_state.other_dirty, *git_state.memory_dirty),
            )

    skip_home = not _home_memory_deploy_allowed()
    home_plan = root_plans[-1]
    project_result: MemoryRootResult | None = None
    if inputs.is_project_dir:
        project_result = initialize_memory_root(
            inputs.project_root,
            inputs.project_entries,
            project_name=inputs.project_name,
            manage_memory=inputs.is_sase_managed,
            enable_amd=True,
            derive_project_title=inputs.is_sase_managed,
            chezmoi_home_roots=(inputs.home_root,) if inputs.use_chezmoi else (),
            include_project_agent_docs=True,
            include_project_memory=True,
        )
    if skip_home:
        home_result = MemoryRootResult(
            root=home_plan.root,
            written_paths=(),
            unreferenced=home_plan.unreferenced,
            deleted_paths=(),
        )
    else:
        home_result = initialize_memory_root(
            inputs.home_root,
            inputs.home_entries,
            enable_amd=True,
            chezmoi_home_roots=(inputs.home_root,) if inputs.use_chezmoi else (),
        )
    results = tuple(
        result for result in (project_result, home_result) if result is not None
    )

    if any(result.unreferenced for result in results):
        print_validation_errors(results)
        return 1

    if skip_home:
        print(
            f"{COMMAND_LABEL}: home memory refresh deferred until land "
            "(agent run); rerun `sase memory init` outside an agent after "
            f"landing — home target: {_sase_memory_path(inputs.home_root)}"
        )
    print(f"{COMMAND_LABEL}: initialized memory")
    if inputs.is_project_dir and inputs.is_sase_managed:
        print(f"  project memory target: {_sase_memory_path(inputs.project_root)}")
    if not skip_home:
        print(f"  home memory target: {_sase_memory_path(inputs.home_root)}")
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
                        project_config_path(),
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

    if skip_home:
        return exit_code
    if inputs.use_chezmoi:
        home_changed_paths = (*home_result.written_paths, *home_result.deleted_paths)
        live_delete_targets: list[Path] = []
        for path in home_result.deleted_paths:
            try:
                relative = path.relative_to(memory_support.CHEZMOI_HOME)
            except ValueError:
                continue
            if relative.name.endswith(".tmpl") and relative.name != ".tmpl":
                relative = relative.with_name(relative.name[: -len(".tmpl")])
            live_delete_targets.append(Path.home() / relative)
        if defer_chezmoi_paths(
            home_changed_paths,
            chezmoi_home=memory_support.CHEZMOI_HOME,
            delete_targets=live_delete_targets,
            delete_target_root=Path.home(),
        ):
            chezmoi_exit_code = 0
        else:
            chezmoi_exit_code = _deploy_to_chezmoi(
                home_changed_paths,
                delete_targets=live_delete_targets,
            )
        if chezmoi_exit_code != 0:
            exit_code = chezmoi_exit_code
    return exit_code


def handle_memory_init_command(args: argparse.Namespace) -> None:
    """Handle the ``sase memory init`` command."""
    sys.exit(run_init_memory(args))
