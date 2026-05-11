"""Axe display and state management mixin for the ace TUI app."""

from ._data import (
    BgCmdSnapshot,
    ChopRunSnapshot,
    ChopSnapshot,
    LumberjackSnapshot,
    collect_axe_status_data,
    collect_chop_snapshot,
    get_axe_process_module,
)
from ._render import AxeDisplayRenderMixin


class AxeDisplayMixin(AxeDisplayRenderMixin):
    """Mixin providing axe display refresh and state loading."""


__all__ = [
    "AxeDisplayMixin",
    "BgCmdSnapshot",
    "ChopRunSnapshot",
    "ChopSnapshot",
    "LumberjackSnapshot",
    "collect_axe_status_data",
    "collect_chop_snapshot",
    "get_axe_process_module",
]
