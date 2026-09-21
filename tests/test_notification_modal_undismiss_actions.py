"""Production-path coverage for the notification dismissed view and undismiss."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.ace.tui.actions.agents._notification_modal_flow import (
    AgentNotificationModalMixin,
)
from sase.ace.tui.actions.agents._notification_provider import (
    AgentNotificationProviderMixin,
)
from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.ace.tui.modals.notification_modal_constants import (
    DEFAULT_HINT_TEXT,
    GATE_HINT_TEXT,
    NOTIFICATION_HINT_FALLBACK_WIDTH,
    QUESTION_HINT_TEXT,
    notification_hint_text,
)
from sase.notifications import Notification
from sase.notifications.store import (
    append_notification,
    load_notifications,
    mark_dismissed,
)


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
) -> Notification:
    return Notification(
        id=notification_id,
        timestamp=_timestamp(offset),
        sender="test",
        action=action,
        tags=[],
        action_data={},
    )


def _seed_inbox_with_dismissed_gate() -> Notification:
    """Seed one inbox row plus a dismissed, still-unread live CustomGate row."""
    append_notification(_notification("n-inbox", offset=1))
    gate = _notification("gate-1", offset=2, action="CustomGate")
    append_notification(gate)
    # Production dismisses protected gates without marking them read, so the
    # row stays unread and (before this phase) unreachable from the modal.
    assert mark_dismissed("gate-1") is True
    return gate


class _ModalApp(AgentNotificationModalMixin, AgentNotificationProviderMixin):
    """Minimal app double that opens the modal through the real flow."""

    def __init__(self) -> None:
        self.pushed: list[tuple[Any, Any]] = []
        self.refresh_count = 0
        self.pending_reads = 0
        self._notification_section_modes = None

    def push_screen(self, screen: Any, callback: Any = None) -> None:
        self.pushed.append((screen, callback))

    def _refresh_notification_count(self) -> None:
        self.refresh_count += 1

    def _read_notification_pending_actions_from_provider(self) -> object:
        self.pending_reads += 1
        return object()


class _FakeOptionList:
    """Selectable-row double that rebuilds along with the modal dataset."""

    def __init__(self, options: list[Any]) -> None:
        self.options = list(options)
        self.highlighted: int | None = None

    @property
    def option_count(self) -> int:
        return len(self.options)

    def get_option_at_index(self, row: int) -> Any:
        return self.options[row]

    def clear_options(self) -> None:
        self.options.clear()

    def add_option(self, option: Any) -> None:
        self.options.append(option)

    def add_class(self, _class_name: str) -> None:
        return

    def remove_class(self, _class_name: str) -> None:
        return


def _wire_modal(modal: NotificationModal) -> SimpleNamespace:
    """Serve the modal's widget queries without mounting it."""
    option_list = _FakeOptionList(modal._create_sectioned_options())
    titles: list[str] = []

    class _Title:
        def update(self, text: object) -> None:
            titles.append(str(text))

    mounted: list[Any] = []

    class _Left:
        def mount(self, widget: Any) -> None:
            mounted.append(widget)

    def query_one(selector: str, *_args: Any, **_kwargs: Any) -> Any:
        if selector == "#notification-list":
            return option_list
        if selector == "#notification-title":
            return _Title()
        if selector == "#notification-left":
            return _Left()
        raise LookupError(selector)

    modal.query_one = MagicMock(side_effect=query_one)  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]
    modal._display_file = MagicMock()  # type: ignore[method-assign]
    return SimpleNamespace(option_list=option_list, titles=titles, mounted=mounted)


def _open_modal(app: _ModalApp) -> tuple[NotificationModal, Any, SimpleNamespace]:
    app._show_notification_modal()
    [(modal, callback)] = app.pushed
    assert isinstance(modal, NotificationModal)
    wired = _wire_modal(modal)
    return modal, callback, wired


def _modal_ids(modal: NotificationModal) -> list[str]:
    return [notification.id for notification in modal._notifications]


def _highlight_first_visible(modal: NotificationModal, wired: SimpleNamespace) -> None:
    first = modal._first_visible_notification_index()
    assert first is not None
    wired.option_list.highlighted = modal._row_for_notification_index(
        wired.option_list, first
    )


def test_normal_inbox_hides_dismissed_gate(notification_home) -> None:
    """The real app flow lists only non-dismissed rows in the normal inbox."""
    del notification_home
    _seed_inbox_with_dismissed_gate()
    modal, _callback, _wired = _open_modal(_ModalApp())

    assert _modal_ids(modal) == ["n-inbox"]


def test_dismissed_view_toggle_loads_dismissed_rows(notification_home) -> None:
    """T switches to a dismissed-only view and back to the normal inbox."""
    del notification_home
    _seed_inbox_with_dismissed_gate()
    modal, _callback, wired = _open_modal(_ModalApp())

    modal.action_toggle_dismissed_view()

    assert modal._showing_dismissed is True
    assert _modal_ids(modal) == ["gate-1"]
    assert wired.titles[-1] == "Notifications (dismissed)"
    modal.notify.assert_called_with("Showing dismissed notifications (T to return)")

    modal.action_toggle_dismissed_view()

    assert modal._showing_dismissed is False
    assert _modal_ids(modal) == ["n-inbox"]
    assert wired.titles[-1] == "Notifications"
    modal.notify.assert_called_with("Showing unread notifications")


def test_empty_dismissed_view_reports_no_dismissed_rows(notification_home) -> None:
    """Toggling with nothing dismissed shows the dismissed empty state."""
    del notification_home
    append_notification(_notification("n-inbox", offset=1))
    modal, _callback, wired = _open_modal(_ModalApp())

    modal.action_toggle_dismissed_view()

    assert modal._showing_dismissed is True
    assert modal._notifications == []
    assert wired.titles[-1] == "Notifications (dismissed)"
    assert len(wired.mounted) == 1


def test_undismiss_from_dismissed_view_restores_store_row(
    notification_home,
) -> None:
    """u in the dismissed view clears the store's dismissed flag."""
    del notification_home
    _seed_inbox_with_dismissed_gate()
    modal, _callback, wired = _open_modal(_ModalApp())
    modal.action_toggle_dismissed_view()
    _highlight_first_visible(modal, wired)

    modal.action_undismiss_notification()

    rows = {n.id: n for n in load_notifications(include_dismissed=True)}
    assert rows["gate-1"].dismissed is False
    assert rows["gate-1"].read is False
    modal.notify.assert_called_with("Undismissed 1 notification")


def test_restored_gate_returns_to_inbox_and_reaches_handler(
    notification_home, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After u + T, the live gate is listed and Enter reaches its handler."""
    del notification_home
    # Patched before the modal opens: _show_notification_modal binds the
    # gate handler into its dismiss callback at open time.
    dispatched: list[Notification] = []
    marked_read: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_actions.handle_custom_gate",
        lambda _app, selected: dispatched.append(selected),
    )
    monkeypatch.setattr(
        "sase.notifications.mark_read",
        lambda notification_id: marked_read.append(notification_id),
    )
    _seed_inbox_with_dismissed_gate()
    app = _ModalApp()
    modal, callback, wired = _open_modal(app)
    modal.action_toggle_dismissed_view()
    _highlight_first_visible(modal, wired)
    modal.action_undismiss_notification()

    modal.action_toggle_dismissed_view()

    assert "gate-1" in _modal_ids(modal)
    notification = next(n for n in modal._notifications if n.id == "gate-1")

    callback(notification)

    assert [n.id for n in dispatched] == ["gate-1"]
    assert marked_read == []
    assert app.pending_reads == 1
    assert app.refresh_count == 1


def test_undismiss_with_marks_restores_every_marked_row(
    notification_home,
) -> None:
    """u with marks bulk-restores every marked dismissed row."""
    del notification_home
    append_notification(_notification("gate-1", offset=1, action="CustomGate"))
    append_notification(_notification("gate-2", offset=2, action="CustomGate"))
    assert mark_dismissed("gate-1") is True
    assert mark_dismissed("gate-2") is True
    modal, _callback, wired = _open_modal(_ModalApp())
    modal.action_toggle_dismissed_view()
    modal._marked_notification_ids = {"gate-1", "gate-2"}
    _highlight_first_visible(modal, wired)

    modal.action_undismiss_notification()

    rows = {n.id: n for n in load_notifications(include_dismissed=True)}
    assert rows["gate-1"].dismissed is False
    assert rows["gate-2"].dismissed is False
    assert modal._marked_notification_ids == set()
    modal.notify.assert_called_with("Undismissed 2 notifications")


def test_undismiss_failure_surfaces_error_and_keeps_flag(
    notification_home, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed undismiss task surfaces the error and keeps the row dismissed."""
    del notification_home
    _seed_inbox_with_dismissed_gate()
    modal, _callback, wired = _open_modal(_ModalApp())
    modal.action_toggle_dismissed_view()
    _highlight_first_visible(modal, wired)

    def _boom(*args: object, **kwargs: object) -> int:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "sase.notifications.store.mark_many_undismissed",
        _boom,
    )

    modal.action_undismiss_notification()

    rows = {n.id: n for n in load_notifications(include_dismissed=True)}
    assert rows["gate-1"].dismissed is True
    modal.notify.assert_called_with(
        "Could not undismiss notifications: boom", severity="error"
    )


def test_toggle_binding_and_footer_advertise_dismissed_view() -> None:
    """T toggles the view without clashing, and every footer lists both keys."""
    assert ("T", "toggle_dismissed_view", "Dismissed") in NotificationModal.BINDINGS
    bound_keys = {
        binding[0]
        for binding in NotificationModal.BINDINGS
        if isinstance(binding, tuple)
    }
    assert "t" not in bound_keys
    for text in (DEFAULT_HINT_TEXT, QUESTION_HINT_TEXT, GATE_HINT_TEXT):
        assert "T: dismissed" in text
        assert "u: undismiss" in text
    for variant in ("default", "question", "gate"):
        text = notification_hint_text(variant, NOTIFICATION_HINT_FALLBACK_WIDTH)
        assert "T: dismissed" in text
        assert "u: undismiss" in text
        assert "+: +1" in text
        assert "q: close" in text
