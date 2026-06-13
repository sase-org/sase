"""Tests for ``sase plan list`` inventory and rendering."""

from __future__ import annotations

import io
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from rich.console import Console

from sase.ace.tui.models.agent import Agent, AgentType
from sase.core.paths import sase_projects_dir, sharded_path
from sase.core.time import get_timezone
from sase.main.plan_inventory import (
    build_plan_inventory,
    plan_inventory_to_json,
    render_plan_inventory,
)
from sase.notifications.models import Notification
from sase.notifications.store import append_notification

_LIVE_AGENT_TS = "20260613120000"
_LIVE_AGENT_ROOT_TS = "20260613115900"


def _timestamp(minutes_ago: int) -> datetime:
    return datetime.now(get_timezone()) - timedelta(minutes=minutes_ago)


def _touch(path: Path, timestamp: datetime) -> None:
    epoch = timestamp.timestamp()
    os.utime(path, (epoch, epoch))


def _archived_plan(name: str, *, minutes_ago: int) -> Path:
    timestamp = _timestamp(minutes_ago)
    path = Path(sharded_path("plans", name, ts=timestamp))
    path.write_text(f"# {name}\n", encoding="utf-8")
    _touch(path, timestamp)
    return path


def _response_dir(root: Path, name: str) -> Path:
    path = root / "responses" / name
    path.mkdir(parents=True)
    (path / "plan_request.json").write_text("{}", encoding="utf-8")
    return path


def _append_plan_notification(
    notification_id: str,
    plan_path: Path,
    response_dir: Path,
    *,
    minutes_ago: int,
    agent_cl_name: str = "demo-cl",
    agent_name: str = "planner",
    agent_timestamp: str | None = _LIVE_AGENT_TS,
    agent_root_timestamp: str | None = None,
) -> None:
    action_data = {
        "agent_name": agent_name,
        "llm_provider": "anthropic",
        "model": "claude-sonnet",
        "project_dir": "/work/demo-project",
        "response_dir": str(response_dir),
    }
    if agent_cl_name:
        action_data["agent_cl_name"] = agent_cl_name
    if agent_timestamp:
        action_data["agent_timestamp"] = agent_timestamp
    if agent_root_timestamp:
        action_data["agent_root_timestamp"] = agent_root_timestamp
    append_notification(
        Notification(
            id=notification_id,
            timestamp=_timestamp(minutes_ago).isoformat(),
            sender="plan",
            files=[str(plan_path)],
            action="PlanApproval",
            action_data=action_data,
        )
    )


def _live_agent(
    *,
    status: str = "PLAN",
    cl_name: str = "demo-cl",
    agent_name: str = "planner",
    raw_suffix: str = _LIVE_AGENT_TS,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/demo-project.sase",
        status=status,
        start_time=None,
        raw_suffix=raw_suffix,
        agent_name=agent_name,
        workspace_dir="/work/demo-project",
    )


def _write_agent_meta(
    project: str,
    workflow: str,
    raw_timestamp: str,
    data: dict[str, object],
    *,
    minutes_ago: int,
) -> Path:
    path = (
        sase_projects_dir()
        / project
        / "artifacts"
        / workflow
        / raw_timestamp
        / "agent_meta.json"
    )
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    _touch(path, _timestamp(minutes_ago))
    return path


def test_build_plan_inventory_classifies_proposed_approved_and_rejected(
    tmp_path: Path,
) -> None:
    proposed_plan = _archived_plan("proposed.md", minutes_ago=30)
    approved_plan = _archived_plan("approved.md", minutes_ago=20)
    rejected_plan = _archived_plan("rejected.md", minutes_ago=10)
    response_dir = _response_dir(tmp_path, "proposed")
    _append_plan_notification(
        "abcdef12-plan-notification",
        proposed_plan,
        response_dir,
        minutes_ago=4,
    )
    _write_agent_meta(
        "demo",
        "workflow-plan",
        "20260613120000",
        {
            "plan_approved": True,
            "plan_action": "tale",
            "plan_path": str(approved_plan),
            "name": "approved-agent",
            "llm_provider": "openai",
            "model": "gpt-5",
        },
        minutes_ago=2,
    )

    with patch(
        "sase.main.plan_candidates._load_live_plan_agents",
        return_value=(_live_agent(),),
    ):
        inventory = build_plan_inventory()
    payload = plan_inventory_to_json(inventory)

    assert payload["summary"] == {
        "proposed": 1,
        "approved_shown": 1,
        "rejected_shown": 1,
        "total_archived_proposals": 3,
    }
    assert payload["proposed"][0]["id_prefix"] == "abcdef12"
    assert payload["proposed"][0]["agent"] == "planner"
    assert payload["proposed"][0]["project"] == "demo-project"
    assert payload["proposed"][0]["provider_model"] == "anthropic/claude-sonnet"
    assert payload["approved"][0]["action"] == "tale"
    assert payload["approved"][0]["agent"] == "approved-agent"
    assert payload["approved"][0]["provider_model"] == "openai/gpt-5"
    assert payload["rejected"][0]["plan_path"].endswith("/rejected.md")
    assert "inferred from archived proposal" in str(payload["rejected"][0]["note"])
    assert str(rejected_plan) in payload["rejected"][0]["plan_path"].replace(
        "~/.sase", str(Path(os.environ["SASE_HOME"]).expanduser())
    )


def test_inventory_dedupes_approved_by_plan_path_and_applies_limits() -> None:
    shared_plan = _archived_plan("shared.md", minutes_ago=50)
    _write_agent_meta(
        "demo",
        "workflow-plan",
        "20260613110000",
        {
            "plan_approved": True,
            "plan_action": "approve",
            "plan_path": str(shared_plan),
        },
        minutes_ago=40,
    )
    _write_agent_meta(
        "demo",
        "workflow-plan",
        "20260613120000",
        {
            "plan_approved": True,
            "plan_action": "legend",
            "plan_path": str(shared_plan),
        },
        minutes_ago=1,
    )
    for index in range(12):
        plan = _archived_plan(f"approved-{index:02d}.md", minutes_ago=80 + index)
        _write_agent_meta(
            "demo",
            "workflow-plan",
            f"2026061313{index:02d}00",
            {
                "plan_approved": True,
                "plan_action": "epic",
                "plan_path": str(plan),
            },
            minutes_ago=10 + index,
        )
    for index in range(12):
        _archived_plan(f"rejected-{index:02d}.md", minutes_ago=20 + index)

    inventory = build_plan_inventory(approved_limit=10, rejected_limit=10)
    payload = plan_inventory_to_json(inventory)

    approved_paths = [row["plan_path"] for row in payload["approved"]]
    shared_rows = [
        row
        for row in payload["approved"]
        if str(row["plan_path"]).endswith("/shared.md")
    ]
    assert len(payload["approved"]) == 10
    assert len(set(approved_paths)) == 10
    assert shared_rows == [
        {
            "timestamp": shared_rows[0]["timestamp"],
            "age": shared_rows[0]["age"],
            "action": "legend",
            "agent": "-",
            "project": "demo",
            "provider_model": "-",
            "plan_path": shared_rows[0]["plan_path"],
            "meta_path": shared_rows[0]["meta_path"],
        }
    ]
    assert len(payload["rejected"]) == 10
    assert all(
        not str(row["plan_path"]).endswith("/rejected-11.md")
        for row in payload["rejected"]
    )


def test_render_plan_inventory_empty_state_is_intentional() -> None:
    inventory = build_plan_inventory()
    buffer = io.StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=100)

    render_plan_inventory(inventory, console=console)

    output = buffer.getvalue()
    assert "Plan Pipeline" in output
    assert "Proposed" in output
    assert "Approved" in output
    assert "Rejected" in output
    assert "No pending plan proposals." in output
    assert "No approved plans found." in output
    assert "No inferred rejected plans." in output


def test_render_plan_inventory_non_empty_output_uses_stable_columns(
    tmp_path: Path,
) -> None:
    plan = _archived_plan("proposed.md", minutes_ago=5)
    response_dir = _response_dir(tmp_path, "proposed")
    _append_plan_notification(
        "12345678-plan-notification",
        plan,
        response_dir,
        minutes_ago=5,
    )
    with patch(
        "sase.main.plan_candidates._load_live_plan_agents",
        return_value=(_live_agent(),),
    ):
        inventory = build_plan_inventory()
    buffer = io.StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=100)

    render_plan_inventory(inventory, console=console)

    output = buffer.getvalue()
    assert "ID" in output
    assert "Age" in output
    assert "Agent/Project" in output
    assert "Model" in output
    assert "Plan path" in output
    assert "12345678" in output
    assert "planner / demo-project" in output


def test_plan_inventory_excludes_proposal_without_matching_live_agent(
    tmp_path: Path,
) -> None:
    plan = _archived_plan("orphan.md", minutes_ago=5)
    response_dir = _response_dir(tmp_path, "orphan")
    _append_plan_notification(
        "12345678-plan-notification",
        plan,
        response_dir,
        minutes_ago=5,
        agent_timestamp="20260613130000",
    )

    with patch(
        "sase.main.plan_candidates._load_live_plan_agents",
        return_value=(_live_agent(),),
    ):
        payload = plan_inventory_to_json(build_plan_inventory())

    assert payload["summary"]["proposed"] == 0
    assert payload["summary"]["rejected_shown"] == 1
    assert str(payload["rejected"][0]["plan_path"]).endswith("/orphan.md")


def test_plan_inventory_matches_root_timestamp(tmp_path: Path) -> None:
    plan = _archived_plan("root.md", minutes_ago=5)
    response_dir = _response_dir(tmp_path, "root")
    _append_plan_notification(
        "12345678-plan-notification",
        plan,
        response_dir,
        minutes_ago=5,
        agent_timestamp="20260613125900",
        agent_root_timestamp=_LIVE_AGENT_ROOT_TS,
    )

    with patch(
        "sase.main.plan_candidates._load_live_plan_agents",
        return_value=(_live_agent(raw_suffix=_LIVE_AGENT_ROOT_TS),),
    ):
        payload = plan_inventory_to_json(build_plan_inventory())

    assert payload["summary"]["proposed"] == 1
    assert payload["proposed"][0]["id_prefix"] == "12345678"


def test_plan_inventory_matches_agent_name_with_timestamp(tmp_path: Path) -> None:
    plan = _archived_plan("named.md", minutes_ago=5)
    response_dir = _response_dir(tmp_path, "named")
    _append_plan_notification(
        "12345678-plan-notification",
        plan,
        response_dir,
        minutes_ago=5,
        agent_cl_name="other-cl",
        agent_name="planner",
    )

    with patch(
        "sase.main.plan_candidates._load_live_plan_agents",
        return_value=(_live_agent(cl_name="demo-cl", agent_name="planner"),),
    ):
        payload = plan_inventory_to_json(build_plan_inventory())

    assert payload["summary"]["proposed"] == 1
    assert payload["proposed"][0]["agent"] == "planner"
