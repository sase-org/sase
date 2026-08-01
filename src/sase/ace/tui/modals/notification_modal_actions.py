"""State-changing actions for the notification modal."""

from __future__ import annotations

from .notification_modal_action_support import NotificationActionSupportMixin
from .notification_modal_action_types import (
    NotificationMutationResult,
    NotificationTargetSelection,
    resolve_snooze_deadline,
)
from .notification_modal_basic_actions import NotificationBasicActionsMixin
from .notification_modal_mute_actions import NotificationMuteActionsMixin
from .notification_modal_snooze_actions import NotificationSnoozeActionsMixin

# Preserve the original private helper imports while implementations live in
# focused modules.
_NotificationMutationResult = NotificationMutationResult
_NotificationTargetSelection = NotificationTargetSelection
_resolve_snooze_deadline = resolve_snooze_deadline

__all__ = [
    "NotificationStateActionsMixin",
    "_NotificationMutationResult",
    "_NotificationTargetSelection",
    "_resolve_snooze_deadline",
]


class NotificationStateActionsMixin(
    NotificationBasicActionsMixin,
    NotificationMuteActionsMixin,
    NotificationSnoozeActionsMixin,
    NotificationActionSupportMixin,
):
    """Compose all state-changing notification modal actions."""
