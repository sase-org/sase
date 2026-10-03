"""Construct and validate the complete sase's TUI keymap registry."""

from dataclasses import fields

from sase.ace.tui.keymaps._registry_shared import log
from sase.ace.tui.keymaps.app_keymaps import AppKeymaps
from sase.ace.tui.keymaps.key_validation import split_key_alternatives
from sase.ace.tui.keymaps.metadata import _MODE_PREFIX_ACTIONS
from sase.ace.tui.keymaps.mode_keymaps import _BUILTIN_MODE_CLASSES
from sase.ace.tui.keymaps.registry_app import LEGACY_APP_KEY_ALIASES, build_app_keymaps
from sase.ace.tui.keymaps.registry_modes import build_mode_keymaps
from sase.ace.tui.keymaps.scopes import (
    load_command_line_keymaps,
    load_config_keymaps,
    load_gate_keymaps,
    load_machines_keymaps,
    load_memory_keymaps,
    load_projects_keymaps,
    load_snippets_keymaps,
    load_statistics_keymaps,
    load_tool_runs_keymaps,
)
from sase.ace.tui.keymaps.types import KeymapRegistry

__all__ = [
    "LEGACY_APP_KEY_ALIASES",
    "load_keymap_registry",
]


def load_keymap_registry(ace_cfg: dict) -> KeymapRegistry:
    """Build a ``KeymapRegistry`` from the merged ``ace`` config section.

    All app-level keybindings must be defined in configuration files. Missing
    bindings cause a ``ValueError`` at startup so ``default_config.yml`` stays
    in sync with ``AppKeymaps``.
    """
    app_km, keymaps_cfg, legacy_card_block_brackets = build_app_keymaps(ace_cfg)

    command_line_km = load_command_line_keymaps(keymaps_cfg)
    config_km = load_config_keymaps(keymaps_cfg)
    statistics_km = load_statistics_keymaps(keymaps_cfg)
    gate_km = load_gate_keymaps(keymaps_cfg)
    machines_km = load_machines_keymaps(keymaps_cfg)
    memory_km = load_memory_keymaps(keymaps_cfg)
    snippets_km = load_snippets_keymaps(keymaps_cfg)
    projects_km = load_projects_keymaps(keymaps_cfg)
    tool_runs_km = load_tool_runs_keymaps(keymaps_cfg)

    modes = build_mode_keymaps(keymaps_cfg)

    registry = KeymapRegistry(
        app=app_km,
        command_line=command_line_km,
        config=config_km,
        statistics=statistics_km,
        gate=gate_km,
        machines=machines_km,
        memory=memory_km,
        snippets=snippets_km,
        projects=projects_km,
        tool_runs=tool_runs_km,
        modes=modes,
        legacy_card_block_brackets=legacy_card_block_brackets,
    )

    for mode_name, action_name in _MODE_PREFIX_ACTIONS.items():
        mode = registry.modes.get(mode_name)
        if mode is None:
            continue
        app_key = getattr(registry.app, action_name, None)
        if app_key != mode.prefix:
            log.warning(
                "Mode %s prefix %r differs from app.%s %r; using mode prefix",
                mode_name,
                mode.prefix,
                action_name,
                app_key,
            )
            setattr(registry.app, action_name, mode.prefix)

    app_keys: set[str] = {
        key_part
        for f in fields(AppKeymaps)
        for key_part in split_key_alternatives(getattr(registry.app, f.name))
    }
    for mode_name, mode in registry.modes.items():
        if mode_name in _BUILTIN_MODE_CLASSES:
            continue
        if mode.prefix and mode.prefix in app_keys:
            log.warning(
                "Custom mode %r prefix %r conflicts with an existing app binding; "
                "the prefix key will activate the custom mode instead",
                mode_name,
                mode.prefix,
            )

    return registry
