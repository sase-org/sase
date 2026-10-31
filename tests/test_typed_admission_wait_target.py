"""Typed admission forwards explicit `%wait target=` to the launched runner."""

from __future__ import annotations

import pytest

from sase.agent.launch_admission_request_data import typed_plan_from_request
from sase.agent.launch_request import _typed_plan_payload
from sase.core.agent_launch_facade import agent_unit_dispatch_prompt
from sase.core.agent_launch_wire import AgentUnitWire
from sase.macro.directives import extract_prompt_directives


def test_typed_admission_forwards_explicit_wait_target_to_dispatch_prompt() -> None:
    pytest.importorskip("sase_core_rs")
    raw = _typed_plan_payload("%wait(planner, target=turn)\nDo work")
    assert raw is not None
    plan = typed_plan_from_request({"typed_plan": raw})
    unit = plan.units[0]
    assert unit.waits == []
    payload = unit.payload
    assert isinstance(payload, AgentUnitWire)
    dispatch = agent_unit_dispatch_prompt(payload)
    assert "%wait(planner, target=turn)" in dispatch
    _, directives = extract_prompt_directives(dispatch)
    assert dict(directives.wait_targets) == {"planner": "turn"}
