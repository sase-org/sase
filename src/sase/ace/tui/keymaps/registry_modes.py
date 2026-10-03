"""Build the prefix-key modes for the TUI keymap registry."""

from sase.ace.tui.keymaps._registry_shared import log, migrate_key_aliases
from sase.ace.tui.keymaps.key_validation import canonicalize_key_binding
from sase.ace.tui.keymaps.mode_keymaps import _BUILTIN_MODE_CLASSES, ModeKeymaps


_LEGACY_FOLD_KEY_ALIASES: dict[str, str] = {
    "cycle_commits": "cycle_stitches",
    "toggle_commits": "toggle_stitches",
}


# Retired built-in leader-mode action ids. These are dropped while loading so a
# stale user override cannot deep-merge a removed command back into the registry.
# ``kill_marked_and_edit`` was folded into the contextual ``kill_and_edit``
# (``,x``) action; ``restore_prompt_stash`` (the old global ``,P``) was replaced
# by the app-level ``@`` binding and prompt-local ``Ctrl+G p`` panel opener;
# ``mark_inactive`` / ``mark_inactive_pinned`` / ``activity_info`` were removed
# with the former user-presence dashboard; ``log_panel`` moved into the
# Admin Center Logs tab and is opened via command palette or ``#``;
# ``task_queue`` moved into the Admin Center Procs tab;
# ``toggle_selected_agent_panels`` moved to the app-level ``L`` action;
# ``show_help`` returned to the app-level ``?`` binding.
_RETIRED_LEADER_KEYS: frozenset[str] = frozenset(
    {
        "show_help",
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


_RELOCATED_LEADER_KEYS: dict[str, str] = {
    "edit_query": (
        "Ignoring stale leader_mode.keys.edit_query; "
        "Agents query editing is now ace.keymaps.app.edit_query"
    ),
    "toggle_agent_panel_grouping": (
        "Ignoring stale leader_mode.keys.toggle_agent_panel_grouping; "
        "agent panel layout now lives under ace.keymaps.app.choose_agent_grouping, "
        "then local picker key 'o'"
    ),
    "jump_to_notification": (
        "Ignoring stale leader_mode.keys.jump_to_notification; "
        "open an agent's pending gate with ace.keymaps.app.act_on_agent (Enter) "
        "on the Agents tab"
    ),
}


_LEGACY_COPY_GROUP_ALIASES: dict[str, str] = {
    "changespecs": "patches",  # legacy compatibility alias
    "artifacts_commits": "artifacts_stitches",  # legacy compatibility alias
}


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


def _migrate_copy_group_aliases(
    keys: dict[str, str | dict[str, str]],
) -> dict[str, str | dict[str, str]]:
    """Normalize legacy copy-mode group ids to canonical groups."""
    migrated = dict(keys)
    for legacy_name, canonical_name in _LEGACY_COPY_GROUP_ALIASES.items():
        if legacy_name not in migrated:
            continue
        legacy_value = migrated.pop(legacy_name)
        if canonical_name in migrated:
            log.warning(
                "copy_mode group %r is deprecated and ignored because %r is configured",
                legacy_name,
                canonical_name,
            )
            continue
        if not isinstance(legacy_value, dict):
            log.warning(
                "copy_mode group %r is deprecated but ignored because its "
                "value is not a mapping",
                legacy_name,
            )
            continue
        migrated[canonical_name] = legacy_value
        log.warning(
            "copy_mode group %r is deprecated; treating it as %r",
            legacy_name,
            canonical_name,
        )
    return migrated


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


def build_mode_keymaps(keymaps_cfg: dict) -> dict[str, ModeKeymaps]:
    """Build the prefix-key modes from the ``keymaps`` config section."""
    modes_cfg = keymaps_cfg.get("modes", {})
    if not isinstance(modes_cfg, dict):
        modes_cfg = {}

    modes: dict[str, ModeKeymaps] = {}
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
        else:
            keys_overrides = dict(keys_overrides)
            if mode_name == "fold_mode":
                keys_overrides = migrate_key_aliases(
                    keys_overrides,
                    _LEGACY_FOLD_KEY_ALIASES,
                    context="fold_mode",
                )
                keys_overrides = _migrate_agent_fold_toggle_alias(
                    keys_overrides,
                    mode_defaults.keys,
                )
            elif mode_name == "copy_mode":
                keys_overrides = _migrate_copy_group_aliases(keys_overrides)

        merged_keys = _deep_merge_keys(mode_defaults.keys, keys_overrides)
        merged_keys = _canonicalize_mode_keys(merged_keys)
        if mode_name == "leader_mode":
            for relocated_name, message in _RELOCATED_LEADER_KEYS.items():
                if relocated_name in merged_keys:
                    # Only warn when the user actually overrode the retired
                    # slot. Defaults no longer include it, so presence after
                    # merge means a stale config key survived deep-merge.
                    if relocated_name in keys_overrides:
                        log.warning("%s", message)
                    merged_keys.pop(relocated_name)
            merged_keys = {
                name: value
                for name, value in merged_keys.items()
                if name not in _RETIRED_LEADER_KEYS
            }
        modes[mode_name] = cls(prefix=prefix, keys=merged_keys)

    for mode_name, mode_data in modes_cfg.items():
        if mode_name in _BUILTIN_MODE_CLASSES or not isinstance(mode_data, dict):
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

    return modes
