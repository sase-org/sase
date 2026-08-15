"""Tests for the ace TUI command generators.

Verifies that the app, saved-query, and mode generators:

- Cover every :class:`AppKeymaps` field exactly once.
- Include all 10 saved-query picker sequences.
- Cover every built-in mode subkey (fold, copy nested per-tab, leader,
  bang, bead issue) and every valid user-defined custom mode command.
"""

from __future__ import annotations

from dataclasses import fields

from sase.ace.tui.commands import (
    build_command_catalog,
    iter_app_commands,
    iter_digit_commands,
    iter_mode_commands,
)
from sase.ace.tui.keymaps import (
    AppKeymaps,
    KeymapRegistry,
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
    reg = load_keymap_registry({"keymaps": {"app": {"next_patch": "B"}}})
    by_id = {c.id: c for c in iter_app_commands(reg)}
    assert by_id["app.next_patch"].key_sequence == ("B",)
    assert by_id["app.next_patch"].key_display == "B"


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
    assert forward.tabs == ("artifacts", "agents", "axe")
    assert "ctrl+shift+o" in forward.aliases
    assert "ctrl+k" not in forward.aliases
    assert by_id["app.next_agent_metadata_section"].tabs == ("agents",)
    assert by_id["app.prev_agent_metadata_section"].tabs == ("agents",)
    assert "app.prev_patch_history" not in by_id
    assert "app.next_patch_history" not in by_id


def test_last_vcs_xprompt_editor_command_is_all_tab_agent_command() -> None:
    """The Ctrl+G MRU editor action is discoverable on every tab."""
    by_id = {c.id: c for c in iter_app_commands(_registry())}
    spec = by_id["app.start_last_vcs_xprompt_in_editor"]
    assert spec.label == "Edit last VCS xprompt"
    assert spec.category == "Agents"
    assert spec.tabs == ("artifacts", "agents", "axe")
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
    assert spec.tabs == ("artifacts", "agents", "axe")
    assert spec.key_sequence == ("at",)
    assert spec.key_display == "@"
    assert spec.executor.kind == "app_action"
    assert spec.executor.action == "restore_prompt_stash"
    assert "stash" in spec.aliases
    assert "pop" in spec.aliases
    assert "gP" not in spec.aliases


def test_show_help_command_is_global_question_mark_keymap() -> None:
    """Bare ``?`` opens tab-aware help; the old ``,?`` command is gone."""
    by_id = {c.id: c for c in build_command_catalog(_registry())}
    spec = by_id["app.show_help"]

    assert spec.label == "Show help"
    assert spec.category == "Display"
    assert spec.tabs == ("artifacts", "agents", "axe")
    assert spec.key_sequence == ("question_mark",)
    assert spec.key_display == "?"
    assert spec.executor.kind == "app_action"
    assert spec.executor.action == "show_help"
    assert "leader.show_help" not in by_id


def test_start_agent_from_patch_command_uses_ctrl_space() -> None:
    """The repeat-last agent command exposes Ctrl+Space, not bare Space."""
    by_id = {c.id: c for c in iter_app_commands(_registry())}
    spec = by_id["app.start_agent_from_patch"]

    assert spec.label == "Run agent from Patch"
    assert spec.key_sequence == ("ctrl+@",)
    assert spec.key_display == "Ctrl+Space"


def test_start_agent_home_command_uses_bare_space() -> None:
    """The home-agent app command exposes bare Space."""
    by_id = {c.id: c for c in iter_app_commands(_registry())}
    spec = by_id["app.start_agent_home"]

    assert spec.label == "Run agent (home mode)"
    assert spec.category == "Agents"
    assert spec.tabs == ("artifacts", "agents", "axe")
    assert spec.key_sequence == ("space",)
    assert spec.key_display == "Space"
    assert spec.executor.kind == "app_action"
    assert spec.executor.action == "start_agent_home"


def test_run_workflow_command_is_contextual_retry_on_agents() -> None:
    by_id = {c.id: c for c in iter_app_commands(_registry())}
    spec = by_id["app.run_workflow"]

    assert spec.label == "Run workflow / retry agent / re-run"
    assert spec.tabs == ("artifacts", "agents", "axe")
    assert spec.key_sequence == ("r",)
    assert spec.key_display == "r"
    assert "retry" in spec.aliases


def test_add_tag_command_is_contextual_wait_on_agents() -> None:
    by_id = {c.id: c for c in iter_app_commands(_registry())}
    spec = by_id["app.add_tag"]

    assert spec.label == "Add tag / wait for agent, clan, or tribe"
    assert spec.tabs == ("artifacts", "agents")
    assert spec.key_sequence == ("W",)
    assert "wait for agent" in spec.aliases
    assert "wait for clan" in spec.aliases
    assert "wait for tribe" in spec.aliases


def test_patch_sync_commands_use_patch_labels() -> None:
    by_id = {c.id: c for c in iter_app_commands(_registry())}

    assert by_id["app.rebase"].label == "Rebase Patch"
    assert by_id["app.start_rewind"].label == "Rewind Patch / Revive agent"


def test_bulk_change_status_command_is_patch_only() -> None:
    by_id = {c.id: c for c in iter_app_commands(_registry())}
    spec = by_id["app.bulk_change_status"]

    assert spec.label == "Bulk status change"
    assert spec.tabs == ("artifacts",)


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

    assert spec.label == "Zoom agent or tribe detail panel"
    assert spec.category == "Display"
    assert spec.tabs == ("agents",)
    assert spec.key_sequence == ("Z",)
    assert spec.key_display == "Z"
    assert "zoom" in spec.aliases
    assert "tribe" in spec.aliases


def test_isolate_panels_command_is_agents_only_display_command() -> None:
    by_id = {c.id: c for c in iter_app_commands(_registry())}
    spec = by_id["app.isolate_panels"]

    assert spec.label == "Isolate or restore tribe panels"
    assert spec.category == "Display"
    assert spec.tabs == ("agents",)
    assert spec.key_sequence == ("=",)
    assert spec.key_display == "="
    assert "only panel" in spec.aliases
    assert "restore panels" in spec.aliases
    assert "isolate" in spec.aliases


def test_collapse_panel_folds_command_is_agents_only_display_command() -> None:
    by_id = {c.id: c for c in iter_app_commands(_registry())}
    spec = by_id["app.collapse_panel_folds"]

    assert spec.label == "Collapse or restore tribe panel folds"
    assert spec.category == "Display"
    assert spec.tabs == ("agents",)
    assert spec.key_sequence == ("minus",)
    assert spec.key_display == "-"
    assert "collapse folds" in spec.aliases
    assert "restore folds" in spec.aliases
    assert "fold panel" in spec.aliases


def test_h_commands_describe_navigation_and_contextual_collapsing() -> None:
    by_id = {c.id: c for c in iter_app_commands(_registry())}
    lower = by_id["app.hooks_or_collapse"]
    upper = by_id["app.hooks_or_collapse_all"]

    assert lower.label == (
        "Navigate to parent container or tribe / collapse selected panel, "
        "jump to last expanded panel, or collapse fold"
    )
    assert lower.key_sequence == ("h",)
    assert lower.key_display == "h"
    assert "last expanded panel" in lower.aliases
    assert upper.label == (
        "Collapse selected workflow/family, then group sase agents, selected "
        "clan, remaining clans/groups; panel sase agents/clans/groups/panel / "
        "compact tools detail / collapse all folds on other tabs"
    )
    assert upper.key_sequence == ("H",)
    assert upper.key_display == "H"
    assert "collapse workflow" in upper.aliases
    assert "collapse family" in upper.aliases
    assert "collapse sase agents" in upper.aliases
    assert "collapse clan" in upper.aliases
    assert "collapse selected clan" in upper.aliases
    assert "collapse clans" in upper.aliases
    assert "collapse remaining clans" in upper.aliases
    assert "collapse group" in upper.aliases
    assert "collapse selected panel" in upper.aliases


# --- Saved-query commands ---


def test_saved_query_commands_cover_all_prefixed_slots() -> None:
    queries = list(iter_digit_commands(_registry()))
    assert {c.id for c in queries} == {f"saved_query.{d}" for d in range(10)}
    assert all(c.executor.kind == "saved_query" for c in queries)
    assert all(c.key_sequence[0] == "0" for c in queries)
    assert {c.key_display for c in queries} == {
        "01",
        "02",
        "03",
        "04",
        "05",
        "06",
        "07",
        "08",
        "09",
        "00",
    }


def test_saved_query_commands_follow_configured_slot_prefix() -> None:
    registry = load_keymap_registry(
        {"keymaps": {"app": {"start_saved_query_mode": "P"}}}
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
    assert by_id["fold.cycle_stitches"].tabs == ("artifacts",)
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
    assert by_id["copy.patches.bug"].tabs == ("artifacts",)
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


def test_bead_issue_mode_commands_cover_every_subkey() -> None:
    reg = _registry()
    specs = [
        c
        for c in iter_mode_commands(reg)
        if c.id.startswith("bead_issue.") and c.executor.kind == "bead_issue_mode_key"
    ]
    expected = {f"bead_issue.{cid}" for cid in reg.bead_issue_mode.keys}
    assert {c.id for c in specs} == expected
    for spec in specs:
        assert spec.key_sequence[0] == reg.bead_issue_mode.prefix
        assert len(spec.key_sequence) == 2
        assert spec.tabs == ("artifacts",)


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
