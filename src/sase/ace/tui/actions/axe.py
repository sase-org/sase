"""Axe control mixin for sase's TUI app.

Facade preserving the original ``sase.ace.tui.actions.axe`` import path.
Implementation lives in :mod:`axe_toggle`, :mod:`axe_quit`, and
:mod:`axe_service`; this module only composes and re-exports public names.
"""

from __future__ import annotations

from .axe_bgcmd import AxeBgCmdMixin
from .axe_chop_run import AxeChopRunMixin
from .axe_config_actions import AxeConfigActionsMixin
from .axe_display import AxeDisplayMixin
from .axe_quit import AxeQuitMixin
from .axe_service import (
    AxeServiceMixin,
    AxeViewType,
    AxeWorkerOperation,
    TabName,
)
from .axe_toggle import AxeToggleMixin


class AxeMixin(
    AxeToggleMixin,
    AxeQuitMixin,
    AxeServiceMixin,
    AxeConfigActionsMixin,
    AxeBgCmdMixin,
    AxeChopRunMixin,
    AxeDisplayMixin,
):
    """Mixin providing axe daemon control and display methods."""


__all__ = [
    "AxeMixin",
    "AxeViewType",
    "AxeWorkerOperation",
    "TabName",
]
