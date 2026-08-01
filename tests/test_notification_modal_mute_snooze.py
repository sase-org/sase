"""Tests for NotificationModal mute, label, and snooze actions."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from sase.ace.tui.modals.notification_modal_actions import (
    _NotificationMutationResult,
    _resolve_snooze_deadline,
)
from sase.core.time import get_timezone
from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.ace.tui.modals.notification_modal_tags import MUTED_TAB_KEY

from tests._notification_modal_helpers import _make_notification


def test_toggle_mute_sets_muted_and_rebuilds() -> None:
    """m should toggle mute state, persist via mark_muted, and rebuild."""
    notification = _make_notification("n1", action="JumpToAgent")
    modal = NotificationModal([notification])
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch("sase.ace.tui.modals.notification_modal.mark_muted") as mock_mark:
        modal.action_toggle_mute()

    mock_mark.assert_called_once_with("n1", True)
    assert notification.muted is True
    assert modal._active_notification_tag == MUTED_TAB_KEY
    modal._rebuild_list.assert_called_once_with(highlight_index=0)
    modal.notify.assert_called_once_with("Muted")


def test_toggle_mute_unmutes_when_already_muted() -> None:
    """m on an already-muted notification flips it back to unmuted."""
    notification = _make_notification("n1", action="JumpToAgent")
    notification.muted = True
    modal = NotificationModal([notification])
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch("sase.ace.tui.modals.notification_modal.mark_muted") as mock_mark:
        modal.action_toggle_mute()

    mock_mark.assert_called_once_with("n1", False)
    assert notification.muted is False
    assert modal._active_notification_tag is None
    modal.notify.assert_called_once_with("Unmuted")


def test_toggle_mute_moves_row_to_muted_tab_and_highlights_replacement() -> None:
    """Muting a row in a still-populated tab highlights a nearby visible row."""
    selected = _make_notification("n1", action="JumpToAgent")
    replacement = _make_notification("n2", action="JumpToAgent")
    modal = NotificationModal([selected, replacement])
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal._pending_confirm_notification_id = "n2"
    modal._pending_confirm_notification_ids = ["n2"]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch("sase.ace.tui.modals.notification_modal.mark_muted"):
        modal.action_toggle_mute()

    assert selected.muted is True
    assert modal._active_notification_tag is None
    assert modal._marked_notification_ids == set()
    assert modal._pending_confirm_notification_id == "n2"
    assert modal._pending_confirm_notification_ids == ["n2"]
    modal._rebuild_list.assert_called_once_with(highlight_index=1)


def test_toggle_mute_with_marks_bulk_mutes_marked_rows_once() -> None:
    """M targets live marks, applies one bulk write, and clears only acted marks."""
    n1 = _make_notification("n1", action="JumpToAgent")
    n2 = _make_notification("n2", action="JumpToAgent")
    n3 = _make_notification("n3", action="JumpToAgent")
    modal = NotificationModal([n1, n2, n3])
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal._marked_notification_ids = {"n1", "n2", "newer-mark"}
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch("sase.ace.tui.modals.notification_modal.mark_many_muted") as mock_mark:
        mock_mark.return_value = 2
        modal.action_toggle_mute()

    mock_mark.assert_called_once_with(["n1", "n2"], True)
    assert n1.muted is True
    assert n2.muted is True
    assert n3.muted is False
    assert modal._marked_notification_ids == {"newer-mark"}
    modal._rebuild_list.assert_called_once_with(highlight_index=2)
    modal.notify.assert_called_once_with("Muted 2 notifications")


def test_toggle_mute_with_marks_unmutes_and_cancels_snoozes() -> None:
    """Marked muted rows bulk-unmute and clear snooze deadlines."""
    n1 = _make_notification("n1", action="JumpToAgent")
    n2 = _make_notification("n2", action="JumpToAgent")
    for n in (n1, n2):
        n.muted = True
        n.snooze_until = "2026-04-22T09:00:00-04:00"
    modal = NotificationModal([n1, n2])
    modal._active_notification_tag = MUTED_TAB_KEY
    modal._marked_notification_ids = {"n1", "n2"}
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch("sase.ace.tui.modals.notification_modal.mark_many_muted") as mock_mark:
        mock_mark.return_value = 2
        modal.action_toggle_mute()

    mock_mark.assert_called_once_with(["n1", "n2"], False)
    assert all(n.muted is False for n in (n1, n2))
    assert all(n.snooze_until is None for n in (n1, n2))
    assert modal._marked_notification_ids == set()
    assert modal._active_notification_tag is None
    modal.notify.assert_called_once_with("Unmuted 2 notifications (snoozes cancelled)")


def test_toggle_mute_with_mixed_marks_converges_to_muted() -> None:
    """If any marked target is unmuted, bulk M mutes every target."""
    n1 = _make_notification("n1", action="JumpToAgent")
    n2 = _make_notification("n2", action="JumpToAgent")
    n2.muted = True
    modal = NotificationModal([n1, n2])
    modal._marked_notification_ids = {"n1", "n2"}
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch("sase.ace.tui.modals.notification_modal.mark_many_muted") as mock_mark:
        mock_mark.return_value = 2
        modal.action_toggle_mute()

    mock_mark.assert_called_once_with(["n1", "n2"], True)
    assert n1.muted is True
    assert n2.muted is True


def test_toggle_mute_prunes_stale_marks_and_falls_back_to_highlight() -> None:
    """Stale-only marks do not cause an empty bulk write."""
    n1 = _make_notification("n1", action="JumpToAgent")
    modal = NotificationModal([n1])
    modal._marked_notification_ids = {"stale"}
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with (
        patch("sase.ace.tui.modals.notification_modal.mark_many_muted") as mock_many,
        patch("sase.ace.tui.modals.notification_modal.mark_muted") as mock_one,
    ):
        modal.action_toggle_mute()

    mock_many.assert_not_called()
    mock_one.assert_called_once_with("n1", True)
    assert modal._marked_notification_ids == set()


def test_unmute_from_muted_tab_highlights_remaining_muted_row() -> None:
    """Unmuting from a still-populated Muted tab highlights the next muted row."""
    selected = _make_notification("n1", action="JumpToAgent")
    selected.muted = True
    replacement = _make_notification("n2", action="JumpToAgent")
    replacement.muted = True
    modal = NotificationModal([selected, replacement])
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch("sase.ace.tui.modals.notification_modal.mark_muted"):
        modal.action_toggle_mute()

    assert selected.muted is False
    assert modal._active_notification_tag == MUTED_TAB_KEY
    modal._rebuild_list.assert_called_once_with(highlight_index=1)


def test_styled_label_uses_tilde_prefix_for_muted() -> None:
    """A muted notification renders with '~ ' prefix instead of '* '."""
    notification = _make_notification("n1", action="JumpToAgent")
    notification.muted = True
    modal = NotificationModal([notification])
    label = modal._create_styled_label(notification)
    assert label.plain.startswith("~ ")


def test_styled_label_uses_asterisk_for_unread_unmuted() -> None:
    """An unread non-muted notification keeps the gold '* ' prefix."""
    notification = _make_notification("n1", action="JumpToAgent")
    modal = NotificationModal([notification])
    label = modal._create_styled_label(notification)
    assert label.plain.startswith("* ")


def test_agent_completion_label_omits_redundant_sender_and_action_badge() -> None:
    """Agent completion rows spend width on the result, not duplicate labels."""
    notification = _make_notification("n1", action="JumpToAgent")
    notification.sender = "user-agent"
    notification.notes = ["CODEX(gpt-5.5) @sase-1l.1 completed: ace(run)-260430_175319"]
    notification.files = ["/tmp/chat.md", "/tmp/diff.diff"]
    modal = NotificationModal([notification])

    label = modal._create_styled_label(notification)

    assert "[user-agent]" not in label.plain
    assert "[agent]" not in label.plain
    assert "2 files" in label.plain


def test_error_label_keeps_sender_and_error_badge() -> None:
    """Error rows keep their source and action badge because both add context."""
    notification = _make_notification("n1", action="ViewErrorReport")
    notification.sender = "user-agent"
    notification.notes = ["Agent failed"]
    modal = NotificationModal([notification])

    label = modal._create_styled_label(notification)

    assert "[user-agent]" in label.plain
    assert "[error]" in label.plain


def test_press_s_pushes_snooze_picker_and_passes_callback() -> None:
    """``s`` pushes the SnoozeDurationModal and registers a callback."""
    notification = _make_notification("n1", action="JumpToAgent")
    modal = NotificationModal([notification])
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]

    push_screen = MagicMock()
    with patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app:
        mock_app.push_screen = push_screen
        modal.action_snooze()

    push_screen.assert_called_once()
    pushed_modal, kwargs = push_screen.call_args
    from sase.ace.tui.modals.snooze_duration_modal import SnoozeDurationModal

    assert isinstance(pushed_modal[0], SnoozeDurationModal)
    assert "callback" in kwargs


def test_snooze_callback_with_timedelta_calls_mark_snoozed() -> None:
    """A timedelta from the picker is converted to an absolute datetime."""
    notification = _make_notification("n1", action="JumpToAgent")
    modal = NotificationModal([notification])
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    captured_callback: list = []

    def fake_push_screen(_screen, *, callback) -> None:
        captured_callback.append(callback)

    with (
        patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app,
        patch("sase.ace.tui.modals.notification_modal.mark_snoozed") as mock_mark,
    ):
        mock_app.push_screen = fake_push_screen
        mock_app._submit_tracked_task = None
        mock_app.screen = modal
        mock_mark.return_value = True
        modal.action_snooze()

        assert captured_callback, "callback was not registered"
        callback = captured_callback[0]
        callback(timedelta(minutes=15))

        mock_mark.assert_called_once()
        args, _ = mock_mark.call_args

    assert args[0] == "n1"
    assert isinstance(args[1], datetime)
    assert notification.muted is True
    assert notification.snooze_until == args[1].isoformat()
    assert modal._active_notification_tag == MUTED_TAB_KEY
    modal.notify.assert_called_once_with("Snoozed for 15m")


def test_snooze_callback_with_datetime_uses_until_label() -> None:
    """A datetime result (e.g. tomorrow morning) preserves the absolute time."""
    notification = _make_notification("n1", action="JumpToAgent")
    modal = NotificationModal([notification])
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    captured_callback: list = []

    def fake_push_screen(_screen, *, callback) -> None:
        captured_callback.append(callback)

    target = datetime(2026, 4, 22, 9, 0, 0, tzinfo=get_timezone())
    with (
        patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app,
        patch("sase.ace.tui.modals.notification_modal.mark_snoozed") as mock_mark,
    ):
        mock_app.push_screen = fake_push_screen
        mock_app._submit_tracked_task = None
        mock_app.screen = modal
        mock_mark.return_value = True
        modal.action_snooze()
        captured_callback[0](target)

        mock_mark.assert_called_once_with("n1", target)

    assert notification.snooze_until == target.isoformat()
    modal.notify.assert_called_once_with("Snoozed until tomorrow morning")


def test_snooze_callback_none_is_cancellation() -> None:
    """Picker returning None just toasts 'Snooze cancelled' — no store call."""
    notification = _make_notification("n1", action="JumpToAgent")
    modal = NotificationModal([notification])
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    captured_callback: list = []

    def fake_push_screen(_screen, *, callback) -> None:
        captured_callback.append(callback)

    with (
        patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app,
        patch("sase.ace.tui.modals.notification_modal.mark_snoozed") as mock_mark,
    ):
        mock_app.push_screen = fake_push_screen
        modal.action_snooze()
        captured_callback[0](None)

        mock_mark.assert_not_called()

    assert notification.snooze_until is None
    assert notification.muted is False
    modal.notify.assert_called_once_with("Snooze cancelled")


def test_single_snooze_submits_tracked_background_write() -> None:
    notification = _make_notification("n1", action="JumpToAgent")
    modal = NotificationModal([notification])
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    captured_callback: list = []

    def fake_push_screen(_screen, *, callback) -> None:
        captured_callback.append(callback)

    with (
        patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app,
        patch("sase.ace.tui.modals.notification_modal.mark_snoozed") as mock_mark,
    ):
        mock_app.push_screen = fake_push_screen
        mock_app._submit_tracked_task.return_value = object()
        modal.action_snooze()
        captured_callback[0](timedelta(minutes=15))

    mock_mark.assert_not_called()
    assert notification.muted is False
    assert notification.snooze_until is None
    mock_app._submit_tracked_task.assert_called_once()
    args = mock_app._submit_tracked_task.call_args.args
    kwargs = mock_app._submit_tracked_task.call_args.kwargs
    assert callable(args[3])
    assert kwargs["dedup_key"] == "notification-state"
    assert kwargs["exclusive_scopes"] == ("notification-state",)


def test_single_snooze_stale_row_does_not_show_false_success() -> None:
    notification = _make_notification("n1", action="JumpToAgent")
    modal = NotificationModal([notification])
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]
    captured_callback: list = []

    def fake_push_screen(_screen, *, callback) -> None:
        captured_callback.append(callback)

    with (
        patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app,
        patch(
            "sase.ace.tui.modals.notification_modal.mark_snoozed",
            return_value=False,
        ),
    ):
        mock_app.push_screen = fake_push_screen
        mock_app._submit_tracked_task = None
        mock_app.screen = modal
        modal.action_snooze()
        captured_callback[0](timedelta(minutes=15))

    assert notification.muted is False
    assert notification.snooze_until is None
    modal._rebuild_list.assert_not_called()
    modal.notify.assert_called_once_with(
        "Could not snooze notification: notification is stale, dismissed, or no longer exists",
        severity="error",
    )


def test_relative_snooze_uses_exact_elapsed_utc_across_dst_transitions() -> None:
    ny = ZoneInfo("America/New_York")
    cases = [
        datetime(2026, 3, 8, 1, 30, tzinfo=ny),
        datetime(2026, 11, 1, 1, 30, tzinfo=ny, fold=0),
    ]

    for local_start in cases:
        start_utc = local_start.astimezone(UTC)
        deadline = _resolve_snooze_deadline(
            timedelta(hours=4),
            now_utc=start_utc,
        )
        assert deadline - start_utc == timedelta(hours=4)
        assert deadline.tzinfo is UTC


def test_snooze_with_marks_uses_one_picker_and_bulk_call() -> None:
    """Marked rows share one computed deadline and one bulk persistence call."""
    n1 = _make_notification("n1", action="JumpToAgent")
    n2 = _make_notification("n2", action="JumpToAgent")
    n3 = _make_notification("n3", action="JumpToAgent")
    modal = NotificationModal([n1, n2, n3])
    modal._marked_notification_ids = {"n1", "n2"}
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]
    captured_callback: list = []

    def fake_push_screen(_screen, *, callback) -> None:
        captured_callback.append(callback)

    with (
        patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app,
        patch("sase.ace.tui.modals.notification_modal.mark_many_snoozed") as mock_mark,
    ):
        mock_app.push_screen = fake_push_screen
        mock_app._submit_tracked_task = None
        mock_app.screen = modal
        mock_mark.return_value = 2
        modal.action_snooze()
        captured_callback[0](timedelta(minutes=15))

    mock_mark.assert_called_once()
    ids, deadline = mock_mark.call_args.args
    assert ids == ["n1", "n2"]
    assert isinstance(deadline, datetime)
    assert n1.snooze_until == deadline.isoformat()
    assert n2.snooze_until == deadline.isoformat()
    assert n3.snooze_until is None
    assert modal._marked_notification_ids == set()
    modal.notify.assert_called_once_with("Snoozed 2 notifications for 15m")


def test_snooze_with_marks_cancellation_keeps_marks_and_state() -> None:
    """Bulk snooze cancellation does not persist or consume marks."""
    n1 = _make_notification("n1", action="JumpToAgent")
    n2 = _make_notification("n2", action="JumpToAgent")
    modal = NotificationModal([n1, n2])
    modal._marked_notification_ids = {"n1", "n2"}
    modal.notify = MagicMock()  # type: ignore[method-assign]
    captured_callback: list = []

    def fake_push_screen(_screen, *, callback) -> None:
        captured_callback.append(callback)

    with (
        patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app,
        patch("sase.ace.tui.modals.notification_modal.mark_many_snoozed") as mock_mark,
    ):
        mock_app.push_screen = fake_push_screen
        mock_app._submit_tracked_task = None
        modal.action_snooze()
        captured_callback[0](None)

    mock_mark.assert_not_called()
    assert modal._marked_notification_ids == {"n1", "n2"}
    assert all(n.snooze_until is None for n in (n1, n2))
    modal.notify.assert_called_once_with("Snooze cancelled")


def test_bulk_state_task_failure_leaves_modal_state_untouched() -> None:
    """A failed marked write does not mutate rows or consume marks."""
    n1 = _make_notification("n1", action="JumpToAgent")
    n2 = _make_notification("n2", action="JumpToAgent")
    modal = NotificationModal([n1, n2])
    modal._marked_notification_ids = {"n1", "n2"}
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch("sase.ace.tui.modals.notification_modal.mark_many_muted") as mock_mark:
        mock_mark.side_effect = RuntimeError("disk busy")
        modal.action_toggle_mute()

    assert all(n.muted is False for n in (n1, n2))
    assert modal._marked_notification_ids == {"n1", "n2"}
    modal._rebuild_list.assert_not_called()
    modal.notify.assert_called_once_with(
        "Notification update failed: disk busy", severity="error"
    )


def test_bulk_state_task_rejects_overlapping_mutation() -> None:
    """A rejected tracked task does not run persistence or mutate modal rows."""
    n1 = _make_notification("n1", action="JumpToAgent")
    n2 = _make_notification("n2", action="JumpToAgent")
    modal = NotificationModal([n1, n2])
    modal._marked_notification_ids = {"n1", "n2"}
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with (
        patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app,
        patch("sase.ace.tui.modals.notification_modal.mark_many_muted") as mock_mark,
    ):
        mock_app._submit_tracked_task.return_value = None
        modal.action_toggle_mute()

    mock_mark.assert_not_called()
    assert all(n.muted is False for n in (n1, n2))
    assert modal._marked_notification_ids == {"n1", "n2"}
    mock_app._submit_tracked_task.assert_called_once()
    kwargs = mock_app._submit_tracked_task.call_args.kwargs
    assert kwargs["dedup_key"] == "notification-state"
    assert kwargs["exclusive_scopes"] == ("notification-state",)


def test_bulk_completion_after_modal_close_does_no_widget_work() -> None:
    """Persistence may succeed after close; the callback leaves widgets untouched."""
    n1 = _make_notification("n1", action="JumpToAgent")
    n2 = _make_notification("n2", action="JumpToAgent")
    modal = NotificationModal([n1, n2])
    modal._marked_notification_ids = {"n1", "n2"}
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app:
        mock_app.screen = object()
        mock_app.screen_stack = []
        modal._complete_bulk_toggle_mute(
            _NotificationMutationResult(
                action="mute",
                ids=("n1", "n2"),
                success=True,
                message="ok",
                matched_count=2,
                muted=True,
            )
        )

    assert all(n.muted is False for n in (n1, n2))
    assert modal._marked_notification_ids == {"n1", "n2"}
    modal._rebuild_list.assert_not_called()
    modal.notify.assert_not_called()


def test_unmute_on_snoozed_clears_snooze_and_toasts() -> None:
    """``m`` on a snoozed row unmutes AND clears snooze_until."""
    notification = _make_notification("n1", action="JumpToAgent")
    notification.muted = True
    notification.snooze_until = "2026-04-22T09:00:00-04:00"
    modal = NotificationModal([notification])
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch("sase.ace.tui.modals.notification_modal.mark_muted") as mock_mark:
        modal.action_toggle_mute()

    mock_mark.assert_called_once_with("n1", False)
    assert notification.muted is False
    assert notification.snooze_until is None
    assert modal._active_notification_tag is None
    modal.notify.assert_called_once_with("Unmuted (snooze cancelled)")


def test_styled_label_includes_snooze_badge_when_snoozed() -> None:
    """A snoozed row's label appends a '⏰ {time}' badge."""
    from datetime import datetime as _datetime
    from datetime import timedelta as _timedelta

    from sase.core.time import get_timezone

    notification = _make_notification("n1", action="JumpToAgent")
    notification.muted = True
    deadline = _datetime.now(get_timezone()) + _timedelta(minutes=14)
    notification.snooze_until = deadline.isoformat()

    modal = NotificationModal([notification])
    label = modal._create_styled_label(notification)
    assert "⏰" in label.plain
