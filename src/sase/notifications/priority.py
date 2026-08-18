"""Priority and error classification for notifications.

Priority notifications demand visual prominence (red indicator) versus
background chatter (gold). Errors are a parallel "something broke" class
rendered in their own section. Lives outside the TUI layer so toast,
metrics, mobile, and other surfaces share the same classification.
"""

from sase.notifications.models import Notification

_PRIORITY_ACTIONS = frozenset(
    {
        "PlanApproval",
        "EpicApproval",
        "UserQuestion",
        "LaunchApproval",
        "TaskTriage",
        "BeadSnooze",
        "FlagTriage",
        "BeadStaleCleanup",
        "PluginsRequired",
        "JumpToMentorReview",
    }
)
_PRIORITY_SENDERS = frozenset({"axe", "crs"})
_ERROR_SENDERS = frozenset({"axe", "file-hooks", "user-agent"})


def is_error(notification: Notification) -> bool:
    """Return True if the notification represents an error report.

    Error notifications are axe error digests, failed file hooks, and
    failed-agent reports paired with action ``ViewErrorReport``.
    """
    return (
        notification.action == "ViewErrorReport"
        and notification.sender in _ERROR_SENDERS
    )


def is_priority(notification: Notification) -> bool:
    """Return True if the notification should drive the red indicator state.

    Priority notifications are: plan approvals, user questions, mentor
    reviews, CRS workflow results, and non-error axe notifications.
    Error reports (see :func:`is_error`) are classified separately.
    """
    if is_error(notification):
        return False
    if notification.action in _PRIORITY_ACTIONS:
        return True
    if notification.sender in _PRIORITY_SENDERS:
        return True
    return False
