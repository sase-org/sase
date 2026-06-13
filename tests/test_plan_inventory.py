"""Tests for ``sase plan list`` inventory and rendering."""

from __future__ import annotations

import io
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from rich.console import Console

from sase.core.paths import sase_projects_dir, sharded_path
from sase.core.time import get_timezone
from sase.main.plan_inventory import (
    build_plan_inventory,
    plan_inventory_to_json,
    render_plan_inventory,
)
from sase.notifications.models import Notification
from sase.notifications.store import append_notification


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
) -> None:
    append_notification(
        Notification(
            id=notification_id,
            timestamp=_timestamp(minutes_ago).isoformat(),
            sender="plan",
            files=[str(plan_path)],
            action="PlanApproval",
            action_data={
                "agent_name": "planner",
                "llm_provider": "anthropic",
                "model": "claude-sonnet",
                "project_dir": "/work/demo-project",
                "response_dir": str(response_dir),
            },
        )
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
