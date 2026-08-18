"""Load keymaps whose bindings are scoped to focused TUI widgets."""

import logging
from collections.abc import Callable
from dataclasses import fields
from typing import Any

from sase.ace.tui.keymaps.defaults import (
    load_builtin_gate_defaults,
    load_builtin_glossary_defaults,
    load_builtin_projects_defaults,
    load_builtin_statistics_defaults,
)
from sase.ace.tui.keymaps.app_keymaps import (
    GateModalKeymaps,
    GlossaryPanelKeymaps,
    ProjectsPaneKeymaps,
    StatisticsPaneKeymaps,
)
from sase.ace.tui.keymaps.key_validation import (
    canonicalize_key_binding,
    is_valid_key,
    normalize_key_binding,
    split_key_alternatives,
)

log = logging.getLogger(__name__)


def _load_scope_keymaps(
    keymaps_cfg: dict[str, Any],
    *,
    scope: str,
    dataclass_type: type[Any],
    defaults: dict[str, str],
    pre_step: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> Any:
    """Load and validate one focused-pane binding scope.

    Shared by every scope with a dataclass, a bundled-defaults loader, and a
    ``ace.keymaps.<scope>`` config section: unknown-action warnings, per-field
    canonicalization, invalid-key revert, and duplicate-key revert all behave
    identically across scopes. ``pre_step`` runs on the raw overrides mapping
    before extras are computed, for scope-specific migrations (e.g. the gate
    scope's ``activate_control`` deprecation shim).
    """

    field_names = {field.name for field in fields(dataclass_type)}
    missing = sorted(field_names - set(defaults))
    if missing:
        raise ValueError(
            f"default_config.yml missing {scope} keymaps: "
            f"{', '.join(missing)}. Add these under ace.keymaps.{scope}."
        )

    raw_overrides = keymaps_cfg.get(scope, {})
    overrides = raw_overrides if isinstance(raw_overrides, dict) else {}
    if pre_step is not None:
        overrides = pre_step(overrides)
    extra = sorted(set(overrides) - field_names)
    if extra:
        log.warning(
            "Unknown %s keymap action(s) in config (ignored): %s",
            scope,
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
                "Invalid key %r for %s action %r; reverting to default %r",
                key,
                scope,
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
                "Duplicate %s key %r: action %r conflicts with %s; "
                "reverting to default %r",
                scope,
                key_value,
                name,
                [action for action in actions if action != name],
                defaults[name],
            )
            values[name] = defaults[name]

    return dataclass_type(**values)


def _migrate_gate_legacy_activate_control(
    overrides: dict[str, Any],
) -> dict[str, Any]:
    """Fold the retired ``activate_control`` gate override into ``submit_primary``."""

    legacy_activate = overrides.get("activate_control")
    if not isinstance(legacy_activate, str):
        return overrides

    migrated = dict(overrides)
    if "submit_primary" not in migrated:
        migrated["submit_primary"] = legacy_activate
        log.warning(
            "Gate keymap action 'activate_control' is deprecated; treating it "
            "as 'submit_primary'"
        )
    else:
        log.warning(
            "Gate keymap action 'activate_control' is deprecated and ignored "
            "because 'submit_primary' is configured"
        )
    migrated.pop("activate_control", None)
    return migrated


def load_statistics_keymaps(keymaps_cfg: dict[str, Any]) -> StatisticsPaneKeymaps:
    """Load and validate the focused Statistics-pane binding scope."""

    return _load_scope_keymaps(
        keymaps_cfg,
        scope="statistics",
        dataclass_type=StatisticsPaneKeymaps,
        defaults=load_builtin_statistics_defaults(),
    )


def load_gate_keymaps(keymaps_cfg: dict[str, Any]) -> GateModalKeymaps:
    """Load and validate the focused gate-modal binding scope."""

    return _load_scope_keymaps(
        keymaps_cfg,
        scope="gate",
        dataclass_type=GateModalKeymaps,
        defaults=load_builtin_gate_defaults(),
        pre_step=_migrate_gate_legacy_activate_control,
    )


def load_glossary_keymaps(keymaps_cfg: dict[str, Any]) -> GlossaryPanelKeymaps:
    """Load and validate the focused Glossary-panel binding scope."""

    return _load_scope_keymaps(
        keymaps_cfg,
        scope="glossary",
        dataclass_type=GlossaryPanelKeymaps,
        defaults=load_builtin_glossary_defaults(),
    )


def load_projects_keymaps(keymaps_cfg: dict[str, Any]) -> ProjectsPaneKeymaps:
    """Load and validate the focused Admin Center Projects binding scope."""

    return _load_scope_keymaps(
        keymaps_cfg,
        scope="projects",
        dataclass_type=ProjectsPaneKeymaps,
        defaults=load_builtin_projects_defaults(),
    )
