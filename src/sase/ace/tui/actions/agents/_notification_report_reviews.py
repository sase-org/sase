"""Small registry for report notifications with a focused review surface."""

from __future__ import annotations

from collections.abc import Callable

from sase.notifications import Notification

ReportReviewOpener = Callable[[object, Notification], bool]


def _open_run_prune_review(app: object, notification: Notification) -> bool:
    from sase.core.agent_artifact_run_prune_review import parse_run_prune_review

    review = parse_run_prune_review(notification.action_data)
    if review is None:
        return False
    from sase.ace.tui.modals.artifact_run_prune_modal import ArtifactRunPruneModal

    app.push_screen(ArtifactRunPruneModal(review, notification))  # type: ignore[attr-defined]
    return True


def _review_openers() -> dict[str, ReportReviewOpener]:
    from sase.core.agent_artifact_run_prune_review import (
        RUN_PRUNE_REVIEW_ACTION_DATA_KEY,
    )

    return {RUN_PRUNE_REVIEW_ACTION_DATA_KEY: _open_run_prune_review}


def open_notification_report_review(
    app: object,
    notification: Notification,
) -> bool:
    """Open a specialized report review, returning false for absent/bad payloads."""
    for action_data_key, opener in _review_openers().items():
        raw = notification.action_data.get(action_data_key)
        if not isinstance(raw, str) or not raw:
            continue
        if opener(app, notification):
            return True
    return False


__all__ = ["open_notification_report_review"]
