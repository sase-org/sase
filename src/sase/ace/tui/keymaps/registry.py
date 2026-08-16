"""Construct and validate the complete ace TUI keymap registry."""

import logging
from dataclasses import fields

from sase.ace.tui.keymaps.defaults import load_builtin_app_defaults
from sase.ace.tui.keymaps.scopes import load_gate_keymaps, load_statistics_keymaps
from sase.ace.tui.keymaps.app_keymaps import AppKeymaps
from sase.ace.tui.keymaps.key_validation import (
    canonicalize_key_binding,
    is_unbound_key,
    is_valid_key,
    normalize_key_binding,
    split_key_alternatives,
)
from sase.ace.tui.keymaps.metadata import _MODE_PREFIX_ACTIONS
from sase.ace.tui.keymaps.mode_keymaps import _BUILTIN_MODE_CLASSES, ModeKeymaps
from sase.ace.tui.keymaps.types import KeymapRegistry

log = logging.getLogger(__name__)


# Retired app-level action ids. Drop stale user overrides quietly so configs
# from before the leader-chord remap continue to load without warnings.
_RETIRED_APP_KEYS: frozenset[str] = frozenset(
    {
        "plans_expand",
        "plans_collapse",
        "plans_cycle_status",
        "plans_edit_bead",
        "plans_launch_epic",
        "plans_open_bug",
        "cycle_files_subtab",
        "cycle_files_subtab_reverse",
        "next_bug",
        "prev_bug",
        "cycle_bug_filter",
        "create_bug",
        "edit_bug",
        "toggle_bug_state",
        "open_bug",
        "copy_bug",
        "start_agent_from_bug",
        "focus_bug_links",
        "activate_bug_link",
        "refresh_bugs",
    }
)


LEGACY_APP_KEY_ALIASES: dict[str, str] = {
    "next_changespec": "next_patch",  # legacy compatibility alias
    "prev_changespec": "prev_patch",  # legacy compatibility alias
    "start_agent_from_changespec": "start_agent_from_patch",  # legacy compatibility alias
    "jump_to_agent_changespec": "jump_to_agent_patch",  # legacy compatibility alias
    "commits_next": "stitches_next",  # legacy compatibility alias
    "commits_prev": "stitches_prev",  # legacy compatibility alias
    "commits_view_selected": "stitches_view_selected",  # legacy compatibility alias
    "commits_copy_sha": "stitches_copy_sha",  # legacy compatibility alias
    "commits_filters": "stitches_filters",  # legacy compatibility alias
    "commits_toggle_sdd": "stitches_toggle_sdd",  # legacy compatibility alias
    "commits_cycle_merges": "stitches_cycle_merges",  # legacy compatibility alias
    "commits_toggle_all_projects": "stitches_toggle_all_projects",  # legacy compatibility alias
    "commits_fetch": "stitches_fetch",  # legacy compatibility alias
    "commits_refresh": "stitches_refresh",  # legacy compatibility alias
    "stitches_refresh": "refresh",  # legacy compatibility alias (sase-m6.9 keymap unification)
    "plans_refresh": "refresh",  # legacy compatibility alias (sase-m6.9 keymap unification)
    "beads_refresh": "refresh",  # legacy compatibility alias (sase-m6.9 keymap unification)
    "files_refresh": "refresh",  # legacy compatibility alias (sase-m6.9 keymap unification)
    "stitches_copy_sha": "artifacts_copy_reference",  # legacy compatibility alias (sase-m6.9 keymap unification)
    "beads_copy_bug": "artifacts_copy_reference",  # legacy compatibility alias (sase-m6.9 keymap unification)
    "files_copy_reference": "artifacts_copy_reference",  # legacy compatibility alias (sase-m6.9 keymap unification)
}


_LEGACY_FOLD_KEY_ALIASES: dict[str, str] = {
    "cycle_commits": "cycle_stitches",
    "toggle_commits": "toggle_stitches",
}


# These app actions intentionally share a key because their tab applicability
# is disjoint: metadata search is Agents-only, while query editing excludes
# Agents. Preserve duplicate validation for every other app-action pairing.
_CONTEXTUAL_APP_DUPLICATES: frozenset[frozenset[str]] = frozenset(
    {
        frozenset({"edit_query", "search_forward"}),
        frozenset({"add_axe_item", "open_artifact_files"}),
        frozenset({"show_diff", "toggle_axe_description"}),
        frozenset({"beads_open_plan", "plans_open_bead"}),
    }
)


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


def _migrate_key_aliases(
    keys: dict[str, str | dict[str, str]],
    aliases: dict[str, str],
    *,
    context: str,
) -> dict[str, str | dict[str, str]]:
    """Normalize legacy keymap action ids to their canonical names."""
    migrated = dict(keys)
    for legacy_name, canonical_name in aliases.items():
        if legacy_name not in migrated:
            continue
        legacy_value = migrated.pop(legacy_name)
        if canonical_name in migrated:
            log.warning(
                "%s keymap action %r is deprecated and ignored because %r is "
                "configured",
                context,
                legacy_name,
                canonical_name,
            )
            continue
        migrated[canonical_name] = legacy_value
        log.warning(
            "%s keymap action %r is deprecated; treating it as %r",
            context,
            legacy_name,
            canonical_name,
        )
    return migrated


_LEGACY_COPY_GROUP_ALIASES: dict[str, str] = {
    "changespecs": "patches",  # legacy compatibility alias
    "artifacts_commits": "artifacts_stitches",  # legacy compatibility alias
}


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


def load_keymap_registry(ace_cfg: dict) -> KeymapRegistry:
    """Build a ``KeymapRegistry`` from the merged ``ace`` config section.

    All app-level keybindings must be defined in configuration files. Missing
    bindings cause a ``ValueError`` at startup so ``default_config.yml`` stays
    in sync with ``AppKeymaps``.
    """
    builtin_defaults = load_builtin_app_defaults()
    app_field_names = {f.name for f in fields(AppKeymaps)}

    missing_from_defaults = sorted(app_field_names - set(builtin_defaults.keys()))
    if missing_from_defaults:
        raise ValueError(
            "default_config.yml missing app keymaps: "
            f"{', '.join(missing_from_defaults)}. "
            "Add these under ace.keymaps.app."
        )

    keymaps_cfg = ace_cfg.get("keymaps", {})
    if not isinstance(keymaps_cfg, dict):
        keymaps_cfg = {}

    app_overrides = keymaps_cfg.get("app", {})
    if not isinstance(app_overrides, dict):
        app_overrides = {}
    else:
        app_overrides = dict(app_overrides)
        app_overrides = _migrate_key_aliases(
            app_overrides,
            LEGACY_APP_KEY_ALIASES,
            context="app",
        )
        for retired_name in sorted(_RETIRED_APP_KEYS & app_overrides.keys()):
            app_overrides.pop(retired_name)
            log.debug("Ignoring retired app keymap action: %s", retired_name)

    extra = sorted(set(app_overrides.keys()) - app_field_names)
    if extra:
        log.warning(
            "Unknown keymap action(s) in config (ignored): %s",
            ", ".join(extra),
        )

    app_kwargs: dict[str, str] = {}
    for fname in app_field_names:
        if fname in app_overrides and isinstance(app_overrides[fname], str):
            app_kwargs[fname] = canonicalize_key_binding(app_overrides[fname])
        else:
            app_kwargs[fname] = builtin_defaults[fname]

    user_overridden = {
        fname
        for fname in app_field_names
        if app_kwargs[fname] != builtin_defaults[fname]
    }
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

    key_to_actions: dict[str, list[str]] = {}
    for fname, key_val in app_kwargs.items():
        if is_unbound_key(key_val):
            continue
        for key_part in split_key_alternatives(key_val):
            key_to_actions.setdefault(key_part, []).append(fname)

    for key_val, actions in key_to_actions.items():
        if len(actions) <= 1:
            continue
        overridden = [a for a in actions if a in user_overridden]
        if not overridden:
            continue
        for fname in overridden:
            conflicts = [
                action
                for action in actions
                if action != fname
                and frozenset({fname, action}) not in _CONTEXTUAL_APP_DUPLICATES
            ]
            if not conflicts:
                continue
            default_val = builtin_defaults[fname]
            log.warning(
                "Duplicate key %r: action %r conflicts with %s; "
                "reverting to default %r",
                key_val,
                fname,
                conflicts,
                default_val,
            )
            app_kwargs[fname] = default_val

    app_km = AppKeymaps(**app_kwargs)
    statistics_km = load_statistics_keymaps(keymaps_cfg)
    gate_km = load_gate_keymaps(keymaps_cfg)

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
                keys_overrides = _migrate_key_aliases(
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

    registry = KeymapRegistry(
        app=app_km,
        statistics=statistics_km,
        gate=gate_km,
        modes=modes,
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
