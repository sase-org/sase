"""Priority classification for notifications.

Priority notifications demand visual prominence in the indicator (red badge)
versus background chatter (gold). Lives outside the TUI layer so toast,
metrics, or external surfaces can reuse the same classification.
"""

from sase.notifications.models import Notification

_PRIORITY_ACTIONS = frozenset({"PlanApproval", "UserQuestion", "JumpToMentorReview"})
_PRIORITY_SENDERS = frozenset({"axe", "crs"})


def is_priority(notification: Notification) -> bool:
    """Return True if the notification should drive the red indicator state.

    Priority notifications are: plan approvals, user questions, mentor
    reviews, axe error digests, CRS workflow results, and failed-agent
    error reports (``user-agent`` sender with ``ViewErrorReport`` action).
    """
    if notification.action in _PRIORITY_ACTIONS:
        return True
    if notification.sender in _PRIORITY_SENDERS:
        return True
    if notification.sender == "user-agent" and notification.action == "ViewErrorReport":
        return True
    return False
