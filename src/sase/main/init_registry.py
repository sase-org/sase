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

    Config establishes the machine-local identity before the memory spec owns
    agent-document initialization (managed AGENTS.md and provider shims), and
    before the repo spec owns configured sidecars and project repository wiring.
    """
    from .config_init_handler import plan_config_init, run_config_init
    from .init_skills_handler import plan_init_skills, run_init_skills
    from .init_memory_handler import plan_init_memory, run_init_memory
    from .repo_init_handler import plan_repo_init, run_repo_init

    return (
        InitCommandSpec(
            name="config",
            label="Config",
            plan=plan_config_init,
            run=run_config_init,
        ),
        InitCommandSpec(
            name="memory",
            label="Memory",
            plan=plan_init_memory,
            run=run_init_memory,
        ),
        InitCommandSpec(
            name="repo",
            label="Repos",
            plan=plan_repo_init,
            run=run_repo_init,
        ),
        InitCommandSpec(
            name="skills",
            label="Skills",
            plan=plan_init_skills,
            run=run_init_skills,
        ),
    )


__all__ = ["InitCommandSpec", "iter_init_command_specs"]
