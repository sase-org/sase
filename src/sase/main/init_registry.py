"""Registry for ``sase init`` onboarding subcommands."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from .init_plan import InitPlan

InitCommandScope = Literal["project", "machine"]


@dataclass(frozen=True)
class InitCommandSpec:
    """Planner and runner pair for one ``sase init`` subcommand."""

    name: str
    label: str
    plan: Callable[[argparse.Namespace], InitPlan]
    run: Callable[[argparse.Namespace], int]
    scope: InitCommandScope = "project"
    decline: Callable[[argparse.Namespace], None] | None = None

    def __post_init__(self) -> None:
        if self.name == "machine" and self.scope == "project":
            object.__setattr__(self, "scope", "machine")


def iter_init_command_specs() -> tuple[InitCommandSpec, ...]:
    """Return registered onboarding specs in execution order.

    Config establishes the explicit owner identity before optional remote-machine
    enrollment, then the memory spec owns agent-document initialization (managed
    AGENTS.md and provider shims), and the repo spec owns configured sidecars
    and project repository wiring.
    """
    from .config_init_handler import plan_config_init, run_config_init
    from .init_machine_handler import plan_init_machine, run_init_machine
    from .init_service_handler import (
        decline_init_service,
        plan_init_service,
        run_init_service,
    )
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
            name="machine",
            label="Machine",
            plan=plan_init_machine,
            run=run_init_machine,
            scope="machine",
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
            name="service",
            label="Service",
            plan=plan_init_service,
            run=run_init_service,
            scope="machine",
            decline=decline_init_service,
        ),
        InitCommandSpec(
            name="skills",
            label="Skills",
            plan=plan_init_skills,
            run=run_init_skills,
        ),
    )


__all__ = ["InitCommandScope", "InitCommandSpec", "iter_init_command_specs"]
