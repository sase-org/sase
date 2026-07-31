"""Tests for authored-plan dependency-wave layering."""

from __future__ import annotations

from dataclasses import dataclass

from sase.sdd.plan_waves import plan_phase_waves


@dataclass(frozen=True, slots=True)
class _Phase:
    id: str
    depends_on: tuple[str, ...]


def test_linear_chain_layers_one_phase_per_wave() -> None:
    phases = [
        _Phase("a", ()),
        _Phase("b", ("a",)),
        _Phase("c", ("b",)),
    ]

    assert plan_phase_waves(phases) == (("a",), ("b",), ("c",))


def test_diamond_dag_collapses_to_fewer_waves_than_phases() -> None:
    phases = [
        _Phase("a", ()),
        _Phase("b", ("a",)),
        _Phase("c", ("a",)),
        _Phase("d", ("b", "c")),
    ]

    assert plan_phase_waves(phases) == (("a",), ("b", "c"), ("d",))


def test_all_independent_phases_layer_into_one_wave() -> None:
    phases = [_Phase("a", ()), _Phase("b", ()), _Phase("c", ())]

    assert plan_phase_waves(phases) == (("a", "b", "c"),)


def test_authored_order_is_preserved_inside_a_wave() -> None:
    phases = [_Phase("c", ()), _Phase("a", ()), _Phase("b", ())]

    assert plan_phase_waves(phases) == (("c", "a", "b"),)


def test_empty_input_layers_to_no_waves() -> None:
    assert plan_phase_waves([]) == ()


def test_cycle_returns_none() -> None:
    phases = [_Phase("a", ("b",)), _Phase("b", ("a",))]

    assert plan_phase_waves(phases) is None


def test_dependency_outside_the_plan_returns_none() -> None:
    phases = [_Phase("a", ("missing",))]

    assert plan_phase_waves(phases) is None
