"""Clipboard action mixin for the ace TUI app.

The ``ClipboardMixin`` is composed of one mixin per tab plus a core mixin that
handles copy-mode lifecycle and per-tab key dispatch. All TUI clipboard writes
go through ``schedule_copy_delivery``.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ._delivery import CopyDeliveryOutcome as CopyDeliveryOutcome

_DELIVERY_EXPORTS = {
    "CopyDeliveryOutcome",
    "CopyFailurePolicy",
    "deliver_copy",
    "schedule_copy_delivery",
}


__all__ = [
    "ClipboardMixin",
    "CopyDeliveryOutcome",
    "CopyFailurePolicy",
    "deliver_copy",
    "schedule_copy_delivery",
]


def _build_clipboard_mixin() -> type[Any]:
    from ._agents import ClipboardAgentsMixin
    from ._artifacts import ClipboardArtifactsMixin
    from ._axe import ClipboardAxeMixin
    from ._core import ClipboardCoreMixin
    from ._patch import ClipboardPatchMixin

    class ClipboardMixin(
        ClipboardCoreMixin,
        ClipboardArtifactsMixin,
        ClipboardPatchMixin,
        ClipboardAgentsMixin,
        ClipboardAxeMixin,
    ):
        """Mixin providing clipboard copy actions for all tabs."""

    ClipboardMixin.__module__ = __name__
    ClipboardMixin.__qualname__ = "ClipboardMixin"
    return ClipboardMixin


def __getattr__(name: str) -> Any:
    if name == "ClipboardMixin":
        value = _build_clipboard_mixin()
    elif name in _DELIVERY_EXPORTS:
        value = getattr(import_module("._delivery", __name__), name)
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})


# PEP 562 entry points are called by Python, not by normal in-file code.
_PEP562_HOOKS = (__getattr__, __dir__)
