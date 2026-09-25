"""Coverage for the shared `%queue` / `%q` contract."""

from __future__ import annotations

import math
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest

from sase.core.agent_launch_facade import (
    agent_unit_dispatch_prompt,
    plan_typed_launch_units,
)
from sase.core.agent_launch_wire import AgentUnitWire
from sase.feature_flags import override_flags
from sase.xprompt.directives import DirectiveError, extract_prompt_directives
from sase.xprompt.queue_directive import (
    collect_queue_fields,
    format_queue_capacity_multiplier,
    format_queue_directive,
    parse_queue_capacity_value,
    resolve_queue_capacity_multiplier,
    validate_queue_capacity,
)


ROOT = Path(__file__).resolve().parents[1]
WEIGHTED_CAPACITY_CORE_FLOOR = (0, 33, 0)
_CORE_FLOOR_RE = re.compile(r"^sase-core-rs>=(\d+(?:\.\d+)*),<\d+(?:\.\d+)*$")


def _declared_core_floor() -> tuple[int, ...]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    for dependency in data["project"]["dependencies"]:
        match = _CORE_FLOOR_RE.match(dependency)
        if match is not None:
            return tuple(int(part) for part in match.group(1).split("."))
    raise AssertionError("sase-core-rs dependency is missing from pyproject.toml")


def test_sase_core_rs_floor_is_published_queue_directive_release() -> None:
    assert _declared_core_floor() >= WEIGHTED_CAPACITY_CORE_FLOOR


def test_queue_adapter_collects_and_formats_through_rust() -> None:
    result = collect_queue_fields(
        [
            {
                "source": "%q:5",
                "source_span": [0, 4],
                "args": [{"value": "5"}],
                "has_plus_suffix": False,
            },
            {
                "source": "%queue(p=20, w=0.25)",
                "source_span": [5, 26],
                "args": [
                    {"name": "p", "value": "20"},
                    {"name": "w", "value": "0.25"},
                ],
                "has_plus_suffix": False,
            },
        ]
    )
    assert result["errors"] == []
    assert result["fields"] == {"capacity": 5, "priority": 20, "weight": 0.25}
    assert (
        format_queue_directive(capacity=5, priority=20, weight=0.25)
        == "%queue(capacity=5, priority=20, weight=0.25)"
    )
    duplicate = collect_queue_fields(
        [
            {
                "source": "%q(5, capacity=5)",
                "source_span": [0, 17],
                "args": [
                    {"value": "5"},
                    {"name": "capacity", "value": "5"},
                ],
                "has_plus_suffix": False,
            }
        ]
    )
    assert duplicate["fields"] is None
    assert duplicate["errors"][0]["code"] == "duplicate-queue-field"
    obsolete = collect_queue_fields(
        [
            {
                "source": "%q(3, runners=3)",
                "source_span": [0, 16],
                "args": [
                    {"value": "3"},
                    {"name": "runners", "value": "3"},
                ],
                "has_plus_suffix": False,
            }
        ]
    )
    assert obsolete["fields"] is None
    assert obsolete["errors"][0]["code"] == "obsolete-queue-runners"
    assert "capacity=" in obsolete["errors"][0]["message"]


def test_queue_weight_extracts_unconditionally() -> None:
    cleaned, directives = extract_prompt_directives("%q(w=0.25)\nDo work")

    assert cleaned == "Do work"
    assert directives.queue_weight == 0.25
    assert directives.queue_weight_explicit is True


def test_capacity_multiplier_extracts_formats_and_rebuilds() -> None:
    with override_flags(queue_capacity_budget=True, typed_launch_units=True):
        parsed = parse_queue_capacity_value("1.50x")
        cleaned, directives = extract_prompt_directives("%q(1.5x, w=0.25)\nDo work")
        plan = plan_typed_launch_units(
            "%q(1.5x, w=0.25)\nDo work",
            selected_project="sase",
        )
        agent = plan.units[0].payload
        assert isinstance(agent, AgentUnitWire)
        rebuilt = agent_unit_dispatch_prompt(agent)

    assert parsed == {"queue_capacity_multiplier": 1.5}
    assert format_queue_capacity_multiplier(1.5) == "1.5x"
    assert resolve_queue_capacity_multiplier(1.5, 5) == 7.5
    assert format_queue_directive(capacity_multiplier=1.5, weight=0.25) == (
        "%queue(capacity=1.5x, weight=0.25)"
    )
    assert cleaned == "Do work"
    assert directives.queue_capacity is None
    assert directives.queue_capacity_multiplier == 1.5
    assert agent.queue_capacity is None
    assert agent.queue_capacity_multiplier == 1.5
    assert "%queue(capacity=1.5x, weight=0.25)" in rebuilt


def test_queue_weight_alias_duplicate_errors() -> None:
    with pytest.raises(DirectiveError, match="Duplicate"):
        extract_prompt_directives("%q(w=1, weight=1)\nDo work")


def test_typed_launch_parses_queue_and_rebuilds_canonical_prompt() -> None:
    with override_flags(typed_launch_units=True):
        plan = plan_typed_launch_units(
            "%w(builder, time=5m) %q(3, p=20, w=2)\nDo work",
            selected_project="sase",
        )
        agent = plan.units[0].payload
        assert isinstance(agent, AgentUnitWire)
        assert agent.wait_runners == 3
        assert agent.wait_priority == 20
        assert agent.queue_weight == 2.0
        assert agent.queue_weight_explicit is True
        rebuilt = agent_unit_dispatch_prompt(agent)
    assert "%queue(capacity=3, priority=20, weight=2)" in rebuilt
    assert "%wait(runners=" not in rebuilt


def test_typed_launch_preserves_explicit_default_weight() -> None:
    with override_flags(typed_launch_units=True):
        plan = plan_typed_launch_units("%q(w=1.0)\nDo work", selected_project="sase")
        agent = plan.units[0].payload
        assert isinstance(agent, AgentUnitWire)
        rebuilt = agent_unit_dispatch_prompt(agent)

    assert agent.queue_weight == 1.0
    assert agent.queue_weight_explicit is True
    assert "%queue(weight=1)" in rebuilt


def test_typed_launch_rejects_retired_wait_queue_keywords() -> None:
    with override_flags(typed_launch_units=True):
        with pytest.raises(Exception, match="%queue"):
            plan_typed_launch_units(
                "%wait(runners=5)\nDo work",
                selected_project="sase",
            )
        with pytest.raises(Exception, match="%queue"):
            plan_typed_launch_units(
                "%wait(priority=5)\nDo work",
                selected_project="sase",
            )


def _queue_occurrence(source: str, args: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "source": source,
        "source_span": [0, len(source)],
        "args": args,
        "has_plus_suffix": False,
    }


@pytest.mark.parametrize(
    ("spelling", "name", "value"),
    [("%q(w=0)", "w", "0"), ("%queue(weight=0.0)", "weight", "0.0")],
)
@pytest.mark.parametrize("budget", [True, False])
def test_zero_weight_directive_collects_through_rust(
    spelling: str, name: str, value: str, budget: bool
) -> None:
    with override_flags(queue_capacity_budget=budget):
        result = collect_queue_fields(
            [_queue_occurrence(spelling, [{"name": name, "value": value}])]
        )

    assert result["errors"] == []
    assert isinstance(result["fields"], dict)
    weight = result["fields"]["weight"]
    assert weight == 0.0
    assert math.copysign(1.0, weight) == 1.0


def test_zero_weight_with_capacity_budget_collects_through_rust() -> None:
    with override_flags(queue_capacity_budget=True):
        result = collect_queue_fields(
            [
                _queue_occurrence(
                    "%q(1, w=0)", [{"value": "1"}, {"name": "w", "value": "0"}]
                )
            ]
        )

    assert result["errors"] == []
    assert result["fields"] == {"capacity": 1, "weight": 0.0}


@pytest.mark.parametrize("budget", [True, False])
def test_negative_zero_weight_still_rejected(budget: bool) -> None:
    with override_flags(queue_capacity_budget=budget):
        result = collect_queue_fields(
            [_queue_occurrence("%q(w=-0)", [{"name": "w", "value": "-0"}])]
        )

    assert result["fields"] is None
    assert result["errors"][0]["code"] == "invalid-queue-weight"


def test_format_zero_weight_emits_weight_zero() -> None:
    assert format_queue_directive(weight=0.0) == "%queue(weight=0)"


@pytest.mark.parametrize("budget", [True, False])
def test_zero_weight_extracts_explicit(budget: bool) -> None:
    with override_flags(queue_capacity_budget=budget):
        cleaned, directives = extract_prompt_directives("%q(w=0)\nDo work")

    assert cleaned == "Do work"
    assert directives.queue_weight == 0.0
    assert directives.queue_weight_explicit is True


def test_typed_launch_dispatch_prompt_carries_zero_weight() -> None:
    with override_flags(typed_launch_units=True):
        plan = plan_typed_launch_units("%q(w=0)\nDo work", selected_project="sase")
        agent = plan.units[0].payload
        assert isinstance(agent, AgentUnitWire)
        assert agent.queue_weight == 0.0
        assert agent.queue_weight_explicit is True
        rebuilt = agent_unit_dispatch_prompt(agent)

    assert "%queue(weight=0)" in rebuilt


def test_validate_queue_capacity_rejects_booleans_and_invalid_numbers() -> None:
    assert validate_queue_capacity("3") == 3
    assert validate_queue_capacity(4294967295) == 4294967295
    with pytest.raises(ValueError, match="at least 1|positive"):
        validate_queue_capacity(0)
    with override_flags(queue_capacity_budget=False):
        assert validate_queue_capacity(0) == 0
    with pytest.raises(ValueError, match="boolean"):
        validate_queue_capacity(True)
    with pytest.raises(ValueError, match="boolean"):
        validate_queue_capacity(False)
    with pytest.raises(ValueError, match="positive integer"):
        validate_queue_capacity(1.5)
    with pytest.raises(ValueError, match="positive integer"):
        validate_queue_capacity(-1)
    with pytest.raises(ValueError):
        validate_queue_capacity("4294967296")
    with pytest.raises(ValueError):
        validate_queue_capacity("true")
