"""Shared result types for bare ``sase init`` onboarding."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from .init_plan import InitPlan

InitRunStatus = Literal[
    "current",
    "initialized",
    "needs_attention",
    "failed",
    "cancelled",
]


@dataclass(frozen=True)
class InitRunResult:
    """Structured result for one onboarding run."""

    exit_code: int
    status: InitRunStatus
    plans: tuple[InitPlan, ...] = ()


def result_with_plans(
    result: InitRunResult, plans: Sequence[InitPlan]
) -> InitRunResult:
    return InitRunResult(result.exit_code, result.status, tuple(plans))
