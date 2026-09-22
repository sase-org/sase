"""Regression coverage for unread notification backlogs beyond 100 rows."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.binding import Binding

from sase.ace.tui.actions.agents._agent_enter_action import AgentEnterActionMixin
from sase.ace.tui.actions.agents._notification_modal_flow import (
    AgentNotificationModalMixin,
)
from sase.ace.tui.actions.agents._notification_provider import (
    AgentNotificationProviderMixin,
    _read_unread_notification_page_for_tui,
)
from sase.ace.tui.actions.agents._notification_provider_direct import (
    direct_unread_notification_page,
    notification_snapshot_from_direct,
)
from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.ace.tui.modals.notification_modal_tags import GATES_TAB_KEY
from sase.ace.tui.models.agent import Agent
from sase.notifications import Notification
from sase.notifications.store import append_notification, read_notification_snapshot

from ._agent_unread_helpers import make_agent


@pytest.fixture()
def notification_home(tmp_path, monkeypatch: pytest.MonkeyPatch):
    from sase.notification_gates import paths
    from sase.notifications import pending_actions, store

    notifications_dir = tmp_path / "notifications"
    monkeypatch.setattr(paths, "INTERACTION_REQUESTS_DIR", tmp_path / "requests")
    monkeypatch.setattr(store, "NOTIFICATIONS_DIR", str(notifications_dir))
    monkeypatch.setattr(
        store,
        "NOTIFICATIONS_FILE",
        str(notifications_dir / "notifications.jsonl"),
    )
    monkeypatch.setattr(
        pending_actions, "PENDING_ACTIONS_PATH", tmp_path / "pending.json"
    )
    monkeypatch.setattr(
        pending_actions,
        "LEGACY_TELEGRAM_PENDING_ACTIONS_PATH",
        tmp_path / "legacy.json",
    )
    store._LOAD_CACHE.clear()
    return tmp_path


def _timestamp(offset: int) -> str:
    return (
        datetime(2026, 9, 18, 12, 0, tzinfo=UTC) + timedelta(seconds=offset)
    ).isoformat()


def _notification(
    notification_id: str,
    *,
    offset: int,
    action: str | None = None,
    sender: str = "test",
    tags: list[str] | None = None,
    action_data: dict[str, str] | None = None,
    read: bool = False,
    dismissed: bool = False,
    silent: bool = False,
    muted: bool = False,
    snooze_until: str | None = None,
) -> Notification:
    return Notification(
        id=notification_id,
        timestamp=_timestamp(offset),
        sender=sender,
        action=action,
        tags=list(tags or []),
        action_data=dict(action_data or {}),
        read=read,
        dismissed=dismissed,
        silent=silent,
        muted=muted,
        snooze_until=snooze_until,
    )


def _append_notifications(notifications: list[Notification]) -> None:
    for notification in notifications:
        append_notification(notification)


def _eligible_ids(*, include_dismissed: bool = False) -> list[str]:
    snapshot = notification_snapshot_from_direct(
        read_notification_snapshot(include_dismissed=include_dismissed)
    )
    return [
        n.id
        for n in snapshot.notifications
        if not n.read and not n.silent and (include_dismissed or not n.dismissed)
    ]


def _assert_page(
    page: Any,
    expected_ids: list[str],
    *,
    bounded: bool,
    truncated: bool,
    include_dismissed: bool = False,
) -> None:
    ids = [notification.id for notification in page.notifications]
    assert ids == expected_ids
    assert page.next_cursor is None
    assert page.bounded is bounded
    assert page.truncated is truncated
    assert page.shared_snapshot is not None
    assert page.shared_snapshot.rows == page.notifications
    assert [
        handle.local_identity for handle in page.shared_snapshot.row_handles
    ] == expected_ids
    assert page.shared_snapshot.metadata["bounded"] is bounded
    assert page.shared_snapshot.metadata["truncated"] is truncated

    snapshot = notification_snapshot_from_direct(
        read_notification_snapshot(include_dismissed=include_dismissed)
    )
    assert page.counts == snapshot.counts


class _ProviderApp(AgentNotificationProviderMixin):
    pass


def test_default_unread_reads_return_complete_backlog(notification_home) -> None:
    del notification_home
    notifications = [
        _notification(f"done-{index}", offset=300 + index, tags=["done"])
        for index in range(250)
    ]
    notifications.extend(
        [
            _notification("old-gate", offset=1, action="PlanApproval"),
            _notification("old-custom", offset=2, tags=["ops"]),
        ]
    )
    _append_notifications(notifications)

    expected_ids = _eligible_ids()

    pages = [
        direct_unread_notification_page(include_dismissed=False),
        _read_unread_notification_page_for_tui(include_dismissed=False).value,
        _ProviderApp()._read_unread_notification_page_from_provider(),
    ]

    assert len(expected_ids) == 252
    assert "old-gate" in expected_ids
    assert "old-custom" in expected_ids
    for page in pages:
        _assert_page(page, expected_ids, bounded=False, truncated=False)


def test_empty_and_filtering_semantics(notification_home) -> None:
    del notification_home
    empty = direct_unread_notification_page(include_dismissed=False)
    _assert_page(empty, [], bounded=False, truncated=False)

    snooze = _timestamp(10_000)
    _append_notifications(
        [
            _notification("visible", offset=1),
            _notification("muted", offset=2, muted=True),
            _notification("snoozed", offset=3, muted=True, snooze_until=snooze),
            _notification("read", offset=4, read=True),
            _notification("silent", offset=5, silent=True),
            _notification("dismissed", offset=6, dismissed=True),
        ]
    )

    expected = _eligible_ids()
    page = direct_unread_notification_page(include_dismissed=False)
    _assert_page(page, expected, bounded=False, truncated=False)
    assert set(expected) == {"visible", "muted", "snoozed"}

    expected_with_dismissed = _eligible_ids(include_dismissed=True)
    included = _read_unread_notification_page_for_tui(
        include_dismissed=True,
        limit=None,
    ).value
    _assert_page(
        included,
        expected_with_dismissed,
        bounded=False,
        truncated=False,
        include_dismissed=True,
    )
    assert "dismissed" in expected_with_dismissed


@pytest.mark.parametrize("reader", ["direct", "wrapper", "mixin"])
@pytest.mark.parametrize(
    ("limit", "expected_count", "bounded", "truncated"),
    [
        (None, 8, False, False),
        (0, 0, True, True),
        (-1, 0, True, True),
        (3, 3, True, True),
        (8, 8, True, False),
        (20, 8, True, False),
    ],
)
def test_explicit_limit_metadata_is_truthful(
    notification_home,
    reader: str,
    limit: int | None,
    expected_count: int,
    bounded: bool,
    truncated: bool,
) -> None:
    del notification_home
    _append_notifications(
        [_notification(f"n-{index}", offset=index) for index in range(8)]
    )
    expected_ids = _eligible_ids()[:expected_count]

    if reader == "direct":
        page = direct_unread_notification_page(
            include_dismissed=False,
            limit=limit,
        )
    elif reader == "wrapper":
        page = _read_unread_notification_page_for_tui(
            include_dismissed=False,
            limit=limit,
        ).value
    else:
        page = _ProviderApp()._read_unread_notification_page_from_provider(limit=limit)

    _assert_page(page, expected_ids, bounded=bounded, truncated=truncated)


class _ModalApp(AgentNotificationModalMixin, AgentNotificationProviderMixin):
    def __init__(self) -> None:
        self.pushed_screens: list[Any] = []
        self.refresh_count = 0
        self._notification_section_modes = None

    def push_screen(self, screen: Any, callback: Any = None) -> None:
        del callback
        self.pushed_screens.append(screen)

    def _refresh_notification_count(self) -> None:
        self.refresh_count += 1


def test_notification_modal_gets_complete_tabs_beyond_indicator_budget(
    notification_home,
) -> None:
    del notification_home
    _append_notifications(
        [
            *[
                _notification(f"done-{index}", offset=200 + index, tags=["done"])
                for index in range(105)
            ],
            _notification("old-gate", offset=1, action="PlanApproval"),
            _notification("old-custom", offset=2, tags=["ops"]),
            _notification(
                "old-error", offset=3, action="ViewErrorReport", sender="axe"
            ),
            _notification("old-general", offset=4),
            _notification("old-muted", offset=5, muted=True),
        ]
    )
    app = _ModalApp()

    app._show_notification_modal()

    [modal] = app.pushed_screens
    assert isinstance(modal, NotificationModal)
    tabs = modal._tag_tabs()
    labels = {tab.label: tab for tab in tabs}
    assert len(tabs) > 4
    assert labels["Gates"].count == 1
    assert labels["Ops"].count == 1
    assert labels["Done"].count == 105

    modal._active_notification_tag = GATES_TAB_KEY
    assert [notification.id for _, notification in modal._active_tab_rows()] == [
        "old-gate"
    ]
    modal._active_notification_tag = "ops"
    assert [notification.id for _, notification in modal._active_tab_rows()] == [
        "old-custom"
    ]


def _matching_action_data(agent: Agent) -> dict[str, str]:
    assert agent.raw_suffix is not None
    return {
        "agent_cl_name": agent.cl_name,
        "agent_name": agent.agent_name or agent.cl_name,
        "agent_timestamp": agent.raw_suffix,
        "agent_root_timestamp": "20260101010101",
    }


class _EnterKeypressApp(
    App[None],
    AgentEnterActionMixin,
    AgentNotificationProviderMixin,
):
    """Minimal Textual app proving Enter opens a backlog gate notification."""

    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [Binding("enter", "act_on_agent", show=False)]

    def __init__(self, agent: Agent, notifications: list[Notification]) -> None:
        super().__init__()
        self._agents = [agent]
        self._agents_with_children = [agent]
        self.current_idx = 0
        self.current_tab = "agents"
        self._current_group_key = None
        self._notification_snapshot_cache: Any = SimpleNamespace(
            notifications=list(notifications)
        )
        self.patches: list[Any] = []
        self.refreshes = 0

    def compose(self) -> ComposeResult:
        from sase.ace.tui.widgets.agent_list import AgentList

        yield AgentList(id="agent-list")

    def on_mount(self) -> None:
        from sase.ace.tui.widgets.agent_list import AgentList

        agent_list = self.query_one(AgentList)
        agent_list.update_list(list(self._agents), current_idx=0)
        agent_list.focus()

    def _get_selected_agent(self) -> Agent | None:
        return self._agents[self.current_idx] if self._agents else None

    def _resolve_agent_cl_name(self, agent: Agent) -> str | None:
        # Gate-only for this backlog test: suppress the Patch target.
        del agent
        return None

    def _agent_by_identity(self, identity: tuple[object, ...]) -> Agent | None:
        for agent in self._agents:
            if agent.identity == identity:
                return agent
        return None

    def _open_question_modal_from_marker(self, agent: Agent) -> bool:
        del agent
        return False

    def _answer_workflow_hitl(self, agent: Agent) -> None:
        del agent

    def _answer_remote_attention_for(self, agent: Any) -> None:
        del agent

    def _schedule_notification_snapshot_refresh(self) -> None:
        self.refreshes += 1

    def _read_notification_pending_actions_from_provider(self) -> object:
        return object()


async def test_enter_keypress_dispatches_backlog_notification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = replace(
        make_agent(name="target", status="PLAN", raw_suffix="20260918010101"),
        agent_name="target-agent",
    )
    notifications = [
        *[
            _notification(f"newer-{index}", offset=500 + index, tags=["done"])
            for index in range(120)
        ],
        _notification(
            "old-match",
            offset=1,
            action="PlanApproval",
            action_data=_matching_action_data(agent),
        ),
    ]
    dispatched: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_actions.handle_plan_approval",
        lambda _app, notification: dispatched.append(notification.id),
    )

    async with _EnterKeypressApp(agent, notifications).run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

    assert dispatched == ["old-match"]
