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

    Phase 1 only introduces the registry surface. Later init plan/apply
    phases register memory, SDD, and skills specs as their read-only planners
    become available.
    """
    return ()


__all__ = ["InitCommandSpec", "iter_init_command_specs"]
