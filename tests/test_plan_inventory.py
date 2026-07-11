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
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanWire,
    AgentMetaWire,
    DoneMarkerWire,
)
from sase.core.agent_artifact_paths import canonical_agent_artifact_path
from sase.core.paths import sase_projects_dir, sharded_path
from sase.core.time import get_timezone
from sase.main import plan_inventory as plan_inventory_module
from sase.main.plan_candidates import visible_pending_plan_notifications
from sase.main.plan_inventory import (
    build_plan_inventory,
    plan_inventory_to_json,
    render_plan_inventory,
)
from sase.notifications import pending_actions
from sase.notifications.models import Notification
from sase.notifications.store import append_notification
from tests._agent_loader_helpers import _empty_artifact_snapshot

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


def _set_plan_tier(path: Path, tier: str) -> None:
    path.write_text(f"---\ntier: {tier}\n---\n# {path.stem}\n", encoding="utf-8")


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


def _write_sharded_agent_meta(
    project: str,
    workflow: str,
    raw_timestamp: str,
    data: dict[str, object],
    *,
    minutes_ago: int,
) -> Path:
    artifact_dir = canonical_agent_artifact_path(
        project,
        workflow,
        raw_timestamp,
        projects_root=sase_projects_dir(),
    )
    artifact_dir.mkdir(parents=True)
    path = artifact_dir / "agent_meta.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    _touch(path, _timestamp(minutes_ago))
    return path


def _done_plan_snapshot(
    *,
    project: str = "demo",
    timestamp: str = _LIVE_AGENT_TS,
    cl_name: str = "demo-cl",
    agent_name: str = "planner",
) -> AgentArtifactScanWire:
    snapshot = _empty_artifact_snapshot()
    snapshot.records.append(
        AgentArtifactRecordWire(
            project_name=project,
            project_dir=f"/tmp/projects/{project}",
            project_file=f"/tmp/projects/{project}/{project}.sase",
            workflow_dir_name="ace-run",
            artifact_dir=f"/tmp/projects/{project}/artifacts/ace-run/{timestamp}",
            timestamp=timestamp,
            agent_meta=AgentMetaWire(
                name=agent_name,
                plan=True,
                plan_submitted_at=["2026-06-13T16:00:00Z"],
            ),
            done=DoneMarkerWire(
                outcome="completed",
                cl_name=cl_name,
                project_file=f"/tmp/projects/{project}/{project}.sase",
                name=agent_name,
            ),
            has_done_marker=True,
        )
    )
    return snapshot


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
        "sase.main.plan_candidates._load_live_plan_agents_for_notifications",
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
        "20260613140000",
        {
            "plan_approved": True,
            "plan_action": "epic",
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
            "action": "epic",
            "agent": "-",
            "project": "demo",
            "provider_model": "-",
            "plan_path": shared_rows[0]["plan_path"],
            "tier": "-",
            "meta_path": shared_rows[0]["meta_path"],
        }
    ]
    assert len(payload["rejected"]) == 10
    assert all(
        not str(row["plan_path"]).endswith("/rejected-11.md")
        for row in payload["rejected"]
    )


def test_inventory_includes_day_sharded_approved_plan() -> None:
    legacy_plan = _archived_plan("legacy-approved.md", minutes_ago=180)
    _write_agent_meta(
        "demo",
        "workflow-plan",
        "20260613090000",
        {
            "plan_approved": True,
            "plan_action": "approve",
            "plan_path": str(legacy_plan),
        },
        minutes_ago=180,
    )
    sharded_plan = _archived_plan("sharded-approved.md", minutes_ago=2)
    _write_sharded_agent_meta(
        "demo",
        "workflow-plan",
        "20260617070000",
        {
            "plan_approved": True,
            "plan_action": "tale",
            "plan_path": str(sharded_plan),
        },
        minutes_ago=2,
    )

    with patch(
        "sase.main.plan_candidates._load_live_plan_agents_for_notifications",
        return_value=(),
    ):
        payload = plan_inventory_to_json(build_plan_inventory())

    approved_paths = [str(row["plan_path"]) for row in payload["approved"]]
    assert any(path.endswith("/sharded-approved.md") for path in approved_paths)
    assert any(path.endswith("/legacy-approved.md") for path in approved_paths)
    rejected_paths = [str(row["plan_path"]) for row in payload["rejected"]]
    assert all(not path.endswith("/sharded-approved.md") for path in rejected_paths)


def test_inventory_tier_filter_and_json_breakdown() -> None:
    epic = _archived_plan("approved-epic.md", minutes_ago=2)
    tale = _archived_plan("rejected-tale.md", minutes_ago=3)
    _set_plan_tier(epic, "epic")
    _set_plan_tier(tale, "tale")
    _write_agent_meta(
        "demo",
        "workflow-plan",
        "20260613150000",
        {
            "plan_approved": True,
            "plan_action": "epic",
            "plan_path": str(epic),
        },
        minutes_ago=1,
    )

    payload = plan_inventory_to_json(build_plan_inventory(tiers=("epic",)))

    assert [row["tier"] for row in payload["approved"]] == ["epic"]
    assert payload["rejected"] == []
    assert payload["summary"]["tier_filter"] == ["epic"]
    assert payload["summary"]["by_tier"] == {"tale": 0, "epic": 1}


def test_approved_plan_scan_stops_after_limit() -> None:
    for index in range(10):
        plan = _archived_plan(f"approved-fast-{index:02d}.md", minutes_ago=index + 1)
        _write_agent_meta(
            "demo",
            "workflow-plan",
            f"2026061313{index:02d}00",
            {
                "plan_approved": True,
                "plan_action": "approve",
                "plan_path": str(plan),
            },
            minutes_ago=index + 1,
        )
    for index in range(50):
        _write_agent_meta(
            "demo",
            "workflow-plan",
            f"2026061212{index:02d}00",
            {"plan_approved": False},
            minutes_ago=100 + index,
        )

    with (
        patch(
            "sase.main.plan_candidates._load_live_plan_agents_for_notifications",
            return_value=(),
        ),
        patch(
            "sase.main.plan_inventory.read_json_object",
            wraps=plan_inventory_module.read_json_object,
        ) as read_json,
    ):
        payload = plan_inventory_to_json(build_plan_inventory(approved_limit=10))

    assert len(payload["approved"]) == 10
    assert read_json.call_count == 10


def test_visible_plan_notifications_loads_pending_store_once(
    tmp_path: Path,
) -> None:
    first_plan = _archived_plan("first.md", minutes_ago=5)
    second_plan = _archived_plan("second.md", minutes_ago=4)
    first_response = _response_dir(tmp_path, "first")
    second_response = _response_dir(tmp_path, "second")
    _append_plan_notification(
        "abcdef12-plan-notification",
        first_plan,
        first_response,
        minutes_ago=5,
        agent_timestamp="20260613120000",
    )
    _append_plan_notification(
        "12345678-plan-notification",
        second_plan,
        second_response,
        minutes_ago=4,
        agent_timestamp="20260613120100",
    )

    with patch.object(
        pending_actions,
        "_load_store",
        wraps=pending_actions._load_store,
    ) as load_store:
        visible = visible_pending_plan_notifications(
            agents=(
                _live_agent(raw_suffix="20260613120000"),
                _live_agent(raw_suffix="20260613120100"),
            )
        )

    assert [notification.id for notification in visible] == [
        "12345678-plan-notification",
        "abcdef12-plan-notification",
    ]
    load_store.assert_called_once_with(include_legacy=True)


def test_plan_inventory_exact_timestamp_fallback_matches_recent_done_planner(
    tmp_path: Path,
) -> None:
    timestamp = "20260612120000"
    plan = _archived_plan("fallback.md", minutes_ago=5)
    response_dir = _response_dir(tmp_path, "fallback")
    _append_plan_notification(
        "abcdef12-plan-notification",
        plan,
        response_dir,
        minutes_ago=5,
        agent_timestamp=timestamp,
    )
    artifact_dir = sase_projects_dir() / "demo" / "artifacts" / "ace-run" / timestamp
    artifact_dir.mkdir(parents=True)

    with patch(
        "sase.ace.tui.models.agent_loader._scan_artifact_dirs_for_loader",
        return_value=_done_plan_snapshot(timestamp=timestamp),
    ) as scan_dirs:
        payload = plan_inventory_to_json(build_plan_inventory())

    assert payload["summary"]["proposed"] == 1
    assert payload["proposed"][0]["id_prefix"] == "abcdef12"
    scan_dirs.assert_called_once()


def test_plan_inventory_exact_timestamp_fallback_finds_sharded_ace_artifact(
    tmp_path: Path,
) -> None:
    timestamp = "20260612120000"
    plan = _archived_plan("sharded-fallback.md", minutes_ago=5)
    response_dir = _response_dir(tmp_path, "sharded-fallback")
    _append_plan_notification(
        "abcdef12-plan-notification",
        plan,
        response_dir,
        minutes_ago=5,
        agent_timestamp=timestamp,
    )
    artifact_dir = canonical_agent_artifact_path(
        "demo",
        "ace-run",
        timestamp,
        projects_root=sase_projects_dir(),
    )
    artifact_dir.mkdir(parents=True)

    with patch(
        "sase.ace.tui.models.agent_loader._scan_artifact_dirs_for_loader",
        return_value=_done_plan_snapshot(timestamp=timestamp),
    ) as scan_dirs:
        payload = plan_inventory_to_json(build_plan_inventory())

    assert payload["summary"]["proposed"] == 1
    assert scan_dirs.call_args.args[0] == [artifact_dir]


def test_lightweight_live_plan_loader_promotes_unreviewed_done_plan(
    tmp_path: Path,
) -> None:
    from sase.ace.tui.models.agent_loader import load_live_plan_agents

    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    snapshot = _done_plan_snapshot()

    with (
        patch(
            "sase.ace.tui.models.agent_loader.default_agent_artifact_index_path",
            return_value=index_path,
        ),
        patch(
            "sase.ace.tui.models.agent_loader.query_agent_artifact_index",
            return_value=snapshot,
        ) as query_index,
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
        ) as source_scan,
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps_from_snapshot",
        ) as workflow_steps,
        patch(
            "sase.ace.tui.models._agent_status_overrides._classify_diff_badges",
            side_effect=AssertionError("diff badges should be skipped"),
        ),
    ):
        agents = load_live_plan_agents()

    assert [(agent.raw_suffix, agent.status) for agent in agents] == [
        (_LIVE_AGENT_TS, "PLAN")
    ]
    query_index.assert_called_once()
    assert query_index.call_args.kwargs["options"].include_prompt_step_markers is False
    source_scan.assert_not_called()
    workflow_steps.assert_not_called()


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
        "sase.main.plan_candidates._load_live_plan_agents_for_notifications",
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
        "sase.main.plan_candidates._load_live_plan_agents_for_notifications",
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
        "sase.main.plan_candidates._load_live_plan_agents_for_notifications",
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
        "sase.main.plan_candidates._load_live_plan_agents_for_notifications",
        return_value=(_live_agent(cl_name="demo-cl", agent_name="planner"),),
    ):
        payload = plan_inventory_to_json(build_plan_inventory())

    assert payload["summary"]["proposed"] == 1
    assert payload["proposed"][0]["agent"] == "planner"
