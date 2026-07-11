"""Registry for ``sase init`` onboarding subcommands."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass

from .init_plan import InitPlan


@dataclass(frozen=True)
class InitCommandSpec:
    """Planner and runner pair for one ``sase init`` subcommand."""

    name: str
    label: str
    plan: Callable[[argparse.Namespace], InitPlan]
    run: Callable[[argparse.Namespace], int]


def iter_init_command_specs() -> tuple[InitCommandSpec, ...]:
    """Return registered onboarding specs in execution order.

    The memory spec now owns agent-document initialization (managed AGENTS.md
    and provider shims), so onboarding registers memory, SDD, skills, and
    workspace specs.
    """
    from .init_skills_handler import plan_init_skills, run_init_skills
    from .init_memory_handler import plan_init_memory, run_init_memory
    from .init_workspace_handler import plan_init_workspace, run_init_workspace
    from .sdd_handler import plan_sdd_init, run_sdd_init

    return (
        InitCommandSpec(
            name="memory",
            label="Memory",
            plan=plan_init_memory,
            run=run_init_memory,
        ),
        InitCommandSpec(
            name="sdd",
            label="SDD",
            plan=plan_sdd_init,
            run=run_sdd_init,
        ),
        InitCommandSpec(
            name="skills",
            label="Skills",
            plan=plan_init_skills,
            run=run_init_skills,
        ),
        InitCommandSpec(
            name="workspace",
            label="Workspace",
            plan=plan_init_workspace,
            run=run_init_workspace,
        ),
    )


__all__ = ["InitCommandSpec", "iter_init_command_specs"]
