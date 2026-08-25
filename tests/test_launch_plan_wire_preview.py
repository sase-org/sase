"""Launch-plan wire and preview behavior."""

from __future__ import annotations

from pathlib import Path

from sase.agent.launch_executor_types import LaunchExecutionContext
from sase.agent.launch_preview import (
    build_launch_preview_request,
    render_launch_preview_markdown,
)
from sase.core.agent_launch_facade import plan_fake_fanout
from sase.core.agent_launch_wire import (
    AgentUnitWire,
    agent_launch_wire_to_json_dict,
    launch_plan_from_dict,
)
from tests._launch_admission_helpers import (
    agent_unit as _agent_unit,
    plan as _plan,
)


def test_payload_json_includes_kind() -> None:
    plan = _plan(_agent_unit("unit-1"))
    payload = agent_launch_wire_to_json_dict(plan)
    assert payload["units"][0]["payload"]["kind"] == "agent"


def test_preview_markdown_includes_typed_plan(tmp_path: Path) -> None:
    request = build_launch_preview_request(
        plan=plan_fake_fanout("agent", ["Do work"]),
        context=LaunchExecutionContext(
            cl_name="demo",
            project_file=str(tmp_path / "project.sase"),
            project_name="demo",
        ),
        source_surface="cli",
        request_id="preview-typed",
        created_at_unix=1.0,
    )
    request["typed_plan"] = {
        "content_digest": "abc123digest",
        "approval_preview": ["LaunchPlan v1 kind=agent units=1 project=demo"],
    }
    markdown = render_launch_preview_markdown(request)
    assert "## Typed launch plan" in markdown
    assert "digest `abc123digest`" in markdown
    assert "LaunchPlan v1" in markdown


def test_launch_plan_from_dict_round_trips_kind() -> None:
    original = _plan(_agent_unit("unit-1"))
    restored = launch_plan_from_dict(agent_launch_wire_to_json_dict(original))
    assert isinstance(restored.units[0].payload, AgentUnitWire)
    assert restored.units[0].payload.prompt == "Do work"
