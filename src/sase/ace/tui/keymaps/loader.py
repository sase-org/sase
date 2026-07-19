"""Keymap loading, binding construction, and display helpers.

Provides the loader that reads from the merged config system
(``default_config.yml`` -> plugins -> ``sase.yml`` -> overlays),
the Textual ``Binding`` builder, and key display name utilities.
"""

import functools
import importlib.resources
import logging
from dataclasses import fields
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

import yaml  # type: ignore[import-untyped]
from textual.binding import Binding

from sase.ace.tui.artifact_tabs import ARTIFACTS_SUBTAB_ORDER
from sase.ace.tui.keymaps.types import (
    _BUILTIN_MODE_CLASSES,
    _KEY_DISPLAY,
    _MODE_PREFIX_ACTIONS,
    AppKeymaps,
    GateModalKeymaps,
    KeymapRegistry,
    ModeKeymaps,
    StatisticsPaneKeymaps,
    canonicalize_key_binding,
    canonicalize_single_key,
    is_valid_key,
    normalize_key_binding,
    split_key_alternatives,
)

# Re-import _BINDING_META so build_app_bindings can use it.
from sase.ace.tui.keymaps.types import (
    _BINDING_META,
    _GATE_BINDING_META,
    _STATISTICS_BINDING_META,
)

log = logging.getLogger(__name__)


# Retired app-level action ids. Drop stale user overrides quietly so configs
# from before the leader-chord remap continue to load without warnings.
_RETIRED_APP_KEYS: frozenset[str] = frozenset({"edit_query", "show_help"})


# Retired built-in leader-mode action ids. These are dropped while loading so a
# stale user override cannot deep-merge a removed command back into the registry.
# ``kill_marked_and_edit`` was folded into the contextual ``kill_and_edit``
# (``,x``) action; ``restore_prompt_stash`` (the old global ``,P``) was replaced
# by the app-level ``@`` binding and prompt-local ``Ctrl+G p`` panel opener;
# ``mark_inactive`` / ``mark_inactive_pinned`` / ``activity_info`` were removed
# with the former user-presence dashboard; ``log_panel`` moved into the
# Admin Center Logs tab and is opened via command palette or ``#``;
# ``task_queue`` moved into the Admin Center Tasks tab;
# ``toggle_selected_agent_panels`` moved to the app-level ``L`` action.
_RETIRED_LEADER_KEYS: frozenset[str] = frozenset(
    {
        "kill_marked_and_edit",
        "restore_prompt_stash",
        "mark_inactive",
        "mark_inactive_pinned",
        "activity_info",
        "log_panel",
        "task_queue",
        "toggle_selected_agent_panels",
    }
)


# ---------------------------------------------------------------------------
# Defaults loader
# ---------------------------------------------------------------------------


@functools.cache
def _builtin_keymaps_config() -> Mapping[str, Any]:
    """Parse and cache the bundled keymap configuration."""

    ref = importlib.resources.files("sase").joinpath("default_config.yml")
    text = ref.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        msg = "default_config.yml is not a valid YAML mapping"
        raise RuntimeError(msg)
    keymaps = data.get("ace", {}).get("keymaps", {})
    if not isinstance(keymaps, dict):
        msg = "default_config.yml missing ace.keymaps section"
        raise RuntimeError(msg)
    return MappingProxyType(keymaps)


@functools.cache
def _builtin_app_defaults() -> Mapping[str, str]:
    """Cache app-level defaults from the bundled configuration."""

    app = _builtin_keymaps_config().get("app", {})
    if not isinstance(app, dict):
        msg = "default_config.yml missing ace.keymaps.app section"
        raise RuntimeError(msg)
    return MappingProxyType(
        {k: canonicalize_key_binding(str(v)) for k, v in app.items()}
    )


def load_builtin_app_defaults() -> dict[str, str]:
    """Load app-level keymap defaults from the bundled ``default_config.yml``.

    Returns a fresh ``dict`` per call; callers may freely mutate it without
    corrupting the cached parse.
    """
    return dict(_builtin_app_defaults())


@functools.cache
def _builtin_statistics_defaults() -> Mapping[str, str]:
    """Cache focused Statistics-pane defaults from bundled configuration."""

    statistics = _builtin_keymaps_config().get("statistics", {})
    if not isinstance(statistics, dict):
        msg = "default_config.yml missing ace.keymaps.statistics section"
        raise RuntimeError(msg)
    return MappingProxyType(
        {k: canonicalize_key_binding(str(v)) for k, v in statistics.items()}
    )


def load_builtin_statistics_defaults() -> dict[str, str]:
    """Return a mutable copy of bundled focused Statistics-pane defaults."""

    return dict(_builtin_statistics_defaults())


@functools.cache
def _builtin_gate_defaults() -> Mapping[str, str]:
    """Cache focused gate-modal defaults from bundled configuration."""

    gate = _builtin_keymaps_config().get("gate", {})
    if not isinstance(gate, dict):
        msg = "default_config.yml missing ace.keymaps.gate section"
        raise RuntimeError(msg)
    return MappingProxyType(
        {k: canonicalize_key_binding(str(v)) for k, v in gate.items()}
    )


def load_builtin_gate_defaults() -> dict[str, str]:
    """Return a mutable copy of bundled focused gate-modal defaults."""

    return dict(_builtin_gate_defaults())


def _load_statistics_keymaps(keymaps_cfg: dict[str, Any]) -> StatisticsPaneKeymaps:
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


def _load_gate_keymaps(keymaps_cfg: dict[str, Any]) -> GateModalKeymaps:
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


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _deep_merge_keys(
    defaults: dict[str, str | dict[str, str]],
    overrides: dict[str, str | dict[str, str]],
) -> dict[str, str | dict[str, str]]:
    """Merge mode key overrides into defaults, handling nested dicts."""
    result = dict(defaults)
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            existing = result[k]
            assert isinstance(existing, dict)  # guarded above
            result[k] = {**existing, **v}
        else:
            result[k] = v
    return result


def _canonicalize_mode_keys(
    keys: dict[str, str | dict[str, str]],
) -> dict[str, str | dict[str, str]]:
    """Canonicalize built-in mode key strings, including nested per-tab keys."""
    result: dict[str, str | dict[str, str]] = {}
    for name, value in keys.items():
        if isinstance(value, dict):
            result[name] = {
                sub_name: canonicalize_key_binding(sub_value)
                for sub_name, sub_value in value.items()
            }
        else:
            result[name] = canonicalize_key_binding(value)
    return result


def _migrate_agent_fold_toggle_alias(
    keys: dict[str, str | dict[str, str]],
    defaults: dict[str, str | dict[str, str]],
) -> dict[str, str | dict[str, str]]:
    """Migrate the retired Agents reverse-cycle action to ``toggle_all``."""
    raw_agent_keys = keys.get("agents")
    if not isinstance(raw_agent_keys, dict) or "cycle_level_back" not in raw_agent_keys:
        return keys

    migrated_agent_keys = dict(raw_agent_keys)
    legacy_binding = migrated_agent_keys.pop("cycle_level_back")
    default_agent_keys = defaults.get("agents")
    default_toggle = (
        default_agent_keys.get("toggle_all")
        if isinstance(default_agent_keys, dict)
        else None
    )
    toggle_is_customized = (
        "toggle_all" in migrated_agent_keys
        and migrated_agent_keys["toggle_all"] != default_toggle
    )
    if not toggle_is_customized and isinstance(legacy_binding, str):
        migrated_agent_keys["toggle_all"] = legacy_binding
        log.warning(
            "Agents fold keymap action 'cycle_level_back' is deprecated; "
            "treating it as 'toggle_all'"
        )
    elif toggle_is_customized:
        log.warning(
            "Agents fold keymap action 'cycle_level_back' is deprecated and "
            "ignored because 'toggle_all' is configured"
        )
    else:
        log.warning(
            "Agents fold keymap action 'cycle_level_back' is deprecated and "
            "ignored because its binding is invalid"
        )

    migrated = dict(keys)
    migrated["agents"] = migrated_agent_keys
    return migrated


def load_keymap_registry(ace_cfg: dict) -> KeymapRegistry:
    """Build a ``KeymapRegistry`` from the ``ace`` config section.

    All app-level keybindings must be defined in configuration files
    (starting from ``default_config.yml``).  Missing bindings cause a
    ``ValueError`` at startup -- this ensures ``default_config.yml``
    stays in sync with ``AppKeymaps``.

    Args:
        ace_cfg: The ``ace`` dict from the merged config (may be empty).

    Returns:
        Fully populated registry with defaults for any missing overrides.
    """
    # Load defaults from default_config.yml (single source of truth).
    builtin_defaults = load_builtin_app_defaults()
    app_field_names = {f.name for f in fields(AppKeymaps)}

    # Fail loudly if default_config.yml doesn't cover every field.
    missing_from_defaults = sorted(app_field_names - set(builtin_defaults.keys()))
    if missing_from_defaults:
        raise ValueError(
            f"default_config.yml missing app keymaps: "
            f"{', '.join(missing_from_defaults)}. "
            f"Add these under ace.keymaps.app."
        )

    keymaps_cfg = ace_cfg.get("keymaps", {})
    if not isinstance(keymaps_cfg, dict):
        keymaps_cfg = {}

    # --- App keymaps ---
    app_overrides = keymaps_cfg.get("app", {})
    if not isinstance(app_overrides, dict):
        app_overrides = {}
    else:
        app_overrides = dict(app_overrides)
        for retired_name in sorted(_RETIRED_APP_KEYS & app_overrides.keys()):
            app_overrides.pop(retired_name)
            log.debug("Ignoring retired app keymap action: %s", retired_name)

    # Warn about unknown keys in config.
    extra = sorted(set(app_overrides.keys()) - app_field_names)
    if extra:
        log.warning(
            "Unknown keymap action(s) in config (ignored): %s",
            ", ".join(extra),
        )

    # Build kwargs: prefer merged config value, fall back to builtin default.
    app_kwargs: dict[str, str] = {}
    for fname in app_field_names:
        if fname in app_overrides and isinstance(app_overrides[fname], str):
            app_kwargs[fname] = canonicalize_key_binding(app_overrides[fname])
        else:
            app_kwargs[fname] = builtin_defaults[fname]

    # --- Validate user-overridden keys ---
    user_overridden = {
        fname
        for fname in app_field_names
        if app_kwargs[fname] != builtin_defaults[fname]
    }

    # Invalid key validation: revert unrecognised keys to defaults.
    for fname in sorted(user_overridden):
        key = app_kwargs[fname]
        if not is_valid_key(key):
            default_val = builtin_defaults[fname]
            log.warning(
                "Invalid key %r for action %r; reverting to default %r",
                key,
                fname,
                default_val,
            )
            app_kwargs[fname] = default_val
            user_overridden.discard(fname)
        else:
            app_kwargs[fname] = normalize_key_binding(key)

    # Duplicate key detection: revert user overrides that conflict.
    key_to_actions: dict[str, list[str]] = {}
    for fname, key_val in app_kwargs.items():
        for key_part in split_key_alternatives(key_val):
            key_to_actions.setdefault(key_part, []).append(fname)

    for key_val, actions in key_to_actions.items():
        if len(actions) <= 1:
            continue
        overridden = [a for a in actions if a in user_overridden]
        if not overridden:
            continue
        for fname in overridden:
            default_val = builtin_defaults[fname]
            log.warning(
                "Duplicate key %r: action %r conflicts with %s; "
                "reverting to default %r",
                key_val,
                fname,
                [a for a in actions if a != fname],
                default_val,
            )
            app_kwargs[fname] = default_val

    app_km = AppKeymaps(**app_kwargs)
    statistics_km = _load_statistics_keymaps(keymaps_cfg)
    gate_km = _load_gate_keymaps(keymaps_cfg)

    # --- Mode keymaps ---
    modes_cfg = keymaps_cfg.get("modes", {})
    if not isinstance(modes_cfg, dict):
        modes_cfg = {}

    modes: dict[str, ModeKeymaps] = {}
    # Process built-in modes first (ensure they always exist).
    for mode_name, cls in _BUILTIN_MODE_CLASSES.items():
        mode_defaults = cls()
        mode_overrides = modes_cfg.get(mode_name, {})
        if not isinstance(mode_overrides, dict):
            modes[mode_name] = mode_defaults
            continue

        prefix = mode_overrides.get("prefix", mode_defaults.prefix)
        if not isinstance(prefix, str):
            prefix = mode_defaults.prefix
        prefix = canonicalize_key_binding(prefix)

        keys_overrides = mode_overrides.get("keys", {})
        if not isinstance(keys_overrides, dict):
            keys_overrides = {}
        elif mode_name == "fold_mode":
            keys_overrides = _migrate_agent_fold_toggle_alias(
                keys_overrides,
                mode_defaults.keys,
            )

        merged_keys = _deep_merge_keys(mode_defaults.keys, keys_overrides)
        merged_keys = _canonicalize_mode_keys(merged_keys)
        if mode_name == "leader_mode":
            merged_keys = {
                name: value
                for name, value in merged_keys.items()
                if name not in _RETIRED_LEADER_KEYS
            }
        modes[mode_name] = cls(prefix=prefix, keys=merged_keys)

    # Process any additional (user-defined) modes.
    for mode_name, mode_data in modes_cfg.items():
        if mode_name in _BUILTIN_MODE_CLASSES:
            continue  # Already handled above.
        if not isinstance(mode_data, dict):
            continue
        prefix = mode_data.get("prefix", "")
        if not isinstance(prefix, str):
            continue
        prefix = canonicalize_key_binding(prefix)
        raw_keys = mode_data.get("keys", {})
        keys: dict[str, str | dict[str, str]] = {}
        if isinstance(raw_keys, dict):
            for k, v in raw_keys.items():
                if not isinstance(v, dict):
                    # Custom mode sub-keys must be dicts with key/shell/action.
                    log.warning(
                        "Custom mode %r sub-key %r: expected dict, got %s; skipping",
                        mode_name,
                        k,
                        type(v).__name__,
                    )
                    continue
                if "key" not in v:
                    log.warning(
                        "Custom mode %r sub-key %r: missing 'key' field; skipping",
                        mode_name,
                        k,
                    )
                    continue
                key_value = v.get("key")
                if not isinstance(key_value, str):
                    log.warning(
                        "Custom mode %r sub-key %r: expected string 'key', got %s; "
                        "skipping",
                        mode_name,
                        k,
                        type(key_value).__name__,
                    )
                    continue
                if "shell" not in v and "action" not in v:
                    log.warning(
                        "Custom mode %r sub-key %r: missing 'shell' or 'action'; "
                        "skipping",
                        mode_name,
                        k,
                    )
                    continue
                spec = {sk: sv for sk, sv in v.items() if isinstance(sv, str)}
                spec["key"] = canonicalize_key_binding(key_value)
                keys[k] = spec
        modes[mode_name] = ModeKeymaps(prefix=prefix, keys=keys)

    registry = KeymapRegistry(
        app=app_km,
        statistics=statistics_km,
        gate=gate_km,
        modes=modes,
    )

    # --- Prefix sync: mode prefix wins over app action ---
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

    # --- Prefix conflict detection for custom modes ---
    # Warn if a custom mode's prefix collides with an app binding.
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


# ---------------------------------------------------------------------------
# Binding builder
# ---------------------------------------------------------------------------

# Non-configurable numbered Artifacts sub-tab bindings.
_ARTIFACT_SUBTAB_BINDINGS: list[Binding] = [
    Binding(
        str(index),
        f"show_artifacts_{subtab}",
        f"Show {subtab.title()}",
        show=False,
    )
    for index, subtab in enumerate(ARTIFACTS_SUBTAB_ORDER, start=1)
]


def build_app_bindings(app_km: AppKeymaps) -> list[Binding]:
    """Generate the Textual ``Binding`` list from an ``AppKeymaps`` instance.

    Preserves the original binding order, descriptions, and priority flags.
    Appends the four non-configurable numbered Artifacts sub-tab bindings.

    Returns:
        List of ``Binding`` objects suitable for ``App.BINDINGS``.
    """
    bindings: list[Binding] = []
    for action, desc, priority in _BINDING_META:
        key = getattr(app_km, action)
        bindings.append(Binding(key, action, desc, show=False, priority=priority))
    bindings.extend(_ARTIFACT_SUBTAB_BINDINGS)
    return bindings


def build_statistics_bindings(keymaps: StatisticsPaneKeymaps) -> list[Binding]:
    """Build instance-local bindings for the focused Statistics pane."""

    return [
        Binding(
            getattr(keymaps, action),
            action,
            description,
            show=False,
        )
        for action, description in _STATISTICS_BINDING_META
    ]


def build_gate_modal_bindings(keymaps: GateModalKeymaps) -> list[Binding]:
    """Build instance-local bindings for a branch-driven gate modal."""

    return [
        Binding(
            getattr(keymaps, action),
            action,
            description,
            show=False,
            priority=True,
        )
        for action, description in _GATE_BINDING_META
    ]


def statistics_help_bindings(
    keymaps: StatisticsPaneKeymaps,
) -> list[tuple[str, str]]:
    """Return effective Statistics keys and descriptions for help surfaces."""

    return [
        (key_display_name(getattr(keymaps, action)), description)
        for action, description in _STATISTICS_BINDING_META
    ]


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def key_display_name(textual_key: str) -> str:
    """Convert a Textual key name to a human-readable display string.

    Examples:
        ``"full_stop"`` -> ``"."``
        ``"ctrl+d"`` -> ``"Ctrl+D"``
        ``"j"`` -> ``"j"``
    """
    alternatives = split_key_alternatives(textual_key)
    if not alternatives or alternatives == ("",):
        return ""
    if len(alternatives) > 1:
        return " / ".join(key_display_name(alternative) for alternative in alternatives)
    textual_key = alternatives[0]
    textual_key = canonicalize_single_key(textual_key)
    if textual_key == "ctrl+@":
        return "Ctrl+Space"
    if textual_key in _KEY_DISPLAY:
        return _KEY_DISPLAY[textual_key]
    key_parts = textual_key.split("+")
    modifiers = {"ctrl": "Ctrl", "shift": "Shift"}
    if len(key_parts) > 1 and all(part in modifiers for part in key_parts[:-1]):
        key_name = _KEY_DISPLAY.get(key_parts[-1], key_parts[-1].upper())
        return "+".join([*(modifiers[part] for part in key_parts[:-1]), key_name])
    return textual_key


def leader_key_display(registry: KeymapRegistry, action_name: str) -> str:
    """Format one configured leader chord for display surfaces."""
    subkey = registry.leader_mode.keys[action_name]
    assert isinstance(subkey, str)
    parts = [
        key_display_name(registry.leader_mode.prefix),
        key_display_name(subkey),
    ]
    if all(len(part) == 1 for part in parts):
        return "".join(parts)
    if len(parts[1]) == 1 and not parts[1].isalnum():
        return "".join(parts)
    return " ".join(parts)


def footer_key_display(textual_key: str) -> str:
    """Convert a Textual key name for footer display.

    Wraps ``key_display_name`` and applies the footer's angle-bracket
    convention for multi-char named keys (``"Space"`` -> ``"<space>"``,
    ``"Enter"`` -> ``"<enter>"``).  Single chars and ``Ctrl+X`` /
    ``Shift+X`` pass through unchanged.
    """
    alternatives = split_key_alternatives(textual_key)
    if len(alternatives) > 1:
        return " / ".join(
            footer_key_display(alternative) for alternative in alternatives
        )
    name = key_display_name(textual_key)
    if len(name) == 1 or name.startswith(("Ctrl+", "Shift+")):
        return name
    return f"<{name.lower()}>"
