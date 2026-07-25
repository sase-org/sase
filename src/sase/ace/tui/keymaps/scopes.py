"""Load keymaps whose bindings are scoped to focused TUI widgets."""

import logging
from dataclasses import fields
from typing import Any

from sase.ace.tui.keymaps.defaults import (
    load_builtin_gate_defaults,
    load_builtin_statistics_defaults,
)
from sase.ace.tui.keymaps.app_keymaps import (
    GateModalKeymaps,
    StatisticsPaneKeymaps,
)
from sase.ace.tui.keymaps.key_validation import (
    canonicalize_key_binding,
    is_valid_key,
    normalize_key_binding,
    split_key_alternatives,
)

log = logging.getLogger(__name__)


def load_statistics_keymaps(keymaps_cfg: dict[str, Any]) -> StatisticsPaneKeymaps:
    """Load and validate the focused Statistics-pane binding scope."""

    defaults = load_builtin_statistics_defaults()
    field_names = {field.name for field in fields(StatisticsPaneKeymaps)}
    missing = sorted(field_names - set(defaults))
    if missing:
        raise ValueError(
            "default_config.yml missing statistics keymaps: "
            f"{', '.join(missing)}. Add these under ace.keymaps.statistics."
        )

    raw_overrides = keymaps_cfg.get("statistics", {})
    overrides = raw_overrides if isinstance(raw_overrides, dict) else {}
    extra = sorted(set(overrides) - field_names)
    if extra:
        log.warning(
            "Unknown statistics keymap action(s) in config (ignored): %s",
            ", ".join(extra),
        )

    values = {
        name: canonicalize_key_binding(overrides[name])
        if isinstance(overrides.get(name), str)
        else defaults[name]
        for name in field_names
    }
    user_overridden = {name for name in field_names if values[name] != defaults[name]}

    for name in sorted(user_overridden):
        key = values[name]
        if not is_valid_key(key):
            log.warning(
                "Invalid key %r for statistics action %r; reverting to default %r",
                key,
                name,
                defaults[name],
            )
            values[name] = defaults[name]
            user_overridden.discard(name)
        else:
            values[name] = normalize_key_binding(key)

    key_to_actions: dict[str, list[str]] = {}
    for name, key_value in values.items():
        for key_part in split_key_alternatives(key_value):
            key_to_actions.setdefault(key_part, []).append(name)
    for key_value, actions in key_to_actions.items():
        if len(actions) <= 1:
            continue
        for name in [action for action in actions if action in user_overridden]:
            log.warning(
                "Duplicate statistics key %r: action %r conflicts with %s; "
                "reverting to default %r",
                key_value,
                name,
                [action for action in actions if action != name],
                defaults[name],
            )
            values[name] = defaults[name]

    return StatisticsPaneKeymaps(**values)


def load_gate_keymaps(keymaps_cfg: dict[str, Any]) -> GateModalKeymaps:
    """Load and validate the focused gate-modal binding scope."""

    defaults = load_builtin_gate_defaults()
    field_names = {field.name for field in fields(GateModalKeymaps)}
    missing = sorted(field_names - set(defaults))
    if missing:
        raise ValueError(
            "default_config.yml missing gate keymaps: "
            f"{', '.join(missing)}. Add these under ace.keymaps.gate."
        )
    raw_overrides = keymaps_cfg.get("gate", {})
    overrides = raw_overrides if isinstance(raw_overrides, dict) else {}
    legacy_activate = overrides.get("activate_control")
    if isinstance(legacy_activate, str):
        overrides = dict(overrides)
        if "submit_primary" not in overrides:
            overrides["submit_primary"] = legacy_activate
            log.warning(
                "Gate keymap action 'activate_control' is deprecated; treating it "
                "as 'submit_primary'"
            )
        else:
            log.warning(
                "Gate keymap action 'activate_control' is deprecated and ignored "
                "because 'submit_primary' is configured"
            )
        overrides.pop("activate_control", None)
    extra = sorted(set(overrides) - field_names)
    if extra:
        log.warning(
            "Unknown gate keymap action(s) in config (ignored): %s",
            ", ".join(extra),
        )
    values = {
        name: canonicalize_key_binding(overrides[name])
        if isinstance(overrides.get(name), str)
        else defaults[name]
        for name in field_names
    }
    user_overridden = {name for name in field_names if values[name] != defaults[name]}
    for name in sorted(user_overridden):
        if not is_valid_key(values[name]):
            log.warning(
                "Invalid key %r for gate action %r; reverting to default %r",
                values[name],
                name,
                defaults[name],
            )
            values[name] = defaults[name]
            user_overridden.discard(name)
        else:
            values[name] = normalize_key_binding(values[name])
    key_to_actions: dict[str, list[str]] = {}
    for name, key_value in values.items():
        for key_part in split_key_alternatives(key_value):
            key_to_actions.setdefault(key_part, []).append(name)
    for key_value, actions in key_to_actions.items():
        if len(actions) <= 1:
            continue
        for name in [action for action in actions if action in user_overridden]:
            log.warning(
                "Duplicate gate key %r: action %r conflicts with %s; "
                "reverting to default %r",
                key_value,
                name,
                [action for action in actions if action != name],
                defaults[name],
            )
            values[name] = defaults[name]
    return GateModalKeymaps(**values)
