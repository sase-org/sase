"""Public facade for KeybindingFooter binding-computation helpers.

Implementation lives in sibling ``_keybinding_bindings_*`` modules; this
file re-exports the names that callers and tests historically import
from ``_keybinding_bindings``.
"""

from __future__ import annotations

from ._keybinding_bindings_agents import AgentBindingsMixin
from ._keybinding_bindings_axe import AxeBindingsMixin
from ._keybinding_bindings_chips import (
    _CHIP_SEPARATOR,
    _GRID_COLUMN_GAP,
    KeybindingChipsMixin,
)
from ._keybinding_bindings_patch import PatchBindingsMixin

__all__ = [
    "AgentBindingsMixin",
    "AxeBindingsMixin",
    "KeybindingBindingsMixin",
    "KeybindingChipsMixin",
    "PatchBindingsMixin",
    "_CHIP_SEPARATOR",
    "_GRID_COLUMN_GAP",
]


class KeybindingBindingsMixin(
    AxeBindingsMixin,
    AgentBindingsMixin,
    PatchBindingsMixin,
    KeybindingChipsMixin,
):
    """Pure binding-list computation for :class:`KeybindingFooter`.

    The mixin relies on the host to supply:
      - ``self._kd(action_name: str) -> str`` — footer key display resolver.
      - ``self._axe_running: bool`` — whether the AXE daemon is running.
    """

    _axe_running: bool
