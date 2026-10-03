"""Build the app-level keymaps for the TUI keymap registry."""

from dataclasses import fields

from sase.ace.tui.keymaps._registry_shared import log, migrate_key_aliases
from sase.ace.tui.keymaps.app_keymaps import AppKeymaps
from sase.ace.tui.keymaps.defaults import load_builtin_app_defaults
from sase.ace.tui.keymaps.key_validation import (
    canonicalize_key_binding,
    is_unbound_key,
    is_valid_key,
    normalize_key_binding,
    split_key_alternatives,
)


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
        "toggle_layout",
        "toggle_thinking",
        "toggle_thinking_reverse",
        "choose_agent_view",
        "next_agent_metadata_section",
        "prev_agent_metadata_section",
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
    "next_agent_file": "next_chop_run",  # sase-17d legacy Agents detail deletion
    "prev_agent_file": "prev_chop_run",  # sase-17d legacy Agents detail deletion
}


# These app actions intentionally share a key because their tab applicability
# is disjoint. Preserve duplicate validation for every other app-action pairing.
_CONTEXTUAL_APP_DUPLICATES: frozenset[frozenset[str]] = frozenset(
    {
        frozenset({"add_axe_item", "open_artifact_files"}),
        frozenset({"show_diff", "toggle_axe_description"}),
        # Pane-disjoint by construction: Beads vs Files open-externally actions.
        frozenset({"beads_open_bug", "files_open_external"}),
        frozenset({"agents_revive", "beads_launch_work"}),
        frozenset({"agents_revive", "reword"}),
        frozenset({"toggle_relation_panel", "toggle_hide_reverted"}),
        # Tab-disjoint by construction: Agents-only jump panel toggle vs the
        # Services `.` and Artifacts `.` owners.
        frozenset({"toggle_agent_jump_panel", "toggle_hide_reverted"}),
        frozenset({"toggle_agent_jump_panel", "toggle_relation_panel"}),
        frozenset({"open_agent_cleanup_panel", "patches_toggle_reverted"}),
        # Pane-disjoint by construction: Agents-only attempt history vs
        # Artifacts-only pane brief cycling.
        frozenset({"toggle_attempt_view", "cycle_artifacts_description"}),
        # Tab-disjoint by construction: Agents-only header toggle vs the
        # three `d` owners on other tabs.
        frozenset({"toggle_agent_header", "show_diff"}),
        frozenset({"toggle_agent_header", "toggle_axe_description"}),
        frozenset({"toggle_agent_header", "stitches_toggle_sdd"}),
        # Pane-disjoint: Artifacts-only query history cycling
        # vs Agents-only all-panel fold sweep.
        frozenset({"next_query", "collapse_all_panel_folds"}),
        # Tab-disjoint: Agents refresh/retry vs Artifacts/Axe run/refresh.
        frozenset({"agents_refresh", "run_workflow"}),
        frozenset({"agents_retry", "refresh"}),
        # Tab-disjoint: Agents opens a direct picker; Artifacts panes keep
        # forward/reverse grouping cycles.
        frozenset({"choose_agent_grouping", "cycle_grouping_mode"}),
        frozenset({"choose_agent_grouping", "cycle_grouping_mode_reverse"}),
        # Pane-disjoint: Beads has no grouping mode, so ``O`` opens cached
        # bead attachments there while grouping panes keep the reverse cycle.
        frozenset({"beads_open_attachments", "cycle_grouping_mode_reverse"}),
        # Tab-disjoint: Agents vs Services panel jumps share J/K.
        frozenset({"focus_next_agent_panel", "focus_next_service_panel"}),
        frozenset({"focus_prev_agent_panel", "focus_prev_service_panel"}),
        # Tab-disjoint: Agents deck keys vs Artifacts paging share Ctrl+J/K.
        frozenset({"next_deck_card", "artifacts_load_more"}),
        frozenset({"prev_deck_card", "artifacts_unload"}),
        # Tab-disjoint: Agents deck selection vs Services job-run selection.
        frozenset({"next_deck", "next_chop_run"}),
        frozenset({"prev_deck", "prev_chop_run"}),
        # Tab-disjoint: Agents deck close vs Services job-run selection.
        frozenset({"close_deck_panel", "prev_chop_run"}),
        # Tab-disjoint: Agents deck picker vs Artifacts project scope.
        frozenset({"pick_deck", "pick_artifacts_project"}),
        # Tab-disjoint: Agents vs Services/Artifacts.
        frozenset({"toggle_deck_focus", "scroll_prompt_down"}),
        frozenset({"toggle_deck_focus_reverse", "scroll_prompt_up"}),
        # Tab-disjoint: Agents deck turn vs Beads note audience toggle.
        frozenset({"turn_deck_layout", "beads_toggle_note_audience"}),
        # Tab-disjoint: Agents deck ratio vs Artifacts split cycling.
        frozenset({"grow_deck_panel", "cycle_artifacts_split"}),
        frozenset({"shrink_deck_panel", "cycle_artifacts_split_reverse"}),
        # Tab-disjoint: Agents card-block stepping vs Artifacts Files
        # version stepping. Both use ( / ) on different main tabs.
        frozenset({"next_card_block", "files_next_version"}),
        frozenset({"prev_card_block", "files_prev_version"}),
        # Tab-disjoint: Agents tab cycling shares ]/[ with the Artifacts
        # sub-tab cycle on different main tabs.
        frozenset({"next_agents_tab", "cycle_artifacts_subtab"}),
        frozenset({"prev_agents_tab", "cycle_artifacts_subtab_reverse"}),
    }
)


# Stale slots from the Agents `/` vs `,/` shortcut swap. Drop them with a
# targeted warning so they cannot reappear as runnable commands, and do not
# translate either override into a second live shortcut.
_RELOCATED_APP_KEYS: dict[str, str] = {
    "search_forward": (
        "Ignoring stale app keymap action 'search_forward'; "
        "metadata search is now ace.keymaps.modes.leader_mode.keys.search_forward"
    ),
}


def build_app_keymaps(ace_cfg: dict) -> tuple[AppKeymaps, dict, frozenset[str]]:
    """Build the app-level keymaps from the merged ``ace`` config section.

    All app-level keybindings must be defined in configuration files. Missing
    bindings cause a ``ValueError`` at startup so ``default_config.yml`` stays
    in sync with ``AppKeymaps``.

    Returns the ``AppKeymaps``, the normalized ``keymaps`` config section for
    the remaining builder stages, and the legacy card-block bracket overrides
    that survived duplicate validation.
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
        app_overrides = migrate_key_aliases(
            app_overrides,
            LEGACY_APP_KEY_ALIASES,
            context="app",
        )
        for retired_name in sorted(_RETIRED_APP_KEYS & app_overrides.keys()):
            app_overrides.pop(retired_name)
            log.debug("Ignoring retired app keymap action: %s", retired_name)
        for relocated_name, message in _RELOCATED_APP_KEYS.items():
            if relocated_name in app_overrides:
                app_overrides.pop(relocated_name)
                log.warning("%s", message)

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
    explicitly_configured = set(app_overrides) & app_field_names
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

    _LEGACY_CARD_BLOCK_BRACKETS = frozenset(
        {"left_square_bracket", "right_square_bracket", "[", "]"}
    )
    legacy_card_block_brackets = sorted(
        fname
        for fname in ("next_card_block", "prev_card_block")
        if fname in user_overridden
        and any(
            part in _LEGACY_CARD_BLOCK_BRACKETS
            for part in split_key_alternatives(app_kwargs[fname])
        )
    )
    # Legacy bracket yield (tab-state-keys phase): unbind only the tab action
    # whose bracket collides with a card-block bracket override. Presence in
    # config counts as explicit even when the value equals the default.
    yielded_tab_actions: list[str] = []
    for _agents_tab_action, _bracket in (
        ("next_agents_tab", "right_square_bracket"),
        ("prev_agents_tab", "left_square_bracket"),
    ):
        card_block_uses_bracket = any(
            _bracket in split_key_alternatives(app_kwargs.get(_card_action, ""))
            for _card_action in legacy_card_block_brackets
        )
        if (
            card_block_uses_bracket
            and _agents_tab_action not in explicitly_configured
            and _bracket
            in split_key_alternatives(app_kwargs.get(_agents_tab_action, ""))
        ):
            app_kwargs[_agents_tab_action] = "unbound"
            yielded_tab_actions.append(_agents_tab_action)
    legacy_bracket_pairs = frozenset(
        {
            frozenset({"next_card_block", "cycle_artifacts_subtab"}),
            frozenset({"prev_card_block", "cycle_artifacts_subtab_reverse"}),
        }
    )

    def _allowlisted(pair: frozenset[str]) -> bool:
        if pair in _CONTEXTUAL_APP_DUPLICATES:
            return True
        # Legacy bracket overrides keep working alongside the Artifacts
        # sub-tab cycle keys instead of reverting to the new defaults.
        return pair in legacy_bracket_pairs and bool(
            legacy_card_block_brackets and pair & frozenset(legacy_card_block_brackets)
        )

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
                if action != fname and not _allowlisted(frozenset({fname, action}))
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

    remaining_legacy_brackets = [
        fname
        for fname in legacy_card_block_brackets
        if any(
            part in _LEGACY_CARD_BLOCK_BRACKETS
            for part in split_key_alternatives(app_kwargs.get(fname, ""))
        )
    ]
    if remaining_legacy_brackets or yielded_tab_actions:
        message = "Card-block stepping moved from [ / ] to ( / )"
        if remaining_legacy_brackets:
            message += (
                f"; explicit bracket override(s) for "
                f"{', '.join(remaining_legacy_brackets)} are honored, "
                "but prefer left_parenthesis/right_parenthesis"
            )
        else:
            message += "; prefer left_parenthesis/right_parenthesis"
        if yielded_tab_actions:
            message += "; agent tab cycling yielded the brackets"
        log.warning("%s", message)

    app_km = AppKeymaps(**app_kwargs)
    return app_km, keymaps_cfg, frozenset(legacy_card_block_brackets)
