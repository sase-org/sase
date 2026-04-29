"""Keymap registry for the ace TUI.

Defines dataclasses for all configurable keymaps (app-level bindings and
prefix-key modes) and provides a loader that reads from the merged config
system (``default_config.yml`` -> plugins -> ``sase.yml`` -> overlays).
"""

from sase.ace.tui.keymaps.loader import (
    build_app_bindings,
    footer_key_display,
    key_display_name,
    load_builtin_app_defaults,
    load_keymap_registry,
)
from sase.ace.tui.keymaps.types import (
    BUILTIN_MODE_NAMES,
    AppKeymaps,
    BangModeKeymaps,
    CopyModeKeymaps,
    FoldModeKeymaps,
    KeymapRegistry,
    LeaderModeKeymaps,
    ModeKeymaps,
    _BINDING_META,
    is_valid_key,
    normalize_key_binding,
    split_key_alternatives,
)

__all__ = [
    "AppKeymaps",
    "BUILTIN_MODE_NAMES",
    "BangModeKeymaps",
    "CopyModeKeymaps",
    "FoldModeKeymaps",
    "KeymapRegistry",
    "LeaderModeKeymaps",
    "ModeKeymaps",
    "_BINDING_META",
    "build_app_bindings",
    "footer_key_display",
    "is_valid_key",
    "key_display_name",
    "load_builtin_app_defaults",
    "load_keymap_registry",
    "normalize_key_binding",
    "split_key_alternatives",
]
