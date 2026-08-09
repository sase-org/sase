"""Typing surface for lazy clipboard action exports."""

from ._agents import ClipboardAgentsMixin as ClipboardAgentsMixin
from ._artifacts import ClipboardArtifactsMixin as ClipboardArtifactsMixin
from ._axe import ClipboardAxeMixin as ClipboardAxeMixin
from ._core import ClipboardCoreMixin as ClipboardCoreMixin
from ._delivery import CopyDeliveryOutcome as CopyDeliveryOutcome
from ._delivery import CopyFailurePolicy as CopyFailurePolicy
from ._delivery import deliver_copy as deliver_copy
from ._delivery import schedule_copy_delivery as schedule_copy_delivery
from ._patch import ClipboardPatchMixin as ClipboardPatchMixin

class ClipboardMixin(
    ClipboardCoreMixin,
    ClipboardArtifactsMixin,
    ClipboardPatchMixin,
    ClipboardAgentsMixin,
    ClipboardAxeMixin,
): ...
