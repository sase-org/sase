"""Tests for assembling and presenting the ace TUI command catalog."""

from __future__ import annotations

from dataclasses import fields

from sase.ace.tui.commands import (
    CommandSpec,
    build_command_catalog,
    iter_app_commands,
)
from sase.ace.tui.commands.catalog import _format_key_sequence
from sase.ace.tui.keymaps import (
    AppKeymaps,
    KeymapRegistry,
    load_builtin_app_defaults,
    load_keymap_registry,
)
from sase.ace.tui.keymaps.key_validation import is_unbound_key


def _registry() -> KeymapRegistry:
    return load_keymap_registry({})


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
    assert "fold.cycle_stitches" in ids
    assert "fold.agents.cycle_level" in ids
    assert "copy.agents.name" in ids
    assert "leader.models_panel" in ids
    assert "bang.toggle_axe" in ids


def test_agent_run_log_leader_command_is_cl_only() -> None:
    catalog = build_command_catalog(_registry())
    spec = next(c for c in catalog if c.id == "leader.agent_run_log")

    assert spec.label == "Agent run log"
    assert spec.key_display == ",A"
    assert spec.tabs == ("artifacts",)
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

    assert (
        spec.label
        == "Toggle a fold in the selected tribe / expand all folds on other tabs"
    )
    assert spec.key_display == "L"
    assert spec.tabs == ("artifacts", "agents", "axe")
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
    assert spec.tabs == ("artifacts", "agents", "axe")
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
    assert spec.tabs == ("artifacts", "agents", "axe")
    assert spec.executor.kind == "app_action"
    assert spec.executor.action == "open_log_panel"
    assert "launch failures" in spec.aliases


def test_tasks_command_is_keyless_and_global() -> None:
    catalog = build_command_catalog(_registry())
    # The ``,t`` leader command was retired; the panel is now a keyless,
    # searchable command that opens the Admin Center on the Tasks tab.
    assert not any(c.id == "leader.task_queue" for c in catalog)
    spec = next(c for c in catalog if c.id == "tasks")

    assert spec.label == "Open procs panel"
    assert spec.key_display == ""
    assert spec.key_sequence == ()
    assert spec.tabs == ("artifacts", "agents", "axe")
    assert spec.executor.kind == "app_action"
    assert spec.executor.action == "open_tasks_panel"
    assert "proc queue" in spec.aliases


def test_jump_to_next_unread_done_agent_leader_command_is_agents_only() -> None:
    catalog = build_command_catalog(_registry())
    spec = next(c for c in catalog if c.id == "leader.jump_to_next_unread_done_agent")

    assert spec.label == "Jump to next unread completed agent"
    assert spec.key_display == ",j"
    assert spec.tabs == ("agents",)
    assert spec.executor.kind == "leader_mode_key"
    assert spec.executor.subkey == "j"


def test_mark_all_unread_done_agents_read_leader_command_mentions_undo() -> None:
    catalog = build_command_catalog(_registry())
    spec = next(c for c in catalog if c.id == "leader.mark_all_unread_done_agents_read")

    assert spec.label == "Mark all unread completed agents read or undo"
    assert spec.key_display == ",u"
    assert spec.tabs == ("agents",)
    assert spec.executor.kind == "leader_mode_key"
    assert spec.executor.subkey == "u"


def test_repeat_last_leader_command_is_global() -> None:
    catalog = build_command_catalog(_registry())
    spec = next(c for c in catalog if c.id == "leader.repeat_last")

    assert spec.label == "Repeat last leader command"
    assert spec.key_display == ",,"
    assert spec.tabs == ("artifacts", "agents", "axe")
    assert spec.executor.kind == "leader_mode_key"
    assert spec.executor.subkey == "comma"


def test_agent_from_cl_leader_command_uses_space() -> None:
    catalog = build_command_catalog(_registry())
    spec = next(c for c in catalog if c.id == "leader.agent_from_cl")

    assert spec.label == "Agent from Patch (quick)"
    assert spec.key_sequence == ("comma", "space")
    assert spec.key_display == ", Space"
    assert spec.tabs == ("artifacts", "agents")
    assert spec.executor.kind == "leader_mode_key"
    assert spec.executor.subkey == "space"


def test_agent_home_leader_command_uses_h() -> None:
    catalog = build_command_catalog(_registry())
    spec = next(c for c in catalog if c.id == "leader.agent_home")

    assert spec.label == "Agent (home mode)"
    assert spec.key_sequence == ("comma", "h")
    assert spec.key_display == ",h"
    assert spec.tabs == ("artifacts", "agents", "axe")
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

    assert spec.label == "Config > Launch"
    assert spec.key_display == ",m"
    assert spec.tabs == ("artifacts", "agents", "axe")
    assert spec.executor.kind == "leader_mode_key"
    assert spec.executor.subkey == "m"


def test_update_sase_leader_command_uses_uppercase_u() -> None:
    catalog = build_command_catalog(_registry())
    spec = next(c for c in catalog if c.id == "leader.update_sase")

    assert spec.label == "Update panel (SASE, providers, agents)"
    assert spec.key_display == ",U"
    assert spec.tabs == ("artifacts", "agents", "axe")
    assert spec.executor.kind == "leader_mode_key"
    assert spec.executor.subkey == "U"


def test_review_mentors_leader_command_uses_uppercase_c() -> None:
    catalog = build_command_catalog(_registry())
    spec = next(c for c in catalog if c.id == "leader.review_mentors")

    assert spec.key_display == ",C"
    assert spec.tabs == ("artifacts",)
    assert spec.executor.kind == "leader_mode_key"
    assert spec.executor.subkey == "C"


def test_prompt_history_edit_first_leader_command_uses_ctrl_g() -> None:
    catalog = build_command_catalog(_registry())
    spec = next(c for c in catalog if c.id == "leader.prompt_history_edit_first")

    assert spec.label == "Edit first prompt history entry"
    assert spec.key_display == ", Ctrl+G"
    assert spec.tabs == ("artifacts", "agents", "axe")
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
        if all(is_unbound_key(part) for part in spec.key_sequence):
            assert spec.key_display == ""
            continue
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
