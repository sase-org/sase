"""Compatibility imports for the keymap loading helpers.

The implementation is split by responsibility across ``defaults``,
``registry``, ``bindings``, and ``display``.
"""

from sase.ace.tui.keymaps.bindings import (
    build_app_bindings,
    build_gate_modal_bindings,
    build_glossary_bindings,
    build_statistics_bindings,
    glossary_help_bindings,
    statistics_help_bindings,
)
from sase.ace.tui.keymaps.defaults import (
    load_builtin_app_defaults,
    load_builtin_gate_defaults,
    load_builtin_glossary_defaults,
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
    "build_gate_modal_bindings",
    "build_glossary_bindings",
    "build_statistics_bindings",
    "footer_key_display",
    "glossary_help_bindings",
    "key_display_name",
    "leader_key_display",
    "load_builtin_app_defaults",
    "load_builtin_gate_defaults",
    "load_builtin_glossary_defaults",
    "load_builtin_statistics_defaults",
    "load_keymap_registry",
    "statistics_help_bindings",
]
