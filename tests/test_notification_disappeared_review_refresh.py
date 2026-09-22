"""Tests for disappeared-review notification refreshes."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agents._notification_utils import (
    prepare_disappeared_plan_notification_refresh,
)
from sase.ace.tui.models.agent import Agent, AgentType

from tests._notification_toasts_helpers import (
    _FakeApp,
    _make,
    _patch_snapshot,
    _snapshot,
)


class TestDisappearedReviewRefresh:
    """A review row leaving the store refreshes only the agents it names."""

    def test_disappeared_plan_reviews_schedule_one_exact_artifact_delta(
        self,
        tmp_path: Path,
    ) -> None:
        app = _FakeApp()
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        agent = Agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="review-agent",
            project_file="/tmp/test.sase",
            status="TALE",
            start_time=datetime(2026, 7, 22, 9, 0, 0),
            raw_suffix="20260722090000",
            artifacts_dir=str(artifacts_dir),
        )
        app._agents = [agent]
        action_data = {
            "agent_cl_name": agent.cl_name,
            "agent_root_timestamp": agent.raw_suffix or "",
        }
        tale = _make(
            id="tale-review",
            action="PlanApproval",
            action_data=action_data,
            muted=True,
        )
        epic = _make(
            id="epic-review",
            action="EpicApproval",
            action_data=action_data,
        )
        app._notification_snapshot_cache = _snapshot([tale, epic])
        scheduled: list[tuple[tuple[Path, ...], str]] = []
        broad_refreshes: list[tuple[str, bool]] = []
        app._schedule_agent_artifact_delta_refresh = (  # type: ignore[attr-defined]
            lambda dirs, *, source: scheduled.append((tuple(dirs), source))
        )
        app.request_agents_refresh = (  # type: ignore[attr-defined]
            lambda source, *, latest_only: broad_refreshes.append((source, latest_only))
        )

        with (
            _patch_snapshot([]) as read_snapshot,
            patch("sase.notifications.load_notifications") as load_notifications,
        ):
            saw_new = asyncio.run(app._poll_agent_completions())

        assert saw_new is False
        assert scheduled == [((artifacts_dir,), "notification")]
        assert broad_refreshes == []
        assert app.notify.call_count == 0
        assert app._bell_rung == 0
        load_notifications.assert_not_called()
        assert read_snapshot.call_args.args[0] is False

    def test_unrelated_disappeared_notification_does_not_refresh(self) -> None:
        app = _FakeApp()
        unrelated = _make(id="question", action="UserQuestion")
        app._notification_snapshot_cache = _snapshot([unrelated])
        scheduled: list[tuple[object, str]] = []
        broad_refreshes: list[tuple[str, bool]] = []
        app._schedule_agent_artifact_delta_refresh = (  # type: ignore[attr-defined]
            lambda dirs, *, source: scheduled.append((dirs, source))
        )
        app.request_agents_refresh = (  # type: ignore[attr-defined]
            lambda source, *, latest_only: broad_refreshes.append((source, latest_only))
        )

        with _patch_snapshot([]):
            saw_new = asyncio.run(app._poll_agent_completions())

        assert saw_new is False
        assert scheduled == []
        assert broad_refreshes == []

    def test_disappeared_plan_review_uses_broad_fallback_without_exact_agent(
        self,
    ) -> None:
        app = _FakeApp()
        review = _make(
            id="missing-agent-review",
            action="PlanApproval",
            action_data={"agent_cl_name": "not-loaded"},
        )
        app._notification_snapshot_cache = _snapshot([review])
        scheduled: list[tuple[object, str]] = []
        broad_refreshes: list[tuple[str, bool]] = []
        app._schedule_agent_artifact_delta_refresh = (  # type: ignore[attr-defined]
            lambda dirs, *, source: scheduled.append((dirs, source))
        )
        app.request_agents_refresh = (  # type: ignore[attr-defined]
            lambda source, *, latest_only: broad_refreshes.append((source, latest_only))
        )

        with _patch_snapshot([]):
            saw_new = asyncio.run(app._poll_agent_completions())

        assert saw_new is False
        assert scheduled == []
        assert broad_refreshes == [("notification", True)]

    def test_disappeared_accepted_shell_gate_schedules_exact_delta(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from sase.notification_gates import paths
        from sase.notification_gates.decision import DECISION_RECEIPT_FILENAME

        monkeypatch.setattr(paths, "INTERACTION_REQUESTS_DIR", tmp_path / "requests")
        bundle = paths.bundle_paths("custom", "custom-accepted")
        bundle.root.mkdir(parents=True)
        bundle.request.write_text(
            '{"request_id":"custom-accepted","kind":"custom","shell":{}}\n',
            encoding="utf-8",
        )
        (bundle.root / DECISION_RECEIPT_FILENAME).write_text(
            '{"selected_option_ids":["approve"]}\n',
            encoding="utf-8",
        )
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        monkeypatch.setattr(
            "sase.gate_shell.store.find_gate_shell_by_gate_id",
            lambda _project, gate_id: (
                SimpleNamespace(artifacts_dir=str(artifacts_dir))
                if gate_id == "custom-accepted"
                else None
            ),
        )
        notification = _make(
            id="accepted-custom",
            action="CustomGate",
            action_data={
                "request_id": "custom-accepted",
                "request_kind": "custom",
            },
        )

        dirs, broad = prepare_disappeared_plan_notification_refresh(
            _FakeApp(),
            [notification],
            [],
        )

        assert dirs == (artifacts_dir,)
        assert broad is False

    def test_disappeared_unaccepted_shell_gate_does_not_refresh(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from sase.notification_gates import paths

        monkeypatch.setattr(paths, "INTERACTION_REQUESTS_DIR", tmp_path / "requests")
        bundle = paths.bundle_paths("custom", "custom-pending")
        bundle.root.mkdir(parents=True)
        bundle.request.write_text(
            '{"request_id":"custom-pending","kind":"custom","shell":{}}\n',
            encoding="utf-8",
        )
        notification = _make(
            id="pending-custom",
            action="CustomGate",
            action_data={"request_id": "custom-pending", "request_kind": "custom"},
        )

        dirs, broad = prepare_disappeared_plan_notification_refresh(
            _FakeApp(),
            [notification],
            [],
        )

        assert dirs == ()
        assert broad is False
