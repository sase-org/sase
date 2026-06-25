"""Tests for the Auto-Approve menu open + apply flow (``a`` key on agents)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agents._approve import (
    AgentApproveMixin,
    _auto_approval_choice_for_agent,
    _auto_approval_state_for_choice,
)
from sase.ace.tui.actions.task_actions import TrackedTaskCompletion, TrackedTaskResult
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.modals.auto_approve_modal import AutoApproveModal
from sase.ace.tui.task_queue import TaskInfo


def _make_agent(artifacts_dir: str, **overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "test_cl",
        "project_file": "/tmp/projects/myproj/myproj.sase",
        "status": "RUNNING",
        "start_time": datetime(2024, 1, 1, 12, 0, 0),
        "raw_suffix": "20240101120000",
        "artifacts_dir": artifacts_dir,
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


class FakeApproveApp(AgentApproveMixin):
    def __init__(self, agent: Agent | None) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents = [agent] if agent is not None else []
        self._selected = agent
        self.notifications: list[tuple[str, str]] = []
        self.scheduled: list[tuple[Any, tuple[Any, ...], dict[str, Any]]] = []
        self.refresh_calls: list[bool] = []
        self.pushed_screens: list[tuple[Any, Any]] = []
        # The approve handler tries selective row patching first, falling back
        # to a full refresh when the patch can't land. This fake forces the
        # fallback so the contract (in-memory mutation + refresh + persistence)
        # stays under test without a real widget tree.
        self.patch_attempts: int = 0

    def _try_patch_agent_row(self, agent: Agent) -> bool:
        del agent
        self.patch_attempts += 1
        return False

    def _get_selected_agent(self) -> Agent | None:
        return self._selected

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def call_later(self, callback: Any, *args: Any, **kwargs: Any) -> None:
        self.scheduled.append((callback, args, kwargs))

    def _submit_tracked_task(
        self,
        task_type: str,
        cl_name: str,
        project_file: str,
        task_callable: Any,
        *,
        display_name: str | None = None,
        dedup_key: str | None = None,
        duplicate_message: str | None = None,
        on_complete: Any = None,
        reload_on_complete: bool = True,
        notify_on_complete: bool = True,
    ) -> TaskInfo:
        del duplicate_message, reload_on_complete, notify_on_complete
        task_info = TaskInfo(
            task_id=f"task-{len(self.scheduled)}",
            task_type=task_type,
            cl_name=cl_name,
            project_file=project_file,
            status="running",
            message="running",
            started_at=datetime.now(),
            display_name=display_name,
            dedup_key=dedup_key,
        )

        async def _run() -> None:
            try:
                result = task_callable()
            except Exception as exc:
                result = TrackedTaskResult(
                    success=False,
                    message=str(exc),
                    error=str(exc),
                )
            task_info.status = "success" if result.success else "error"
            task_info.message = result.message
            task_info.error = result.error
            if on_complete is not None:
                on_complete(
                    TrackedTaskCompletion(
                        task_info=task_info,
                        success=result.success,
                        message=result.message,
                        output="",
                        payload=result.payload,
                        error=result.error,
                    )
                )

        self.scheduled.append((_run, (), {}))
        return task_info

    def _refresh_agents_display(self, *, list_changed: bool = False) -> None:
        self.refresh_calls.append(list_changed)

    def push_screen(self, screen: Any, callback: Any = None) -> None:
        self.pushed_screens.append((screen, callback))


# --- Pure mapping helpers ------------------------------------------------


def test_auto_approval_choice_for_agent_maps_each_state() -> None:
    assert _auto_approval_choice_for_agent(_make_agent("/x")) == "disable"
    assert _auto_approval_choice_for_agent(_make_agent("/x", approve=True)) == "plan"
    assert (
        _auto_approval_choice_for_agent(
            _make_agent("/x", approve=True, auto_approve_plan_action="tale")
        )
        == "tale"
    )
    assert (
        _auto_approval_choice_for_agent(
            _make_agent("/x", approve=True, auto_approve_plan_action="epic")
        )
        == "epic"
    )


def test_auto_approval_state_for_choice_table() -> None:
    assert _auto_approval_state_for_choice("plan")[:2] == (True, None)
    assert _auto_approval_state_for_choice("tale")[:2] == (True, "tale")
    assert _auto_approval_state_for_choice("epic")[:2] == (True, "epic")
    assert _auto_approval_state_for_choice("disable")[:2] == (False, None)


# --- Persistence primitive ------------------------------------------------


def testpersist_approve_field_writes_new_file(tmp_path: Any) -> None:
    agent = _make_agent(str(tmp_path))
    app = FakeApproveApp(agent)

    app._apply_auto_approve_choice(agent, "plan")
    asyncio.run(app.scheduled[0][0]())

    assert json.loads((tmp_path / "agent_meta.json").read_text()) == {"approve": True}


def testpersist_approve_field_preserves_other_keys(tmp_path: Any) -> None:
    meta_path = tmp_path / "agent_meta.json"
    meta_path.write_text(json.dumps({"approve": False, "other": "keep"}))
    agent = _make_agent(str(tmp_path))
    app = FakeApproveApp(agent)

    app._apply_auto_approve_choice(agent, "plan")
    asyncio.run(app.scheduled[0][0]())

    data = json.loads(meta_path.read_text())
    assert data["approve"] is True
    assert data["other"] == "keep"


def test_persist_plan_auto_approval_epic_clears_legacy_approve(
    tmp_path: Any,
) -> None:
    meta_path = tmp_path / "agent_meta.json"
    meta_path.write_text(json.dumps({"approve": True, "other": "keep"}))
    agent = _make_agent(str(tmp_path))
    app = FakeApproveApp(agent)

    app._apply_auto_approve_choice(agent, "epic")
    asyncio.run(app.scheduled[0][0]())

    data = json.loads(meta_path.read_text())
    assert data["auto_approve_plan_action"] == "epic"
    assert data["other"] == "keep"
    assert "approve" not in data


def test_persist_plan_auto_approval_refreshes_artifact_index(tmp_path: Any) -> None:
    agent = _make_agent(str(tmp_path))
    app = FakeApproveApp(agent)

    with patch(
        "sase.ace.tui.actions.agents._directive_persistence."
        "update_agent_artifact_index_for_marker_mutation"
    ) as update_index:
        app._apply_auto_approve_choice(agent, "plan")
        asyncio.run(app.scheduled[0][0]())

    update_index.assert_called_once_with(str(tmp_path))


# --- Menu open routing ----------------------------------------------------


def test_open_menu_pushes_modal_marking_current_state(tmp_path: Any) -> None:
    agent = _make_agent(str(tmp_path), approve=True, auto_approve_plan_action="epic")
    app = FakeApproveApp(agent)

    app.action_open_auto_approve_menu()

    assert len(app.pushed_screens) == 1
    screen, callback = app.pushed_screens[0]
    assert isinstance(screen, AutoApproveModal)
    assert screen._current == "epic"
    assert callable(callback)
    # Opening the menu mutates nothing on its own.
    assert agent.auto_approve_plan_action == "epic"
    assert app.scheduled == []


def test_open_menu_no_op_off_agents_tab(tmp_path: Any) -> None:
    agent = _make_agent(str(tmp_path))
    app = FakeApproveApp(agent)
    app.current_tab = "changespecs"

    app.action_open_auto_approve_menu()

    assert app.pushed_screens == []
    assert app.notifications == []


def test_open_menu_warns_when_status_ineligible(tmp_path: Any) -> None:
    agent = _make_agent(str(tmp_path), status="DONE")
    app = FakeApproveApp(agent)

    app.action_open_auto_approve_menu()

    assert app.pushed_screens == []
    assert any(sev == "warning" for _, sev in app.notifications)


def test_open_menu_warns_when_no_agent_selected() -> None:
    app = FakeApproveApp(None)

    app.action_open_auto_approve_menu()

    assert app.pushed_screens == []
    assert any(sev == "warning" for _, sev in app.notifications)


def _dismiss_with(app: FakeApproveApp, choice: str | None) -> None:
    """Invoke the dismiss callback recorded by the last ``push_screen``."""
    callback = app.pushed_screens[-1][1]
    callback(choice)


# --- Apply: each menu choice ---------------------------------------------


def test_choose_plan_enables_normal_auto_approve(tmp_path: Any) -> None:
    agent = _make_agent(str(tmp_path))
    app = FakeApproveApp(agent)

    app.action_open_auto_approve_menu()
    _dismiss_with(app, "plan")

    assert agent.approve is True
    assert agent.auto_approve_plan_action is None
    # Optimistic refresh fired and disk write scheduled (not inline).
    assert app.refresh_calls == [True]
    assert len(app.scheduled) == 1
    assert not (tmp_path / "agent_meta.json").exists()
    assert any(msg.startswith("Auto-approve enabled") for msg, _ in app.notifications)

    asyncio.run(app.scheduled[0][0]())
    assert json.loads((tmp_path / "agent_meta.json").read_text()) == {"approve": True}


def test_choose_tale_sets_tale_action(tmp_path: Any) -> None:
    agent = _make_agent(str(tmp_path), approve=True)
    app = FakeApproveApp(agent)

    app.action_open_auto_approve_menu()
    _dismiss_with(app, "tale")

    assert agent.approve is True
    assert agent.auto_approve_plan_action == "tale"
    assert any(
        msg.startswith("Tale auto-approve enabled") for msg, _ in app.notifications
    )

    asyncio.run(app.scheduled[0][0]())
    # Tale carries its state in the action; the legacy approve key is omitted.
    assert json.loads((tmp_path / "agent_meta.json").read_text()) == {
        "auto_approve_plan_action": "tale"
    }


def test_choose_epic_sets_epic_action(tmp_path: Any) -> None:
    agent = _make_agent(str(tmp_path), approve=True)
    app = FakeApproveApp(agent)

    app.action_open_auto_approve_menu()
    _dismiss_with(app, "epic")

    assert agent.approve is True
    assert agent.auto_approve_plan_action == "epic"

    asyncio.run(app.scheduled[0][0]())
    assert json.loads((tmp_path / "agent_meta.json").read_text()) == {
        "auto_approve_plan_action": "epic"
    }


def test_choose_disable_clears_everything(tmp_path: Any) -> None:
    meta_path = tmp_path / "agent_meta.json"
    meta_path.write_text(
        json.dumps(
            {
                "approve": True,
                "auto_approve_plan_action": "epic",
                "other": "keep",
            }
        )
    )
    agent = _make_agent(str(tmp_path), approve=True, auto_approve_plan_action="epic")
    app = FakeApproveApp(agent)

    app.action_open_auto_approve_menu()
    _dismiss_with(app, "disable")

    assert agent.approve is False
    assert agent.auto_approve_plan_action is None

    asyncio.run(app.scheduled[0][0]())
    assert json.loads(meta_path.read_text()) == {"other": "keep"}


def test_cancel_leaves_agent_unchanged(tmp_path: Any) -> None:
    agent = _make_agent(str(tmp_path), approve=True, auto_approve_plan_action="tale")
    app = FakeApproveApp(agent)

    app.action_open_auto_approve_menu()
    _dismiss_with(app, None)

    assert agent.approve is True
    assert agent.auto_approve_plan_action == "tale"
    assert app.scheduled == []
    assert app.refresh_calls == []
    assert not (tmp_path / "agent_meta.json").exists()


def test_apply_rolls_back_on_persist_failure(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A disk failure reverts the optimistic mutation and shows an error."""
    agent = _make_agent(str(tmp_path))
    app = FakeApproveApp(agent)

    def _boom(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise OSError("disk full")

    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._approve.persist_agent_directive_update",
        _boom,
    )

    app.action_open_auto_approve_menu()
    _dismiss_with(app, "tale")
    assert agent.auto_approve_plan_action == "tale"  # optimistic

    asyncio.run(app.scheduled[0][0]())

    assert agent.approve is False  # rolled back
    assert agent.auto_approve_plan_action is None
    assert any(sev == "error" for _, sev in app.notifications)
    # Refresh fired twice: once optimistic, once on rollback.
    assert app.refresh_calls == [True, True]


def test_apply_warns_when_no_artifacts_dir() -> None:
    agent = _make_agent("")
    app = FakeApproveApp(agent)
    with patch.object(Agent, "get_artifacts_dir", return_value=None):
        app._apply_auto_approve_choice(agent, "tale")

    assert app.scheduled == []
    assert any(sev == "warning" for _, sev in app.notifications)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
