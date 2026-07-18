"""Keymap registry for the ace TUI.

Defines dataclasses for all configurable keymaps (app-level bindings and
prefix-key modes) and provides a loader that reads from the merged config
system (``default_config.yml`` -> plugins -> ``sase.yml`` -> overlays).
"""

from sase.ace.tui.keymaps.loader import (
    build_app_bindings,
    build_gate_modal_bindings,
    build_telemetry_bindings,
    footer_key_display,
    key_display_name,
    load_builtin_app_defaults,
    load_builtin_gate_defaults,
    load_builtin_telemetry_defaults,
    load_keymap_registry,
    telemetry_help_bindings,
)
from sase.ace.tui.keymaps.types import (
    BUILTIN_MODE_NAMES,
    AppKeymaps,
    BangModeKeymaps,
    CopyModeKeymaps,
    FoldModeKeymaps,
    GateModalKeymaps,
    KeymapRegistry,
    LeaderModeKeymaps,
    ModeKeymaps,
    TelemetryPaneKeymaps,
    _BINDING_META,
    canonicalize_key_binding,
    canonicalize_single_key,
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
    "GateModalKeymaps",
    "KeymapRegistry",
    "LeaderModeKeymaps",
    "ModeKeymaps",
    "TelemetryPaneKeymaps",
    "_BINDING_META",
    "build_app_bindings",
    "build_gate_modal_bindings",
    "build_telemetry_bindings",
    "canonicalize_key_binding",
    "canonicalize_single_key",
    "footer_key_display",
    "is_valid_key",
    "key_display_name",
    "load_builtin_app_defaults",
    "load_builtin_gate_defaults",
    "load_builtin_telemetry_defaults",
    "load_keymap_registry",
    "normalize_key_binding",
    "split_key_alternatives",
    "telemetry_help_bindings",
]
