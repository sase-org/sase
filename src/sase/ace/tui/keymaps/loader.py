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

import yaml  # type: ignore[import-untyped]
from textual.binding import Binding

from sase.ace.tui.keymaps.types import (
    _BUILTIN_MODE_CLASSES,
    _KEY_DISPLAY,
    _MODE_PREFIX_ACTIONS,
    KeymapRegistry,
    AppKeymaps,
    ModeKeymaps,
    is_valid_key,
)

# Re-import _BINDING_META so build_app_bindings can use it.
from sase.ace.tui.keymaps.types import _BINDING_META

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Defaults loader
# ---------------------------------------------------------------------------


@functools.cache
def _builtin_app_defaults() -> Mapping[str, str]:
    """Parse and cache the app-level keymap defaults as an immutable mapping.

    This file is the **single source of truth** for default keybindings.
    Adding a new field to ``AppKeymaps`` without a corresponding entry in
    ``default_config.yml`` will cause startup to fail.
    """
    ref = importlib.resources.files("sase").joinpath("default_config.yml")
    text = ref.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        msg = "default_config.yml is not a valid YAML mapping"
        raise RuntimeError(msg)
    app = data.get("ace", {}).get("keymaps", {}).get("app", {})
    if not isinstance(app, dict):
        msg = "default_config.yml missing ace.keymaps.app section"
        raise RuntimeError(msg)
    return MappingProxyType({k: str(v) for k, v in app.items()})


def load_builtin_app_defaults() -> dict[str, str]:
    """Load app-level keymap defaults from the bundled ``default_config.yml``.

    Returns a fresh ``dict`` per call; callers may freely mutate it without
    corrupting the cached parse.
    """
    return dict(_builtin_app_defaults())


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
            app_kwargs[fname] = app_overrides[fname]
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
        if not is_valid_key(app_kwargs[fname]):
            default_val = builtin_defaults[fname]
            log.warning(
                "Invalid key %r for action %r; reverting to default %r",
                app_kwargs[fname],
                fname,
                default_val,
            )
            app_kwargs[fname] = default_val
            user_overridden.discard(fname)

    # Duplicate key detection: revert user overrides that conflict.
    key_to_actions: dict[str, list[str]] = {}
    for fname, key_val in app_kwargs.items():
        key_to_actions.setdefault(key_val, []).append(fname)

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

        keys_overrides = mode_overrides.get("keys", {})
        if not isinstance(keys_overrides, dict):
            keys_overrides = {}

        merged_keys = _deep_merge_keys(mode_defaults.keys, keys_overrides)
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
                if "shell" not in v and "action" not in v:
                    log.warning(
                        "Custom mode %r sub-key %r: missing 'shell' or 'action'; "
                        "skipping",
                        mode_name,
                        k,
                    )
                    continue
                keys[k] = {sk: sv for sk, sv in v.items() if isinstance(sv, str)}
        modes[mode_name] = ModeKeymaps(prefix=prefix, keys=keys)

    registry = KeymapRegistry(app=app_km, modes=modes)

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
    app_keys: set[str] = {getattr(registry.app, f.name) for f in fields(AppKeymaps)}
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

# Non-configurable digit bindings for saved queries.
_DIGIT_BINDINGS: list[Binding] = [
    Binding(str(d), f"load_saved_query_{d}", f"Load Q{d}", show=False)
    for d in [1, 2, 3, 4, 5, 6, 7, 8, 9, 0]
]


def build_app_bindings(app_km: AppKeymaps) -> list[Binding]:
    """Generate the Textual ``Binding`` list from an ``AppKeymaps`` instance.

    Preserves the original binding order, descriptions, and priority flags.
    Appends the 10 non-configurable digit bindings for saved queries.

    Returns:
        List of ``Binding`` objects suitable for ``App.BINDINGS``.
    """
    bindings: list[Binding] = []
    for action, desc, priority in _BINDING_META:
        key = getattr(app_km, action)
        bindings.append(Binding(key, action, desc, show=False, priority=priority))
    bindings.extend(_DIGIT_BINDINGS)
    return bindings


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
    if textual_key in _KEY_DISPLAY:
        return _KEY_DISPLAY[textual_key]
    if textual_key.startswith("ctrl+"):
        return f"Ctrl+{textual_key[5:].upper()}"
    return textual_key


def footer_key_display(textual_key: str) -> str:
    """Convert a Textual key name for footer display.

    Wraps ``key_display_name`` and applies the footer's angle-bracket
    convention for multi-char named keys (``"Space"`` -> ``"<space>"``,
    ``"Enter"`` -> ``"<enter>"``).  Single chars and ``Ctrl+X`` /
    ``Shift+X`` pass through unchanged.
    """
    name = key_display_name(textual_key)
    if len(name) == 1 or name.startswith(("Ctrl+", "Shift+")):
        return name
    return f"<{name.lower()}>"
