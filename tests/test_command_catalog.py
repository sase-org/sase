"""Tests for the ace TUI command catalog (Phase 1).

Verifies that :func:`build_command_catalog` produces a stable list of
:class:`CommandSpec` entries that:

- Cover every :class:`AppKeymaps` field exactly once.
- Include all 10 saved-query picker sequences.
- Cover every built-in mode subkey (fold, copy nested per-tab, leader,
  bang) and every valid user-defined custom mode command.
- Carry a non-empty key sequence and a stable id.
"""

from __future__ import annotations

from dataclasses import fields

from sase.ace.tui.commands import (
    CommandSpec,
    build_command_catalog,
    iter_app_commands,
    iter_digit_commands,
    iter_mode_commands,
)
from sase.ace.tui.commands.catalog import _format_key_sequence
from sase.ace.tui.keymaps import (
    AppKeymaps,
    KeymapRegistry,
    load_builtin_app_defaults,
    load_keymap_registry,
)


def _registry() -> KeymapRegistry:
    return load_keymap_registry({})


# --- App command coverage ---


def test_every_app_keymap_has_a_command_spec() -> None:
    """Every AppKeymaps field must be represented exactly once."""
    catalog = list(iter_app_commands(_registry()))
    seen = {c.id for c in catalog}
    expected = {f"app.{f.name}" for f in fields(AppKeymaps)}
    assert seen == expected


def test_app_command_spec_uses_configured_key() -> None:
    """A CommandSpec's key sequence must reflect the merged keymap."""
    reg = load_keymap_registry({"keymaps": {"app": {"next_changespec": "B"}}})
    by_id = {c.id: c for c in iter_app_commands(reg)}
    assert by_id["app.next_changespec"].key_sequence == ("B",)
    assert by_id["app.next_changespec"].key_display == "B"


def test_open_command_palette_command_uses_default_alternatives() -> None:
    """The palette opener command picks up both default key alternatives."""
    by_id = {c.id: c for c in iter_app_commands(_registry())}
    spec = by_id["app.open_command_palette"]
    assert spec.key_sequence == ("colon,semicolon",)
    assert spec.key_display == ": / ;"


def test_jump_commands_use_back_and_forward_defaults_on_every_tab() -> None:
    """The palette exposes the jump-stack pair on every tab."""
    by_id = {c.id: c for c in iter_app_commands(_registry())}
    spec = by_id["app.jump_to_entry_fast"]
    forward = by_id["app.jump_to_entry_forward"]

    assert spec.label == "Fast jump to entry"
    assert spec.key_sequence == ("ctrl+o",)
    assert spec.key_display == "Ctrl+O"
    assert forward.label == "Jump forward through jump stack"
    assert forward.key_sequence == ("ctrl+shift+o",)
    assert forward.key_display == "Ctrl+Shift+O"
    assert forward.tabs == ("changespecs", "agents", "axe")
    assert "ctrl+shift+o" in forward.aliases
    assert "ctrl+k" not in forward.aliases
    assert by_id["app.next_agent_metadata_section"].tabs == ("agents",)
    assert by_id["app.prev_agent_metadata_section"].tabs == ("agents",)
    assert "app.prev_changespec_history" not in by_id
    assert "app.next_changespec_history" not in by_id


def test_last_vcs_xprompt_editor_command_is_all_tab_agent_command() -> None:
    """The Ctrl+G MRU editor action is discoverable on every tab."""
    by_id = {c.id: c for c in iter_app_commands(_registry())}
    spec = by_id["app.start_last_vcs_xprompt_in_editor"]
    assert spec.label == "Edit last VCS xprompt"
    assert spec.category == "Agents"
    assert spec.tabs == ("changespecs", "agents", "axe")
    assert spec.key_sequence == ("ctrl+g",)
    assert spec.key_display == "Ctrl+G"


def test_start_custom_agent_command_uses_plus() -> None:
    """The custom-agent launcher command exposes ``+`` and a ``+`` alias."""
    by_id = {c.id: c for c in iter_app_commands(_registry())}
    spec = by_id["app.start_custom_agent"]

    assert spec.label == "Run custom agent"
    assert spec.key_sequence == ("plus",)
    assert spec.key_display == "+"
    assert "+" in spec.aliases
    assert "@" not in spec.aliases


def test_restore_prompt_stash_command_is_all_tab_at_keymap() -> None:
    """The global prompt-stash restore command exposes ``@`` on every tab."""
    by_id = {c.id: c for c in iter_app_commands(_registry())}
    spec = by_id["app.restore_prompt_stash"]

    assert spec.label == "Restore stashed prompt"
    assert spec.category == "Agents"
    assert spec.tabs == ("changespecs", "agents", "axe")
    assert spec.key_sequence == ("at",)
    assert spec.key_display == "@"
    assert spec.executor.kind == "app_action"
    assert spec.executor.action == "restore_prompt_stash"
    assert "stash" in spec.aliases
    assert "pop" in spec.aliases
    assert "gP" not in spec.aliases


def test_start_agent_from_changespec_command_uses_ctrl_space() -> None:
    """The repeat-last agent command exposes Ctrl+Space, not bare Space."""
    by_id = {c.id: c for c in iter_app_commands(_registry())}
    spec = by_id["app.start_agent_from_changespec"]

    assert spec.label == "Run agent from PR"
    assert spec.key_sequence == ("ctrl+@",)
    assert spec.key_display == "Ctrl+Space"


def test_start_agent_home_command_uses_bare_space() -> None:
    """The home-agent app command exposes bare Space."""
    by_id = {c.id: c for c in iter_app_commands(_registry())}
    spec = by_id["app.start_agent_home"]

    assert spec.label == "Run agent (home mode)"
    assert spec.category == "Agents"
    assert spec.tabs == ("changespecs", "agents", "axe")
    assert spec.key_sequence == ("space",)
    assert spec.key_display == "Space"
    assert spec.executor.kind == "app_action"
    assert spec.executor.action == "start_agent_home"


def test_run_workflow_command_is_contextual_retry_on_agents() -> None:
    by_id = {c.id: c for c in iter_app_commands(_registry())}
    spec = by_id["app.run_workflow"]

    assert spec.label == "Run workflow / retry agent / re-run"
    assert spec.tabs == ("changespecs", "agents", "axe")
    assert spec.key_sequence == ("r",)
    assert spec.key_display == "r"
    assert "retry" in spec.aliases


def test_add_tag_command_is_contextual_wait_on_agents() -> None:
    by_id = {c.id: c for c in iter_app_commands(_registry())}
    spec = by_id["app.add_tag"]

    assert spec.label == "Add tag / wait for agent, clan, or tribe"
    assert spec.tabs == ("changespecs", "agents")
    assert spec.key_sequence == ("W",)
    assert "wait for agent" in spec.aliases
    assert "wait for clan" in spec.aliases
    assert "wait for tribe" in spec.aliases


def test_pr_sync_commands_use_pr_labels() -> None:
    by_id = {c.id: c for c in iter_app_commands(_registry())}

    assert by_id["app.rebase"].label == "Rebase PR"
    assert by_id["app.start_rewind"].label == "Rewind PR / Revive agent"


def test_bulk_change_status_command_is_changespec_only() -> None:
    by_id = {c.id: c for c in iter_app_commands(_registry())}
    spec = by_id["app.bulk_change_status"]

    assert spec.label == "Bulk status change"
    assert spec.tabs == ("changespecs",)


def test_save_marked_agents_command_covers_agent_save_flow() -> None:
    by_id = {c.id: c for c in iter_app_commands(_registry())}
    spec = by_id["app.save_marked_agents"]

    assert spec.label == "Save/dismiss marked agents"
    assert spec.tabs == ("agents",)
    assert spec.key_sequence == ("s",)
    assert "save marked" in spec.aliases
    assert "dismiss marked" in spec.aliases
    assert "name group" in spec.aliases
    assert "saved group name" in spec.aliases


def test_zoom_panel_command_is_agents_only_display_command() -> None:
    by_id = {c.id: c for c in iter_app_commands(_registry())}
    spec = by_id["app.zoom_panel"]

    assert spec.label == "Zoom largest panel"
    assert spec.category == "Display"
    assert spec.tabs == ("agents",)
    assert spec.key_sequence == ("Z",)
    assert spec.key_display == "Z"
    assert "zoom" in spec.aliases


def test_capital_h_command_describes_contextual_panel_isolation() -> None:
    by_id = {c.id: c for c in iter_app_commands(_registry())}
    spec = by_id["app.hooks_or_collapse_all"]

    assert spec.label == (
        "Show only or restore tribe panels / collapse group or all folds / "
        "compact tools detail"
    )
    assert spec.key_sequence == ("H",)
    assert spec.key_display == "H"


# --- Saved-query commands ---


def test_saved_query_commands_cover_all_prefixed_slots() -> None:
    queries = list(iter_digit_commands(_registry()))
    assert {c.id for c in queries} == {f"saved_query.{d}" for d in range(10)}
    assert all(c.executor.kind == "saved_query" for c in queries)
    assert all(c.key_sequence[0] == "asterisk" for c in queries)
    assert {c.key_display for c in queries} == {
        "*1",
        "*2",
        "*3",
        "*4",
        "*5",
        "*6",
        "*7",
        "*8",
        "*9",
        "*0",
    }


def test_saved_query_commands_follow_configured_picker_prefix() -> None:
    registry = load_keymap_registry(
        {"keymaps": {"app": {"open_saved_query_picker": "P"}}}
    )
    queries = list(iter_digit_commands(registry))
    assert queries[0].key_sequence == ("P", "1")
    assert queries[0].key_display == "P1"


# --- Built-in mode coverage ---


def test_fold_mode_commands_cover_every_subkey() -> None:
    reg = _registry()
    fold_specs = [
        c
        for c in iter_mode_commands(reg)
        if c.id.startswith("fold.") and c.executor.kind == "fold_mode_key"
    ]
    expected = {
        f"fold.{cid}"
        for cid, subkey in reg.fold_mode.keys.items()
        if isinstance(subkey, str)
    }
    agent_keys = reg.fold_mode.keys["agents"]
    assert isinstance(agent_keys, dict)
    expected.update(f"fold.agents.{cid}" for cid in agent_keys)
    assert {c.id for c in fold_specs} == expected
    # Every fold key sequence is (z, subkey)
    for spec in fold_specs:
        assert spec.key_sequence[0] == reg.fold_mode.prefix
        assert len(spec.key_sequence) == 2

    by_id = {spec.id: spec for spec in fold_specs}
    assert by_id["fold.cycle_commits"].tabs == ("changespecs",)
    assert by_id["fold.agents.cycle_level"].tabs == ("agents",)
    assert by_id["fold.agents.toggle_all"].label == "Toggle all metadata folds"
    assert "fold.agents.cycle_level_back" not in by_id
    assert by_id["fold.set_level_3"].label == "Set all folds to level 3"
    assert by_id["fold.agents.set_level_4"].label == ("Set metadata panel fold level 4")


def test_copy_mode_commands_per_tab_scope() -> None:
    reg = _registry()
    copy_specs = [
        c
        for c in iter_mode_commands(reg)
        if c.id.startswith("copy.") and c.executor.kind == "copy_mode_key"
    ]
    by_id = {c.id: c for c in copy_specs}
    # Each per-tab subdict produces commands tagged with that single tab.
    assert by_id["copy.changespecs.bug"].tabs == ("changespecs",)
    assert by_id["copy.agents.name"].tabs == ("agents",)
    assert by_id["copy.axe.visible"].tabs == ("axe",)
    # Coverage for every nested key.
    expected: set[str] = set()
    for tab_name, sub in reg.copy_mode.keys.items():
        if isinstance(sub, dict):
            for cid in sub:
                expected.add(f"copy.{tab_name}.{cid}")
    assert {c.id for c in copy_specs} == expected


def test_leader_mode_commands_cover_every_subkey() -> None:
    reg = _registry()
    leader_specs = [c for c in iter_mode_commands(reg) if c.id.startswith("leader.")]
    expected = {f"leader.{cid}" for cid in reg.leader_mode.keys}
    assert {c.id for c in leader_specs} == expected
    assert "leader.retry_edit" not in {c.id for c in leader_specs}


def test_bang_mode_commands_cover_every_subkey() -> None:
    reg = _registry()
    bang_specs = [c for c in iter_mode_commands(reg) if c.id.startswith("bang.")]
    expected = {f"bang.{cid}" for cid in reg.bang_mode.keys}
    assert {c.id for c in bang_specs} == expected


def test_custom_mode_commands_included() -> None:
    reg = load_keymap_registry(
        {
            "keymaps": {
                "modes": {
                    "my_mode": {
                        "prefix": "semicolon",
                        "keys": {
                            "do_thing": {
                                "key": "t",
                                "shell": "echo hi",
                                "description": "Do a thing",
                            },
                        },
                    },
                },
            },
        }
    )
    specs = [c for c in iter_mode_commands(reg) if c.id.startswith("custom.")]
    assert len(specs) == 1
    spec = specs[0]
    assert spec.id == "custom.my_mode.do_thing"
    assert spec.executor.kind == "custom_mode_key"
    assert spec.executor.mode_name == "my_mode"
    assert spec.executor.command_id == "do_thing"
    assert spec.label == "Do a thing"


# --- build_command_catalog (whole list) ---


def test_build_command_catalog_includes_all_buckets() -> None:
    reg = _registry()
    catalog = build_command_catalog(reg)
    ids = {c.id for c in catalog}
    # App
    for f in fields(AppKeymaps):
        assert f"app.{f.name}" in ids
    # Digit
    for d in range(10):
        assert f"saved_query.{d}" in ids
    # Mode (sample one of each)
    assert "fold.cycle_commits" in ids
    assert "fold.agents.cycle_level" in ids
    assert "copy.agents.name" in ids
    assert "leader.models_panel" in ids
    assert "bang.toggle_axe" in ids


def test_agent_run_log_leader_command_is_cl_only() -> None:
    catalog = build_command_catalog(_registry())
    spec = next(c for c in catalog if c.id == "leader.agent_run_log")

    assert spec.label == "Agent run log"
    assert spec.key_display == ",A"
    assert spec.tabs == ("changespecs",)
    assert spec.executor.kind == "leader_mode_key"
    assert spec.executor.subkey == "A"


def test_agent_panel_grouping_leader_command_is_agents_only() -> None:
    catalog = build_command_catalog(_registry())
    spec = next(c for c in catalog if c.id == "leader.toggle_agent_panel_grouping")

    assert spec.label == "Toggle agent panel grouping"
    assert spec.key_display == ",g"
    assert spec.tabs == ("agents",)
    assert spec.executor.kind == "leader_mode_key"
    assert spec.executor.subkey == "g"


def test_visible_agent_folds_use_contextual_app_command() -> None:
    catalog = build_command_catalog(_registry())
    assert not any(c.id == "leader.toggle_selected_agent_panels" for c in catalog)
    spec = next(c for c in catalog if c.id == "app.expand_all_folds")

    assert spec.label == (
        "Select visible Agents folds by number / expand all folds on other tabs"
    )
    assert spec.key_display == "L"
    assert spec.tabs == ("changespecs", "agents", "axe")
    assert spec.executor.kind == "app_action"
    assert spec.executor.action == "expand_all_folds"


def test_projects_command_is_keyless_and_global() -> None:
    catalog = build_command_catalog(_registry())
    # The ``,p`` leader command was retired; the panel is now a keyless,
    # searchable command that opens the Admin Center on the Projects tab.
    assert not any(c.id == "leader.projects" for c in catalog)
    spec = next(c for c in catalog if c.id == "projects")

    assert spec.label == "Open project management panel"
    assert spec.key_display == ""
    assert spec.key_sequence == ()
    assert spec.tabs == ("changespecs", "agents", "axe")
    assert spec.executor.kind == "app_action"
    assert spec.executor.action == "open_projects_panel"
    assert "project management" in spec.aliases


def test_logs_command_is_keyless_and_global() -> None:
    catalog = build_command_catalog(_registry())
    # The ``,L`` leader command was retired; the panel is now a keyless,
    # searchable command that opens the Admin Center on the Logs tab.
    assert not any(c.id == "leader.log_panel" for c in catalog)
    spec = next(c for c in catalog if c.id == "logs")

    assert spec.label == "Open logs panel"
    assert spec.key_display == ""
    assert spec.key_sequence == ()
    assert spec.tabs == ("changespecs", "agents", "axe")
    assert spec.executor.kind == "app_action"
    assert spec.executor.action == "open_log_panel"
    assert "launch failures" in spec.aliases


def test_tasks_command_is_keyless_and_global() -> None:
    catalog = build_command_catalog(_registry())
    # The ``,t`` leader command was retired; the panel is now a keyless,
    # searchable command that opens the Admin Center on the Tasks tab.
    assert not any(c.id == "leader.task_queue" for c in catalog)
    spec = next(c for c in catalog if c.id == "tasks")

    assert spec.label == "Open tasks panel"
    assert spec.key_display == ""
    assert spec.key_sequence == ()
    assert spec.tabs == ("changespecs", "agents", "axe")
    assert spec.executor.kind == "app_action"
    assert spec.executor.action == "open_tasks_panel"
    assert "task queue" in spec.aliases


def test_jump_to_next_unread_done_agent_leader_command_is_agents_only() -> None:
    catalog = build_command_catalog(_registry())
    spec = next(c for c in catalog if c.id == "leader.jump_to_next_unread_done_agent")

    assert spec.label == "Jump to next unread completed agent"
    assert spec.key_display == ",j"
    assert spec.tabs == ("agents",)
    assert spec.executor.kind == "leader_mode_key"
    assert spec.executor.subkey == "j"


def test_repeat_last_leader_command_is_global() -> None:
    catalog = build_command_catalog(_registry())
    spec = next(c for c in catalog if c.id == "leader.repeat_last")

    assert spec.label == "Repeat last leader command"
    assert spec.key_display == ",,"
    assert spec.tabs == ("changespecs", "agents", "axe")
    assert spec.executor.kind == "leader_mode_key"
    assert spec.executor.subkey == "comma"


def test_agent_from_cl_leader_command_uses_space() -> None:
    catalog = build_command_catalog(_registry())
    spec = next(c for c in catalog if c.id == "leader.agent_from_cl")

    assert spec.label == "Agent from PR (quick)"
    assert spec.key_sequence == ("comma", "space")
    assert spec.key_display == ", Space"
    assert spec.tabs == ("changespecs", "agents")
    assert spec.executor.kind == "leader_mode_key"
    assert spec.executor.subkey == "space"


def test_agent_home_leader_command_uses_h() -> None:
    catalog = build_command_catalog(_registry())
    spec = next(c for c in catalog if c.id == "leader.agent_home")

    assert spec.label == "Agent (home mode)"
    assert spec.key_sequence == ("comma", "h")
    assert spec.key_display == ",h"
    assert spec.tabs == ("changespecs", "agents", "axe")
    assert spec.executor.kind == "leader_mode_key"
    assert spec.executor.subkey == "h"


def test_repeat_last_leader_command_respects_repeat_key_and_prefix_overrides() -> None:
    reg = load_keymap_registry(
        {
            "keymaps": {
                "modes": {
                    "leader_mode": {
                        "prefix": "space",
                        "keys": {"repeat_last": "R"},
                    }
                }
            }
        }
    )
    catalog = build_command_catalog(reg)
    spec = next(c for c in catalog if c.id == "leader.repeat_last")

    assert spec.key_sequence == ("space", "R")
    assert spec.key_display == "Space R"
    assert spec.executor.kind == "leader_mode_key"
    assert spec.executor.subkey == "R"


def test_jump_to_next_stopped_agent_leader_command_is_agents_only() -> None:
    catalog = build_command_catalog(_registry())
    spec = next(c for c in catalog if c.id == "leader.jump_to_next_stopped_agent")

    assert spec.label == "Jump to next stopped agent"
    assert spec.key_display == ",J"
    assert spec.tabs == ("agents",)
    assert spec.executor.kind == "leader_mode_key"
    assert spec.executor.subkey == "J"


def test_runners_leader_command_uses_uppercase_r() -> None:
    catalog = build_command_catalog(_registry())
    spec = next(c for c in catalog if c.id == "leader.runners")

    assert spec.key_display == ",R"
    assert spec.executor.kind == "leader_mode_key"
    assert spec.executor.subkey == "R"


def test_capture_agents_repro_leader_command_uses_uppercase_b() -> None:
    catalog = build_command_catalog(_registry())
    spec = next(c for c in catalog if c.id == "leader.capture_agents_repro")

    assert spec.key_display == ",B"
    assert spec.tabs == ("agents",)
    assert spec.executor.kind == "leader_mode_key"
    assert spec.executor.subkey == "B"


def test_models_panel_leader_command_uses_m() -> None:
    catalog = build_command_catalog(_registry())
    spec = next(c for c in catalog if c.id == "leader.models_panel")

    assert spec.label == "Models panel"
    assert spec.key_display == ",m"
    assert spec.tabs == ("changespecs", "agents", "axe")
    assert spec.executor.kind == "leader_mode_key"
    assert spec.executor.subkey == "m"


def test_update_sase_leader_command_uses_uppercase_u() -> None:
    catalog = build_command_catalog(_registry())
    spec = next(c for c in catalog if c.id == "leader.update_sase")

    assert spec.label == "Update sase, core, and plugins"
    assert spec.key_display == ",U"
    assert spec.tabs == ("changespecs", "agents", "axe")
    assert spec.executor.kind == "leader_mode_key"
    assert spec.executor.subkey == "U"


def test_review_mentors_leader_command_uses_uppercase_c() -> None:
    catalog = build_command_catalog(_registry())
    spec = next(c for c in catalog if c.id == "leader.review_mentors")

    assert spec.key_display == ",C"
    assert spec.tabs == ("changespecs",)
    assert spec.executor.kind == "leader_mode_key"
    assert spec.executor.subkey == "C"


def test_prompt_history_edit_first_leader_command_uses_ctrl_g() -> None:
    catalog = build_command_catalog(_registry())
    spec = next(c for c in catalog if c.id == "leader.prompt_history_edit_first")

    assert spec.label == "Edit first prompt history entry"
    assert spec.key_display == ", Ctrl+G"
    assert spec.tabs == ("changespecs", "agents", "axe")
    assert spec.executor.kind == "leader_mode_key"
    assert spec.executor.subkey == "ctrl+g"


def test_command_specs_are_well_formed() -> None:
    reg = _registry()
    catalog = build_command_catalog(reg)
    for spec in catalog:
        assert isinstance(spec, CommandSpec)
        assert spec.id
        assert spec.label
        assert spec.tabs
        if spec.id in {
            "logs",
            "projects",
            "tasks",
            "statistics",
        }:
            # These Admin Center panels are intentionally keyless: searchable
            # commands with no direct binding that open the corresponding tab.
            assert spec.key_sequence == ()
            assert spec.key_display == ""
            continue
        assert spec.key_sequence and all(spec.key_sequence)
        assert spec.key_display


def test_command_catalog_ids_are_unique() -> None:
    catalog = build_command_catalog(_registry())
    ids = [c.id for c in catalog]
    assert len(ids) == len(set(ids))


# --- key display formatting ---


def test_format_key_sequence_single_char_concat() -> None:
    """Two single-char keys concatenate without separator (``zc``)."""
    assert _format_key_sequence(("z", "c")) == "zc"


def test_format_key_sequence_special_keys_concat() -> None:
    """``percent_sign`` + ``n`` renders as ``%n``."""
    assert _format_key_sequence(("percent_sign", "n")) == "%n"


def test_format_key_sequence_multichar_space_joined() -> None:
    """Multi-char keys (e.g. ``ctrl+d``) get space-joined for readability."""
    assert _format_key_sequence(("ctrl+d", "x")) == "Ctrl+D x"
    assert _format_key_sequence(("comma", "ctrl+@")) == ", Ctrl+Space"


def test_format_key_sequence_compound_binding_displays_alternatives() -> None:
    """A compound app binding is formatted as alternatives."""
    assert _format_key_sequence(("colon,semicolon",)) == ": / ;"


# --- Source-of-truth guard ---


def test_app_metadata_matches_app_keymaps_after_load() -> None:
    """Catalog construction must not silently drift from AppKeymaps.

    ``catalog.py`` raises at import time if the metadata table doesn't
    cover every ``AppKeymaps`` field; this test re-asserts the contract
    with a freshly-loaded registry to catch runtime regressions.
    """
    defaults = load_builtin_app_defaults()
    reg = load_keymap_registry({})
    catalog = list(iter_app_commands(reg))
    assert len(catalog) == len(defaults)
