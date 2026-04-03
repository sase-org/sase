"""Hint-based action methods for the ace TUI app."""

from ._accept import AcceptMailMixin
from ._files import FileViewingMixin
from ._hooks import HookEditingMixin
from ._jump import JumpToEntryMixin
from ._mentors import MentorKillingMixin
from ._processing import InputProcessingMixin
from ._rewind import RewindMixin


class HintActionsMixin(
    AcceptMailMixin,
    FileViewingMixin,
    HookEditingMixin,
    JumpToEntryMixin,
    MentorKillingMixin,
    InputProcessingMixin,
    RewindMixin,
):
    """Mixin providing hint-based actions (edit hooks, view files, kill mentors, rewind, jump)."""

    pass
