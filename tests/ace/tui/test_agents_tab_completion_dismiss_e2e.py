"""End-to-end contract tests for one-to-one agent completion dismissal.

The product contract this guards is:

- Each completed Agents-tab row is unread iff its matching completion
  notification is still active (not dismissed).
- Reading a single row dismisses exactly that row's matching notification.
- Dismissing a notification through the notification API clears exactly
  that row on the next reconciliation pass.
- Entering / navigating the Agents tab alone never bulk-dismisses
  unrelated completion (or non-completion) notifications.

These tests drive the real Rust-backed notification store through
``temp_notifications_dir`` so the projection helpers, per-row dismiss
helper, and finalize sync pipeline are exercised end-to-end against
the actual persistence layer rather than mocks.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agents._core import AgentsMixinCore
from sase.ace.tui.actions.agents._loading_finalize import (
    _sync_unread_completed_agents,
)
from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.ace.tui.models.agent import Agent, AgentType
from sase.notifications import (
    Notification,
    append_notification,
    load_notifications,
    mark_dismissed,
    read_notification_snapshot,
)

from ._agent_unread_helpers import make_agent
from tests._agent_cleanup_proc_helpers import TrackedProcRecorderMixin


@pytest.fixture()
def temp_notifications_dir(tmp_path: Path) -> Iterator[Path]:
    """Patch NOTIFICATIONS_DIR/FILE so each test gets an isolated store."""
    notifications_dir = str(tmp_path / "notifications")
    notifications_file = str(tmp_path / "notifications" / "notifications.jsonl")
    with (
        patch("sase.notifications.store.NOTIFICATIONS_DIR", notifications_dir),
        patch("sase.notifications.store.NOTIFICATIONS_FILE", notifications_file),
    ):
        yield tmp_path


def _completion_notification(
    agent: Agent,
    *,
    n_id: str,
    action: str = "JumpToAgent",
    tags: list[str] | None = None,
) -> Notification:
    if tags is None:
        tags = ["done"] if action == "JumpToAgent" else []
    return Notification(
        id=n_id,
        timestamp="2026-05-11T12:00:00-04:00",
        sender="user-agent",
        tags=tags,
        action=action,
        action_data={
            "cl_name": agent.cl_name,
            "raw_suffix": agent.raw_suffix or "",
        },
    )


def _interactive_notification(
    agent: Agent,
    *,
    n_id: str,
    action: str = "PlanApproval",
) -> Notification:
    return Notification(
        id=n_id,
        timestamp="2026-05-11T12:01:00-04:00",
        sender="user-agent",
        action=action,
        action_data={
            "agent_cl_name": agent.cl_name,
            "agent_timestamp": agent.raw_suffix or "",
        },
    )


class _E2EApp(TrackedProcRecorderMixin, AgentsMixinCore):
    """Minimal stand-in app exercising the per-row helpers and finalize sync."""

    def __init__(self, agents: list[Agent]) -> None:
        self._init_tracked_task_recorder()
        self._agents = agents
        self._agents_with_children = list(agents)
        self.current_idx = 0
        self.current_tab = "agents"
        self._current_group_key: tuple[str, ...] | None = None
        self._unread_completed_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._manual_unread_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._dismissed_agents: set[tuple[AgentType, str, str | None]] = set()
        self._dismissed_agent_objects: list[Agent] = []
        self._recent_dismissed_agent_groups = []
        self._revived_agent_raw_suffixes: set[str] = set()
        self._marked_agents: set[tuple[AgentType, str, str | None]] = set()
        self._marked_agent_order: list[tuple[AgentType, str, str | None]] = []
        self._agent_status_overrides: dict[tuple[AgentType, str, str | None], str] = {}
        self._dismiss_persistence_inflight: set[tuple[AgentType, str, str | None]] = (
            set()
        )
        self._agent_display_status_by_identity: dict[
            tuple[AgentType, str, str | None], str
        ] = {}
        self.refresh_count_calls = 0
        self.patch_calls: list[Agent] = []
        self.refresh_calls: list[dict[str, object]] = []
        self.notifications: list[tuple[str, str]] = []
        self.refilter_calls = 0
        self.async_refreshes = 0
        self.notification_refreshes_async = 0
        self._scheduled: list[tuple[object, tuple[object, ...]]] = []

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def call_later(self, callback: object, *args: object) -> None:
        self._scheduled.append((callback, args))

    def call_after_refresh(self, callback: object, *args: object) -> None:
        callback(*args)  # type: ignore[operator]

    def _refresh_notification_count(self) -> None:
        self.refresh_count_calls += 1

    async def _refresh_notification_count_async(self) -> None:
        self.notification_refreshes_async += 1

    def _schedule_agents_async_refresh(self, *, source: str = "unknown") -> None:
        del source
        self.async_refreshes += 1

    def _refilter_agents(self, *, prior_pos: int | None = None) -> None:
        del prior_pos
        self.refilter_calls += 1
        self._agents = list(self._agents_with_children)

    def _try_patch_agent_row(self, agent: Agent) -> bool:
        self.patch_calls.append(agent)
        return True

    def _refresh_agents_display(self, **kwargs: object) -> None:
        self.refresh_calls.append(kwargs)


def _active_completion_ids() -> set[str]:
    """Return ids of completion notifications still active in the store."""
    return {
        n.id
        for n in load_notifications()
        if n.sender == "user-agent" and n.action in ("JumpToAgent", "ViewErrorReport")
    }


def _active_ids() -> set[str]:
    """Return ids of all active notifications still in the store."""
    return {n.id for n in load_notifications()}


def _modal_visible_ids(modal: NotificationModal) -> list[str]:
    """Return notification ids in current modal visual order."""
    ids: list[str] = []
    for option in modal._create_sectioned_options():
        if option.disabled or option.id is None or str(option.id).startswith("hdr:"):
            continue
        ids.append(modal._notifications[int(str(option.id))].id)
    return ids


def _sync_from_store(app: _E2EApp, *, on_agents_tab: bool) -> None:
    """Refresh the notification cache and run the hot-path finalizer sync."""
    app._notification_snapshot_cache = read_notification_snapshot()
    _sync_unread_completed_agents(app, on_agents_tab=on_agents_tab)  # type: ignore[arg-type]


def test_two_completed_agents_with_two_notifications_start_unread(
    temp_notifications_dir: Path,
) -> None:
    """Both completion notifications project onto matching unread rows."""
    assert temp_notifications_dir.is_dir()
    first = make_agent(name="alpha", status="DONE", raw_suffix="20260507090000")
    second = make_agent(name="beta", status="FAILED", raw_suffix="20260507100000")
    app = _E2EApp([first, second])
    append_notification(_completion_notification(first, n_id="n-alpha"))
    append_notification(
        _completion_notification(second, n_id="n-beta", action="ViewErrorReport")
    )

    # Off-tab finalize so neither row is auto-cleared by being the selection.
    _sync_from_store(app, on_agents_tab=False)

    assert app._unread_completed_agent_ids == {first.identity, second.identity}


def test_done_tab_matches_successful_unread_completion_notifications(
    temp_notifications_dir: Path,
) -> None:
    """The done tab contains successful completions that project unread rows."""
    assert temp_notifications_dir.is_dir()
    first = make_agent(name="alpha", status="DONE", raw_suffix="20260507090000")
    second = make_agent(name="beta", status="DONE", raw_suffix="20260507100000")
    failed = make_agent(name="gamma", status="FAILED", raw_suffix="20260507110000")
    app = _E2EApp([first, second, failed])
    append_notification(_completion_notification(first, n_id="n-alpha"))
    append_notification(_completion_notification(second, n_id="n-beta"))
    append_notification(
        _completion_notification(failed, n_id="n-failure", action="ViewErrorReport")
    )

    _sync_from_store(app, on_agents_tab=False)

    assert app._unread_completed_agent_ids == {
        first.identity,
        second.identity,
        failed.identity,
    }
    modal = NotificationModal(load_notifications())
    assert [(tab.tag, tab.count) for tab in modal._tag_tabs()] == [
        ("errors", 1),
        ("done", 2),
    ]
    assert _modal_visible_ids(modal) == ["n-failure"]

    modal._active_notification_tag = "done"
    assert set(_modal_visible_ids(modal)) == {"n-alpha", "n-beta"}
    assert "n-failure" not in _modal_visible_ids(modal)

    modal._active_notification_tag = "errors"
    assert _modal_visible_ids(modal) == ["n-failure"]


def test_acknowledging_done_agent_removes_completion_from_done_not_general_tab(
    temp_notifications_dir: Path,
) -> None:
    """Reading one done row removes only its completion notification."""
    assert temp_notifications_dir.is_dir()
    first = make_agent(name="alpha", status="DONE", raw_suffix="20260507090000")
    second = make_agent(name="beta", status="DONE", raw_suffix="20260507100000")
    app = _E2EApp([first, second])
    append_notification(_completion_notification(first, n_id="n-alpha"))
    append_notification(_completion_notification(second, n_id="n-beta"))
    append_notification(
        Notification(
            id="n-plan",
            timestamp="2026-05-11T12:01:00-04:00",
            sender="plan",
            action="PlanApproval",
            action_data={
                "agent_cl_name": first.cl_name,
                "agent_timestamp": first.raw_suffix or "",
            },
        )
    )
    _sync_from_store(app, on_agents_tab=False)
    assert app._unread_completed_agent_ids == {first.identity, second.identity}

    modal = NotificationModal(load_notifications())
    assert _modal_visible_ids(modal) == ["n-plan"]
    modal._active_notification_tag = "done"
    assert set(_modal_visible_ids(modal)) == {"n-alpha", "n-beta"}

    assert app._clear_agent_unread_and_dismiss_notification(first)

    modal = NotificationModal(load_notifications())
    assert _modal_visible_ids(modal) == ["n-plan"]
    modal._active_notification_tag = "done"
    assert _modal_visible_ids(modal) == ["n-beta"]
    assert app._unread_completed_agent_ids == {second.identity}
    assert app.refresh_count_calls == 1


def test_reading_one_agent_dismisses_only_its_notification(
    temp_notifications_dir: Path,
) -> None:
    """The per-row helper dismisses exactly one notification and clears one row."""
    assert temp_notifications_dir.is_dir()
    first = make_agent(name="alpha", status="DONE", raw_suffix="20260507090000")
    second = make_agent(name="beta", status="DONE", raw_suffix="20260507100000")
    app = _E2EApp([first, second])
    append_notification(_completion_notification(first, n_id="n-alpha"))
    append_notification(_completion_notification(second, n_id="n-beta"))
    _sync_from_store(app, on_agents_tab=False)
    assert app._unread_completed_agent_ids == {first.identity, second.identity}

    assert app._clear_agent_unread_and_dismiss_notification(first)

    assert app._unread_completed_agent_ids == {second.identity}
    assert _active_completion_ids() == {"n-beta"}
    assert app.refresh_count_calls == 1


def test_dismissing_single_agent_removes_only_its_completion_notification(
    temp_notifications_dir: Path,
) -> None:
    """Dismissing one row clears only its completion notification immediately."""
    assert temp_notifications_dir.is_dir()
    first = make_agent(name="alpha", status="DONE", raw_suffix="20260507090000")
    second = make_agent(name="beta", status="DONE", raw_suffix="20260507100000")
    app = _E2EApp([first, second])
    append_notification(_completion_notification(first, n_id="n-alpha"))
    append_notification(_completion_notification(second, n_id="n-beta"))
    append_notification(_interactive_notification(first, n_id="n-plan"))
    append_notification(
        _interactive_notification(second, n_id="n-question", action="UserQuestion")
    )
    _sync_from_store(app, on_agents_tab=False)
    assert app._unread_completed_agent_ids == {first.identity, second.identity}

    app._dismiss_done_agent(first)

    assert app._unread_completed_agent_ids == {second.identity}
    assert _active_completion_ids() == {"n-beta"}
    assert {"n-plan", "n-question"}.issubset(_active_ids())
    assert app.refresh_count_calls == 1


def test_bulk_dismiss_all_done_removes_completion_notifications(
    temp_notifications_dir: Path,
) -> None:
    """Bulk dismiss clears every selected row's completion notification."""
    assert temp_notifications_dir.is_dir()
    first = make_agent(name="alpha", status="DONE", raw_suffix="20260507090000")
    second = make_agent(name="beta", status="FAILED", raw_suffix="20260507100000")
    app = _E2EApp([first, second])
    append_notification(_completion_notification(first, n_id="n-alpha"))
    append_notification(
        _completion_notification(second, n_id="n-beta", action="ViewErrorReport")
    )
    _sync_from_store(app, on_agents_tab=False)
    assert app._unread_completed_agent_ids == {first.identity, second.identity}

    app._do_dismiss_all([first, second])

    assert app._unread_completed_agent_ids == set()
    assert _active_completion_ids() == set()
    assert app.refresh_count_calls == 1


def test_marked_group_save_dismiss_removes_completion_not_interactive_notifications(
    temp_notifications_dir: Path,
) -> None:
    """Save-and-dismiss clears completions while preserving HITL notifications."""
    assert temp_notifications_dir.is_dir()
    first = make_agent(name="alpha", status="DONE", raw_suffix="20260507090000")
    second = make_agent(name="beta", status="DONE", raw_suffix="20260507100000")
    app = _E2EApp([first, second])
    app._marked_agents = {first.identity, second.identity}
    append_notification(_completion_notification(first, n_id="n-alpha"))
    append_notification(_completion_notification(second, n_id="n-beta"))
    append_notification(_interactive_notification(first, n_id="n-plan"))
    append_notification(
        _interactive_notification(second, n_id="n-question", action="UserQuestion")
    )
    _sync_from_store(app, on_agents_tab=False)

    app._save_marked_agent_group(group_name="done batch")

    assert app._unread_completed_agent_ids == set()
    assert _active_completion_ids() == set()
    assert {"n-plan", "n-question"}.issubset(_active_ids())
    assert app._marked_agents == set()
    assert app.refresh_count_calls == 1


def test_dismiss_agent_raw_suffix_disambiguates_same_cl_name(
    temp_notifications_dir: Path,
) -> None:
    """Dismissing one run leaves a same-cl_name run's notification active."""
    assert temp_notifications_dir.is_dir()
    first_run = make_agent(name="alpha", status="DONE", raw_suffix="20260507090000")
    second_run = make_agent(name="alpha", status="DONE", raw_suffix="20260507100000")
    app = _E2EApp([first_run, second_run])
    append_notification(_completion_notification(first_run, n_id="n-first"))
    append_notification(_completion_notification(second_run, n_id="n-second"))
    _sync_from_store(app, on_agents_tab=False)

    app._dismiss_done_agent(second_run)

    assert app._unread_completed_agent_ids == {first_run.identity}
    assert _active_completion_ids() == {"n-first"}
    assert app.refresh_count_calls == 1


def test_dismiss_workflow_parent_removes_child_completion_notifications(
    temp_notifications_dir: Path,
) -> None:
    """Dismissing a workflow parent also clears child completion notifications."""
    assert temp_notifications_dir.is_dir()
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="workflow-cl",
        project_file="/tmp/projects/demo/demo.sase",
        status="DONE",
        start_time=None,
        raw_suffix="20260507090000",
        workflow="wf",
    )
    child = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="workflow-cl",
        project_file="/tmp/projects/demo/demo.sase",
        status="DONE",
        start_time=None,
        raw_suffix="20260507090100",
        parent_workflow="wf",
        parent_timestamp="20260507090000",
    )
    app = _E2EApp([parent, child])
    append_notification(_completion_notification(parent, n_id="n-parent"))
    append_notification(_completion_notification(child, n_id="n-child"))
    _sync_from_store(app, on_agents_tab=False)
    assert app._unread_completed_agent_ids == {parent.identity}

    app._dismiss_done_agent(parent)

    assert app._unread_completed_agent_ids == set()
    assert _active_completion_ids() == set()
    assert app.refresh_count_calls == 1


def test_dismissing_notification_clears_other_row_on_refresh(
    temp_notifications_dir: Path,
) -> None:
    """A notification dismissed via the API clears its row on next reconcile."""
    assert temp_notifications_dir.is_dir()
    first = make_agent(name="alpha", status="DONE", raw_suffix="20260507090000")
    second = make_agent(name="beta", status="DONE", raw_suffix="20260507100000")
    app = _E2EApp([first, second])
    append_notification(_completion_notification(first, n_id="n-alpha"))
    append_notification(_completion_notification(second, n_id="n-beta"))
    _sync_from_store(app, on_agents_tab=False)
    assert app._unread_completed_agent_ids == {first.identity, second.identity}

    # Dismiss the beta notification directly via the notification API
    # (mirrors the user dismissing it from the notification modal).
    assert mark_dismissed("n-beta")

    _sync_from_store(app, on_agents_tab=False)

    assert app._unread_completed_agent_ids == {first.identity}
    assert _active_completion_ids() == {"n-alpha"}


def test_entering_agents_tab_does_not_dismiss_selected_row(
    temp_notifications_dir: Path,
) -> None:
    """The finalize sync does not treat the selected row as read.

    Landing on the Agents tab must not silently dismiss active completion
    notifications. A focused unread row is acknowledged only when the user
    intentionally selects/navigates into that row again.
    """
    assert temp_notifications_dir.is_dir()
    first = make_agent(name="alpha", status="DONE", raw_suffix="20260507090000")
    second = make_agent(name="beta", status="DONE", raw_suffix="20260507100000")
    third = make_agent(name="gamma", status="DONE", raw_suffix="20260507110000")
    app = _E2EApp([first, second, third])
    app.current_idx = 0  # alpha is the selected row.
    append_notification(_completion_notification(first, n_id="n-alpha"))
    append_notification(_completion_notification(second, n_id="n-beta"))
    append_notification(_completion_notification(third, n_id="n-gamma"))

    # Seed the unread set the way a prior refresh tick would: every
    # completion notification has projected onto its row.
    app._unread_completed_agent_ids = {
        first.identity,
        second.identity,
        third.identity,
    }

    _sync_from_store(app, on_agents_tab=True)

    assert app._unread_completed_agent_ids == {
        first.identity,
        second.identity,
        third.identity,
    }
    assert _active_completion_ids() == {"n-alpha", "n-beta", "n-gamma"}


def test_navigating_within_agents_tab_does_not_bulk_dismiss(
    temp_notifications_dir: Path,
) -> None:
    """Repeated finalize ticks must not drain unrelated completion rows."""
    assert temp_notifications_dir.is_dir()
    selected = make_agent(name="focused", status="RUNNING", raw_suffix="focused")
    first = make_agent(name="alpha", status="DONE", raw_suffix="20260507090000")
    second = make_agent(name="beta", status="DONE", raw_suffix="20260507100000")
    app = _E2EApp([selected, first, second])
    app.current_idx = 0  # focus a still-running agent → no row to ack.
    append_notification(_completion_notification(first, n_id="n-alpha"))
    append_notification(_completion_notification(second, n_id="n-beta"))

    # Multiple finalize ticks (e.g. j/k navigation auto-refresh) must not
    # ever dismiss a notification whose row is not focused.
    for _ in range(3):
        _sync_from_store(app, on_agents_tab=True)

    assert app._unread_completed_agent_ids == {first.identity, second.identity}
    assert _active_completion_ids() == {"n-alpha", "n-beta"}


def test_unrelated_notifications_survive_agents_tab_activity(
    temp_notifications_dir: Path,
) -> None:
    """Unrelated plan/question/mentor/axe rows are untouched by finalize sync."""
    assert temp_notifications_dir.is_dir()
    agent = make_agent(name="alpha", status="DONE", raw_suffix="20260507090000")
    app = _E2EApp([agent])
    app.current_idx = 0
    append_notification(_completion_notification(agent, n_id="n-completion"))

    # Notifications for OTHER agents and from non-agent senders — none of
    # these should be touched when we ack alpha's completion row.
    append_notification(
        Notification(
            id="n-plan",
            timestamp="2026-05-11T12:01:00-04:00",
            sender="user-agent",
            action="PlanApproval",
            action_data={"agent_cl_name": "other"},
        )
    )
    append_notification(
        Notification(
            id="n-question",
            timestamp="2026-05-11T12:02:00-04:00",
            sender="user-agent",
            action="UserQuestion",
            action_data={"agent_cl_name": "other"},
        )
    )
    append_notification(
        Notification(
            id="n-mentor",
            timestamp="2026-05-11T12:03:00-04:00",
            sender="mentors",
            action="JumpToMentorReview",
            action_data={"cl_name": agent.cl_name},
        )
    )
    append_notification(
        Notification(
            id="n-axe",
            timestamp="2026-05-11T12:04:00-04:00",
            sender="axe",
            action="ViewErrorReport",
            action_data={"chop_id": "c1"},
        )
    )
    app._unread_completed_agent_ids = {agent.identity}

    _sync_from_store(app, on_agents_tab=True)

    # Finalize does not acknowledge the focused completion row. All
    # notifications must remain in the store.
    active_ids = {n.id for n in load_notifications()}
    assert active_ids == {
        "n-completion",
        "n-plan",
        "n-question",
        "n-mentor",
        "n-axe",
    }


def test_raw_suffix_disambiguates_same_cl_name(
    temp_notifications_dir: Path,
) -> None:
    """Two runs of the same agent get one-to-one mapping by raw_suffix."""
    assert temp_notifications_dir.is_dir()
    first_run = make_agent(name="alpha", status="DONE", raw_suffix="20260507090000")
    second_run = make_agent(name="alpha", status="DONE", raw_suffix="20260507100000")
    app = _E2EApp([first_run, second_run])
    append_notification(_completion_notification(first_run, n_id="n-first"))
    append_notification(_completion_notification(second_run, n_id="n-second"))
    _sync_from_store(app, on_agents_tab=False)
    assert app._unread_completed_agent_ids == {first_run.identity, second_run.identity}

    assert app._clear_agent_unread_and_dismiss_notification(second_run)

    assert app._unread_completed_agent_ids == {first_run.identity}
    assert _active_completion_ids() == {"n-first"}


def test_large_roster_completion_schedules_exact_delta_not_broad(
    temp_notifications_dir: Path,
    tmp_path: Path,
) -> None:
    """A one-agent completion stays a bounded delta against a large roster.

    Structural regression for the diagnosed incident: a real, ~500-row
    roster with the completed agent folded/filtered out of the visible
    ``_agents`` projection must still resolve through the complete
    ``_agents_with_children`` roster to exactly one exact artifact delta,
    never a broad ``request_agents_refresh`` fallback.
    """
    from sase.ace.tui.actions.agents._notification_utils import (
        request_notification_agents_refresh,
    )

    assert temp_notifications_dir.is_dir()

    bulk_roster = [
        make_agent(
            name=f"bulk-{i}",
            status="RUNNING",
            raw_suffix=f"202605{(i % 27) + 1:02d}090000",
        )
        for i in range(500)
    ]
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    target = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="folded-target",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=make_agent().start_time,
        raw_suffix="20260722090000",
        artifacts_dir=str(artifacts_dir),
    )

    app = _E2EApp(bulk_roster)
    # The visible/filtered projection only shows the bulk roster (as if a
    # search query or fold hid the target); the complete loaded roster
    # still has it.
    app._agents_with_children = [*bulk_roster, target]
    append_notification(_completion_notification(target, n_id="n-folded-target"))
    app._notification_snapshot_cache = read_notification_snapshot()

    scheduled: list[tuple[tuple[Path, ...], str]] = []
    broad: list[tuple[str, bool]] = []
    app._schedule_agent_artifact_delta_refresh = (  # type: ignore[attr-defined]
        lambda dirs, *, source: scheduled.append((tuple(dirs), source))
    )
    app.request_agents_refresh = (  # type: ignore[attr-defined]
        lambda source, *, latest_only: broad.append((source, latest_only))
    )

    request_notification_agents_refresh(app)

    assert scheduled == [((artifacts_dir,), "notification")]
    assert broad == []
