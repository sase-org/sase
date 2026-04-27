"""Clipboard action mixin for the ace TUI app.

The ``ClipboardMixin`` is composed of one mixin per tab plus a core mixin that
handles copy-mode lifecycle and per-tab key dispatch. ``copy_to_system_clipboard``
is re-exported here because external modules import it from this package.
"""

from ._agents import ClipboardAgentsMixin
from ._axe import ClipboardAxeMixin
from ._changespec import ClipboardChangeSpecMixin
from ._core import ClipboardCoreMixin
from ._helpers import copy_to_system_clipboard


class ClipboardMixin(
    ClipboardCoreMixin,
    ClipboardChangeSpecMixin,
    ClipboardAgentsMixin,
    ClipboardAxeMixin,
):
    """Mixin providing clipboard copy actions for all tabs."""


__all__ = ["ClipboardMixin", "copy_to_system_clipboard"]
