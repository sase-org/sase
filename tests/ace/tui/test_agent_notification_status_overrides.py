"""Tests for Agents-tab notification reconciliation."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agents._notification_navigation import (
    find_agent_for_notification,
)
from sase.ace.tui.actions.agents._notification_plan_reconciliation import (
    AgentNotificationPlanReconciliationMixin,
    prepare_plan_notification_reconciliation,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.notifications import Notification


class _NotificationApp:
    def __init__(self, agents: list[Agent]) -> None:
        self._agents = agents
        self._agents_with_children = agents


class _ExternalPlanResponseApp(AgentNotificationPlanReconciliationMixin):
    def __init__(self, agents: list[Agent]) -> None:
        self._agents = agents
        self._agents_with_children = agents
        self._agent_status_overrides: dict[tuple[AgentType, str, str | None], str] = {}
        self.notification_count_refreshes = 0
        self.notification_snapshot_refreshes = 0
        self.delta_refreshes: list[tuple[tuple[Path, ...], str]] = []
        self.broad_refreshes = 0

    def _schedule_agent_artifact_delta_refresh(
        self, artifact_dirs: tuple[Path, ...], *, source: str = "unknown"
    ) -> None:
        self.delta_refreshes.append((tuple(artifact_dirs), source))

    def _schedule_agents_async_refresh(self, *, source: str = "unknown") -> None:
        del source
        self.broad_refreshes += 1

    def _refresh_notification_count(self) -> None:
        self.notification_count_refreshes += 1

    def _schedule_notification_snapshot_refresh(self) -> None:
        self.notification_snapshot_refreshes += 1


def _notification(
    *,
    action: str = "PlanApproval",
    cl_name: str = "oo",
    agent_name: str | None = None,
    agent_timestamp: str = "20260512094333",
    agent_root_timestamp: str = "20260512090000",
    response_dir: str = "/tmp/response",
    request_id: str | None = None,
) -> Notification:
    action_data = {
        "agent_cl_name": cl_name,
        "agent_timestamp": agent_timestamp,
        "agent_root_timestamp": agent_root_timestamp,
        "response_dir": response_dir,
        "session_id": "session",
    }
    if agent_name:
        action_data["agent_name"] = agent_name
    if request_id:
        action_data["request_id"] = request_id
    return Notification(
        id="n1",
        timestamp="2026-05-12T09:43:33",
        sender="plan" if action == "PlanApproval" else "question",
        action=action,
        action_data=action_data,
    )


def test_find_agent_for_notification_matches_root_timestamp() -> None:
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="oo",
        project_file="/tmp/test.sase",
        status="PLAN",
        start_time=datetime(2026, 5, 12, 9, 0, 0),
        raw_suffix="20260512090000",
        role_suffix=".plan",
    )
    app = _NotificationApp([parent])

    assert find_agent_for_notification(app, _notification()) is parent


def test_find_agent_for_notification_matches_agent_name_timestamp() -> None:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="different-cl",
        project_file="/tmp/test.sase",
        status="PLAN",
        start_time=datetime(2026, 5, 12, 9, 43, 33),
        raw_suffix="20260512094333",
        agent_name="planner",
    )
    app = _NotificationApp([agent])

    assert (
        find_agent_for_notification(
            app,
            _notification(
                cl_name="oo",
                agent_name="planner",
                agent_root_timestamp="20260512090000",
            ),
        )
        is agent
    )


@pytest.mark.parametrize(
    ("notification_action", "response", "expected_action"),
    [
        (
            "PlanApproval",
            {"action": "approve", "commit_plan": False, "run_coder": True},
            "approve",
        ),
        (
            "PlanApproval",
            {"action": "approve", "commit_plan": True, "run_coder": True},
            "tale",
        ),
        (
            "EpicApproval",
            {"action": "epic", "commit_plan": True, "run_coder": True},
            "epic",
        ),
        (
            "PlanApproval",
            {"action": "approve", "commit_plan": True, "run_coder": False},
            "commit",
        ),
    ],
)
def test_legacy_external_plan_response_dismisses_and_persists_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    notification_action: str,
    response: dict[str, object],
    expected_action: str,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    response_dir = tmp_path / "response"
    response_dir.mkdir()
    (response_dir / "plan_response.json").write_text(
        json.dumps(response), encoding="utf-8"
    )
    dismissed: list[str] = []
    monkeypatch.setattr(
        "sase.notifications.mark_dismissed",
        lambda notification_id: dismissed.append(notification_id),
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_plan_persistence."
        "update_agent_artifact_index_for_marker_mutation",
        lambda artifacts_dir: None,
    )

    agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="oo",
        project_file="/tmp/test.sase",
        status="PLAN",
        start_time=datetime(2026, 5, 12, 9, 0, 0),
        raw_suffix="20260512090000",
        role_suffix=".plan",
        artifacts_dir=str(artifacts_dir),
    )
    app = _ExternalPlanResponseApp([agent])
    app._agent_status_overrides[agent.identity] = "PLAN"

    auto_dismissed_ids = app._reconcile_plan_notification_lifecycle(
        [
            _notification(
                action=notification_action,
                response_dir=str(response_dir),
            )
        ]
    )

    assert auto_dismissed_ids == {"n1"}
    assert dismissed == ["n1"]
    assert agent.identity not in app._agent_status_overrides
    assert app.delta_refreshes == [((artifacts_dir,), "notification")]
    assert app.broad_refreshes == 0
    assert app.notification_count_refreshes == 1
    assert json.loads((artifacts_dir / "agent_meta.json").read_text()) == {
        "plan_approved": True,
        "plan_action": expected_action,
    }


@pytest.mark.parametrize(
    (
        "notification_action",
        "request_kind",
        "selected_option_ids",
    ),
    [
        (
            "PlanApproval",
            "plan",
            ["approve", "commit"],
        ),
        (
            "EpicApproval",
            "epic_plan",
            ["approve"],
        ),
    ],
)
def test_neutral_gate_response_is_ignored_by_legacy_reconciliation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    notification_action: str,
    request_kind: str,
    selected_option_ids: list[str],
) -> None:
    from sase.notification_gates import paths

    request_id = f"{request_kind}-request"
    bundle_dir = tmp_path / request_kind / request_id
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "request.json").write_text(
        json.dumps({"kind": request_kind}),
        encoding="utf-8",
    )
    option_results = [
        {
            "id": option_id,
            "result": {
                "action": "epic" if request_kind == "epic_plan" else "approve",
                "commit_plan": option_id == "commit",
                "run_coder": option_id != "commit",
            },
        }
        for option_id in selected_option_ids
    ]
    (bundle_dir / "response.json").write_text(
        json.dumps(
            {
                "selected_option_ids": selected_option_ids,
                "option_results": option_results,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(paths, "INTERACTION_REQUESTS_DIR", tmp_path)
    dismissed: list[str] = []
    monkeypatch.setattr(
        "sase.notifications.mark_dismissed",
        lambda notification_id: dismissed.append(notification_id),
    )
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="oo",
        project_file="/tmp/test.sase",
        status="TALE" if request_kind == "plan" else "EPIC",
        start_time=datetime(2026, 5, 12, 9, 0, 0),
        raw_suffix="20260512090000",
        role_suffix=".plan",
        artifacts_dir=str(artifacts_dir),
    )
    app = _ExternalPlanResponseApp([agent])
    app._agent_status_overrides[agent.identity] = "TALE"
    notification = _notification(
        action=notification_action,
        request_id=request_id,
    )

    prepared = prepare_plan_notification_reconciliation(
        app,
        [notification],
    ).external_responses
    dismissed_ids = app._reconcile_plan_notification_lifecycle(
        [notification],
        prepared_external_plan_responses=prepared,
    )

    assert prepared == {}
    assert dismissed_ids == set()
    assert dismissed == []
    assert app._agent_status_overrides[agent.identity] == "TALE"
    assert app.delta_refreshes == []
    assert app.notification_snapshot_refreshes == 0
    assert not (artifacts_dir / "agent_meta.json").exists()


def test_telegram_gate_resolution_dismisses_and_finalizes_pending_tale_override(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.actions.agents._loading_compute_finalize import (
        _compute_status_override_plan,
    )
    from sase.ace.tui.models._loaders._meta_enrichment import enrich_agent_from_meta
    from sase.notification_gates.executor import execute_gate_selection
    from sase.notification_gates.service import create_gate
    from sase.notifications.store import load_notifications
    from sase.plan_gate import build_plan_approval_gate_spec
    from tests.plan_validation_helpers import VALID_TALE_PLAN

    artifacts_dir = gate_home / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"plan": True}) + "\n",
        encoding="utf-8",
    )
    root_timestamp = "20260722090000"
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    monkeypatch.setenv("SASE_AGENT_CL_NAME", "telegram-plan")
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", root_timestamp)
    monkeypatch.setenv("SASE_AGENT_ROOT_TIMESTAMP", root_timestamp)
    plan_path = gate_home / "telegram-tale.md"
    plan_path.write_text(VALID_TALE_PLAN, encoding="utf-8")
    gate = create_gate(
        build_plan_approval_gate_spec(
            plan_path,
            "telegram-tale",
            agent_name="telegram-plan.plan",
        )
    )
    [pending_notification] = load_notifications()

    with patch(
        "sase.plan_approval_actions._archive_plan_for_approval",
        return_value=str(gate_home / "archived-tale.md"),
    ):
        execution = execute_gate_selection(
            gate.bundle_path,
            ("approve", "commit"),
            source="telegram",
        )

    assert execution.response["source"] == "telegram"
    assert load_notifications() == []
    [handled_notification] = load_notifications(include_dismissed=True)
    assert handled_notification.id == pending_notification.id
    assert handled_notification.dismissed is True
    assert json.loads((artifacts_dir / "agent_meta.json").read_text()) == {
        "plan": True,
        "plan_approved": True,
        "plan_action": "tale",
    }

    loaded_agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="telegram-plan",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 22, 9, 0, 0),
        raw_suffix=root_timestamp,
        role_suffix=".plan",
        artifacts_dir=str(artifacts_dir),
    )
    enrich_agent_from_meta(loaded_agent, str(artifacts_dir))
    finalize_plan = _compute_status_override_plan(
        [loaded_agent],
        {loaded_agent.identity: "TALE"},
    )

    assert loaded_agent.status == "TALE APPROVED"
    assert finalize_plan.overrides_to_apply == []
    assert finalize_plan.cleared_identities == [loaded_agent.identity]
