"""Coverage for the shared `%queue` / `%q` contract."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from sase.core.agent_launch_facade import (
    agent_unit_dispatch_prompt,
    plan_typed_launch_units,
)
from sase.core.agent_launch_wire import AgentUnitWire
from sase.feature_flags import override_flags
from sase.xprompt.queue_directive import collect_queue_fields, format_queue_directive


ROOT = Path(__file__).resolve().parents[1]
QUEUE_DIRECTIVE_CORE_FLOOR = (0, 32, 52)
_CORE_FLOOR_RE = re.compile(r"^sase-core-rs>=(\d+(?:\.\d+)*),<\d+(?:\.\d+)*$")


def _declared_core_floor() -> tuple[int, ...]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    for dependency in data["project"]["dependencies"]:
        match = _CORE_FLOOR_RE.match(dependency)
        if match is not None:
            return tuple(int(part) for part in match.group(1).split("."))
    raise AssertionError("sase-core-rs dependency is missing from pyproject.toml")


def test_sase_core_rs_floor_is_published_queue_directive_release() -> None:
    assert _declared_core_floor() >= QUEUE_DIRECTIVE_CORE_FLOOR


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
                "source": "%queue(p=20)",
                "source_span": [5, 18],
                "args": [{"name": "p", "value": "20"}],
                "has_plus_suffix": False,
            },
        ]
    )
    assert result["errors"] == []
    assert result["fields"] == {"runners": 5, "priority": 20}
    assert (
        format_queue_directive(runners=5, priority=20)
        == "%queue(runners=5, priority=20)"
    )
    duplicate = collect_queue_fields(
        [
            {
                "source": "%q(5, runners=5)",
                "source_span": [0, 16],
                "args": [
                    {"value": "5"},
                    {"name": "runners", "value": "5"},
                ],
                "has_plus_suffix": False,
            }
        ]
    )
    assert duplicate["fields"] is None
    assert duplicate["errors"][0]["code"] == "duplicate-queue-field"


def test_typed_launch_parses_queue_and_rebuilds_canonical_prompt() -> None:
    with override_flags(typed_launch_units=True):
        plan = plan_typed_launch_units(
            "%w(builder, time=5m) %q(1, p=20)\nDo work",
            selected_project="sase",
        )
        agent = plan.units[0].payload
        assert isinstance(agent, AgentUnitWire)
        assert agent.wait_runners == 1
        assert agent.wait_priority == 20
        rebuilt = agent_unit_dispatch_prompt(agent)
    assert "%queue(runners=1, priority=20)" in rebuilt
    assert "%wait(runners=" not in rebuilt


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
