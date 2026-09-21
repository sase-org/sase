"""Tests for NotificationModal undismiss actions."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.ops.names import NOTIFY_APPLY_STATE

from tests._notification_modal_helpers import _make_notification


def _install_undismiss_submit(
    mock_app: MagicMock,
    modal: NotificationModal,
) -> list[tuple[tuple[object, ...], dict[str, object]]]:
    submissions: list[tuple[tuple[object, ...], dict[str, object]]] = []
    mock_app.screen = modal

    def submit(*args: object, **kwargs: object) -> object:
        submissions.append((args, kwargs))
        request = kwargs["request"]
        assert isinstance(request, dict)
        ids = request["ids"]
        assert isinstance(ids, list)
        payload = dict(request)
        payload["matched_count"] = len(ids)
        on_complete = kwargs["on_complete"]
        assert callable(on_complete)
        on_complete(
            SimpleNamespace(
                success=True,
                message="ok",
                payload=payload,
            )
        )
        return object()

    mock_app._submit_durable_proc.side_effect = submit
    return submissions


def test_undismiss_notification_restores_highlighted_row() -> None:
    """u should submit an undismiss task and clear the row's dismissed flag."""
    notification = _make_notification("n1", action="JumpToAgent")
    notification.dismissed = True
    modal = NotificationModal([notification])
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app:
        submissions = _install_undismiss_submit(mock_app, modal)
        modal.action_undismiss_notification()

    [(args, kwargs)] = submissions
    assert args == (["sase", "notify", "apply-state", "n1", "undismiss"],)
    assert kwargs["operation"] == NOTIFY_APPLY_STATE
    request = kwargs["request"]
    assert isinstance(request, dict)
    assert request["ids"] == ["n1"]
    assert notification.dismissed is False
    modal.notify.assert_called_once_with("Undismissed 1 notification")


def test_undismiss_notification_with_marks_restores_marked_rows() -> None:
    """u with marks should bulk-undismiss the marked rows and clear the marks."""
    n1 = _make_notification("n1", action="JumpToAgent")
    n2 = _make_notification("n2", action="JumpToAgent")
    n1.dismissed = True
    n2.dismissed = True
    modal = NotificationModal([n1, n2])
    modal._marked_notification_ids = {"n1", "n2"}
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app:
        submissions = _install_undismiss_submit(mock_app, modal)
        modal.action_undismiss_notification()

    [(args, kwargs)] = submissions
    assert args == (["sase", "notify", "apply-state-many", "undismiss"],)
    request = kwargs["request"]
    assert isinstance(request, dict)
    assert request["ids"] == ["n1", "n2"]
    assert n1.dismissed is False
    assert n2.dismissed is False
    assert modal._marked_notification_ids == set()
    modal.notify.assert_called_once_with("Undismissed 2 notifications")


def test_undismiss_notification_reports_failure() -> None:
    """A failed undismiss task must surface the error and keep the flag."""
    notification = _make_notification("n1", action="JumpToAgent")
    notification.dismissed = True
    modal = NotificationModal([notification])
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app:
        mock_app.screen = modal

        def submit(*args: object, **kwargs: object) -> object:
            on_complete = kwargs["on_complete"]
            assert callable(on_complete)
            on_complete(SimpleNamespace(success=False, message="boom", payload={}))
            return object()

        mock_app._submit_durable_proc.side_effect = submit
        modal.action_undismiss_notification()

    assert notification.dismissed is True
    modal.notify.assert_called_once_with(
        "Could not undismiss notifications: boom", severity="error"
    )
