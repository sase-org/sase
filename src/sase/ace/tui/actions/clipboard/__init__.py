"""Clipboard action mixin for the ace TUI app.

The ``ClipboardMixin`` is composed of one mixin per tab plus a core mixin that
handles copy-mode lifecycle and per-tab key dispatch. All TUI clipboard writes
go through ``schedule_copy_delivery``.
"""

from ._agents import ClipboardAgentsMixin
from ._artifacts import ClipboardArtifactsMixin
from ._axe import ClipboardAxeMixin
from ._changespec import ClipboardChangeSpecMixin
from ._core import ClipboardCoreMixin
from ._delivery import (
    CopyDeliveryOutcome,
    CopyFailurePolicy,
    deliver_copy,
    schedule_copy_delivery,
)


class ClipboardMixin(
    ClipboardCoreMixin,
    ClipboardArtifactsMixin,
    ClipboardChangeSpecMixin,
    ClipboardAgentsMixin,
    ClipboardAxeMixin,
):
    """Mixin providing clipboard copy actions for all tabs."""


__all__ = [
    "ClipboardMixin",
    "CopyDeliveryOutcome",
    "CopyFailurePolicy",
    "deliver_copy",
    "schedule_copy_delivery",
]
