"""Compatibility imports for the keymap loading helpers.

The implementation is split by responsibility across ``defaults``,
``registry``, ``bindings``, and ``display``.
"""

from sase.ace.tui.keymaps.bindings import (
    build_app_bindings,
    build_config_hub_bindings,
    build_gate_input_panel_bindings,
    build_gate_modal_bindings,
    build_memory_bindings,
    build_statistics_bindings,
    memory_help_bindings,
    statistics_help_bindings,
)
from sase.ace.tui.keymaps.defaults import (
    load_builtin_app_defaults,
    load_builtin_config_defaults,
    load_builtin_gate_defaults,
    load_builtin_memory_defaults,
    load_builtin_statistics_defaults,
)
from sase.ace.tui.keymaps.display import (
    footer_key_display,
    key_display_name,
    leader_key_display,
)
from sase.ace.tui.keymaps.registry import load_keymap_registry

__all__ = [
    "build_app_bindings",
    "build_config_hub_bindings",
    "build_gate_input_panel_bindings",
    "build_gate_modal_bindings",
    "build_memory_bindings",
    "build_statistics_bindings",
    "footer_key_display",
    "key_display_name",
    "leader_key_display",
    "load_builtin_app_defaults",
    "load_builtin_config_defaults",
    "load_builtin_gate_defaults",
    "load_builtin_memory_defaults",
    "load_builtin_statistics_defaults",
    "load_keymap_registry",
    "memory_help_bindings",
    "statistics_help_bindings",
]
