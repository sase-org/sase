"""Keymap registry for the ace TUI.

Defines dataclasses for all configurable keymaps (app-level bindings and
prefix-key modes) and provides a loader that reads from the merged config
system (``default_config.yml`` -> plugins -> ``sase.yml`` -> overlays).
"""

from sase.ace.tui.keymaps.bindings import (
    build_app_bindings,
    build_gate_modal_bindings,
    build_gate_numbered_branch_bindings,
    build_statistics_bindings,
    statistics_help_bindings,
)
from sase.ace.tui.keymaps.app_keymaps import (
    AppKeymaps,
    GateModalKeymaps,
    StatisticsPaneKeymaps,
)
from sase.ace.tui.keymaps.defaults import (
    load_builtin_app_defaults,
    load_builtin_gate_defaults,
    load_builtin_statistics_defaults,
)
from sase.ace.tui.keymaps.display import (
    footer_key_display,
    key_display_name,
    leader_key_display,
)
from sase.ace.tui.keymaps.key_validation import (
    canonicalize_key_binding,
    canonicalize_single_key,
    is_valid_key,
    normalize_key_binding,
    split_key_alternatives,
)
from sase.ace.tui.keymaps.metadata import _BINDING_META
from sase.ace.tui.keymaps.mode_keymaps import (
    BUILTIN_MODE_NAMES,
    BangModeKeymaps,
    BeadIssueModeKeymaps,
    CopyModeKeymaps,
    FoldModeKeymaps,
    LeaderModeKeymaps,
    ModeKeymaps,
)
from sase.ace.tui.keymaps.registry import load_keymap_registry
from sase.ace.tui.keymaps.types import KeymapRegistry

__all__ = [
    "AppKeymaps",
    "BUILTIN_MODE_NAMES",
    "BangModeKeymaps",
    "BeadIssueModeKeymaps",
    "CopyModeKeymaps",
    "FoldModeKeymaps",
    "GateModalKeymaps",
    "KeymapRegistry",
    "LeaderModeKeymaps",
    "ModeKeymaps",
    "StatisticsPaneKeymaps",
    "_BINDING_META",
    "build_app_bindings",
    "build_gate_modal_bindings",
    "build_gate_numbered_branch_bindings",
    "build_statistics_bindings",
    "canonicalize_key_binding",
    "canonicalize_single_key",
    "footer_key_display",
    "is_valid_key",
    "key_display_name",
    "leader_key_display",
    "load_builtin_app_defaults",
    "load_builtin_gate_defaults",
    "load_builtin_statistics_defaults",
    "load_keymap_registry",
    "normalize_key_binding",
    "split_key_alternatives",
    "statistics_help_bindings",
]
