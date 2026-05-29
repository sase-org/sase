"""Read-only planning for ``sase amd init``."""

from __future__ import annotations

import argparse
from pathlib import Path

from sase.main.init_plan import InitAction, InitPlan

from ._config import amd_init_roots, load_amd_h1_title
from ._memory import render_managed_agents
from ._shared import (
    AmdInitPlan,
    PlannedWrite,
    planned_write,
    provider_shim_writes,
    provider_statuses,
    read_text,
)
from .constants import AGENTS_FILENAME


def _migration_writes(
    root: Path,
    provider_statuses: dict[Path, str],
) -> tuple[tuple[PlannedWrite, ...], tuple[str, ...]]:
    agents_path = root / AGENTS_FILENAME
    if agents_path.exists():
        return (), ()

    custom_provider_paths = tuple(
        path for path, status in provider_statuses.items() if status == "custom"
    )
    shim_provider_paths = tuple(
        path
        for path, status in provider_statuses.items()
        if status in {"exact_shim", "shim"}
    )

    if len(custom_provider_paths) > 1:
        names = ", ".join(path.name for path in custom_provider_paths)
        return (), (
            f"{AGENTS_FILENAME} is missing and multiple provider instruction "
            f"files contain custom content: {names}",
        )

    if len(custom_provider_paths) == 0:
        if shim_provider_paths:
            names = ", ".join(path.name for path in shim_provider_paths)
            return (), (
                f"{AGENTS_FILENAME} is missing but provider shim files already "
                f"point to it: {names}",
            )
        return (), ()

    source_path = custom_provider_paths[0]
    source_text, error = read_text(source_path)
    if error is not None or source_text is None:
        return (), (error or f"{source_path}: failed to read legacy provider file",)

    writes: list[PlannedWrite] = []
    agents_write = planned_write(
        agents_path,
        source_text,
        detail=f"migrate {source_path.name} to AGENTS.md",
    )
    if agents_write is not None:
        writes.append(agents_write)
    writes.extend(provider_shim_writes(root))
    return tuple(writes), ()


def _summarize_amd_actions(
    actions: tuple[InitAction, ...], blockers: tuple[str, ...]
) -> str:
    if blockers:
        return "cannot initialize agent markdown documents until blockers are fixed"
    if not actions:
        return "agent markdown documents are current"
    if len(actions) == 1:
        action = actions[0]
        return f"{action.operation} {action.detail}"
    operations = {action.operation for action in actions}
    if operations == {"create"}:
        verb = "create"
    elif operations == {"overwrite"}:
        verb = "overwrite"
    else:
        verb = "refresh"
    return f"{verb} {len(actions)} agent markdown documents"


def _build_single_amd_init_plan(root: Path, *, explicit: bool = True) -> AmdInitPlan:
    """Return the pure AMD init plan for one root without writing files."""
    title, title_error = load_amd_h1_title(root)
    provider_status_map, provider_errors = provider_statuses(root)
    blockers = tuple(error for error in (title_error, *provider_errors) if error)
    writes: list[PlannedWrite] = []

    if not blockers:
        if title is not None:
            agents_write = planned_write(
                root / AGENTS_FILENAME,
                render_managed_agents(root, title),
                detail="managed AGENTS.md",
            )
            if agents_write is not None:
                writes.append(agents_write)
            writes.extend(provider_shim_writes(root))
        elif not explicit:
            pass
        else:
            migration_writes, migration_blockers = _migration_writes(
                root,
                provider_status_map,
            )
            blockers = migration_blockers
            if not blockers:
                writes.extend(migration_writes)
                if not migration_writes:
                    writes.extend(provider_shim_writes(root))

    actions = tuple(write.action for write in writes)
    return AmdInitPlan(
        plan=InitPlan(
            command="amd",
            label="AMD",
            summary=_summarize_amd_actions(actions, blockers),
            actions=actions,
            blockers=blockers,
        ),
        writes=tuple(writes),
    )


def _combine_amd_init_plans(plans: tuple[AmdInitPlan, ...]) -> AmdInitPlan:
    actions: list[InitAction] = []
    warnings: list[str] = []
    blockers: list[str] = []
    writes: list[PlannedWrite] = []

    for built in plans:
        actions.extend(built.plan.actions)
        warnings.extend(built.plan.warnings)
        blockers.extend(built.plan.blockers)
        writes.extend(built.writes)

    return AmdInitPlan(
        plan=InitPlan(
            command="amd",
            label="AMD",
            summary=_summarize_amd_actions(tuple(actions), tuple(blockers)),
            actions=tuple(actions),
            warnings=tuple(warnings),
            blockers=tuple(blockers),
        ),
        writes=tuple(writes),
    )


def build_amd_init_plan(
    root: Path | None = None, *, explicit: bool = True
) -> AmdInitPlan:
    """Return the pure AMD init plan without writing files."""
    if root is not None:
        return _build_single_amd_init_plan(root, explicit=explicit)

    roots = amd_init_roots(Path.cwd())
    return _combine_amd_init_plans(
        tuple(_build_single_amd_init_plan(root, explicit=explicit) for root in roots)
    )


def plan_amd_init_for_check(args: argparse.Namespace) -> InitPlan:
    """Return a read-only plan for ``sase amd init``."""
    is_bare_onboarding = (
        getattr(args, "command", None) == "init"
        and getattr(args, "init_subcommand", None) is None
    )
    explicit = not is_bare_onboarding
    return build_amd_init_plan(explicit=explicit).plan


def plan_amd_init(args: argparse.Namespace) -> InitPlan:
    """Return a read-only AMD init plan for onboarding registries."""
    return plan_amd_init_for_check(args)
