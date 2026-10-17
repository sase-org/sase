"""Read-only planning for ``sase memory init``."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path

from sase.main.init_plan import InitAction, InitPlan

from ._init_memory_support import (
    load_memory_inputs,
    memory_plan_warnings,
    memory_root_plan_warnings,
    memory_root_plans,
)
from .init_memory.config import project_config_path
from .init_memory.models import MemoryRootPlan


def _format_unreferenced_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root.resolve(strict=False)))
    except ValueError:
        return str(path)


def _memory_plan_blockers(
    root_plans: Iterable[MemoryRootPlan],
) -> tuple[str, ...]:
    blockers: list[str] = []
    for root_plan in root_plans:
        blockers.extend(root_plan.blockers)
        for path in root_plan.unreferenced:
            display = _format_unreferenced_path(root_plan.root, path)
            blockers.append(f"{root_plan.root}: unreferenced memory file {display}")
    return tuple(blockers)


def _deferred_home_memory_warning(pending_count: int) -> str:
    noun = "home memory file" if pending_count == 1 else "home memory files"
    return (
        f"{pending_count} {noun} out of sync with rendered sources; refresh is "
        "deferred until land. Rerun `sase memory init` after landing."
    )


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
    inputs = load_memory_inputs(args)
    warnings = memory_plan_warnings(inputs)
    if inputs.config_errors:
        return InitPlan(
            command="memory",
            label="Memory",
            summary="cannot generate memory until configuration is fixed",
            actions=(),
            warnings=warnings,
            blockers=inputs.config_errors,
        )

    root_plans = memory_root_plans(inputs)
    home_plan = root_plans[-1]
    project_plans = root_plans[:-1]
    check_mode = bool(getattr(args, "check", False))
    warnings_list = list(warnings)
    if check_mode:
        change_plans = project_plans
        if home_plan.changes:
            warnings_list.append(_deferred_home_memory_warning(len(home_plan.changes)))
    else:
        change_plans = root_plans
    actions = tuple(
        InitAction(
            path=change.path,
            operation=change.operation,
            detail=change.detail,
            new_content=change.new_content,
        )
        for root_plan in change_plans
        for change in root_plan.changes
    )
    if getattr(args, "_project_config_changed", False):
        config_action = InitAction(
            path=project_config_path(),
            operation=getattr(args, "_project_config_operation", "update"),
            detail="mark repository as SASE-managed in sase.yml",
        )
        actions = (config_action, *actions)
    blockers = _memory_plan_blockers(root_plans)
    warnings = (*warnings_list, *memory_root_plan_warnings(root_plans))
    try:
        from sase.main.init_memory.tracking import tracking_blockers_for_root

        tracking = (
            *(
                tracking_blockers_for_root(
                    inputs.project_root,
                    label="memory",
                    include_project_memory=True,
                )
                if inputs.is_project_dir
                else ()
            ),
            *(
                tracking_blockers_for_root(inputs.home_root, label="memory")
                if inputs.use_chezmoi
                else ()
            ),
        )
    except Exception:  # noqa: BLE001 - tracking never breaks planning.
        tracking = ()
    blockers = (*blockers, *tracking)
    return InitPlan(
        command="memory",
        label="Memory",
        summary=_summarize_memory_actions(actions),
        actions=actions,
        warnings=warnings,
        blockers=blockers,
    )
