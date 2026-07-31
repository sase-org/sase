"""Direct coverage locking the ``preview_waves`` / ``sase bead work`` contract."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from sase.bead.cli_work_from_plan_helpers import preview_waves
from sase.bead.cli_work_from_plan_types import PlanFileWorkError


@dataclass(frozen=True, slots=True)
class _Phase:
    id: str
    depends_on: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Plan:
    phases: tuple[_Phase, ...]


def test_preview_waves_layers_a_valid_dag() -> None:
    plan = _Plan(
        phases=(
            _Phase("core", ()),
            _Phase("cli", ("core",)),
            _Phase("verify", ("core", "cli")),
        )
    )

    assert preview_waves(plan) == (("core",), ("cli",), ("verify",))


def test_preview_waves_raises_plan_file_work_error_on_cycle() -> None:
    plan = _Plan(phases=(_Phase("a", ("b",)), _Phase("b", ("a",))))

    with pytest.raises(
        PlanFileWorkError,
        match="validated epic plan contains a dependency cycle",
    ):
        preview_waves(plan)
