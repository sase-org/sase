"""Cross-tab command palette applicability predicates."""

from __future__ import annotations

from types import SimpleNamespace

from sase.ace.tui.commands import (
    CommandContext,
    build_command_catalog,
    is_command_available,
)
from sase.ace.tui.keymaps import load_keymap_registry
from tests._command_availability_helpers import catalog_by_id as _catalog_by_id


def test_catalog_has_one_cleanup_command_and_no_legacy_kill_all() -> None:
    catalog = build_command_catalog(load_keymap_registry({}))
    cleanup = [spec for spec in catalog if spec.id == "app.open_agent_cleanup_panel"]
    legacy = [spec for spec in catalog if spec.id == "leader.kill_all"]
    assert len(cleanup) == 1
    assert legacy == []


def test_command_hidden_when_tab_not_in_spec_tabs() -> None:
    """A Patch-only command must be hidden on the agents tab."""
    catalog = _catalog_by_id()
    show_diff = catalog["app.show_diff"]
    ctx = CommandContext(tab="agents")
    assert not is_command_available(show_diff, ctx)


def test_metadata_sections_are_agents_only_and_forward_jump_is_all_tab() -> None:
    catalog = _catalog_by_id()
    next_section = catalog["app.next_agent_metadata_section"]
    prev_section = catalog["app.prev_agent_metadata_section"]
    jump_forward = catalog["app.jump_to_entry_forward"]

    for section_command in (next_section, prev_section):
        assert is_command_available(section_command, CommandContext(tab="agents"))
        assert not is_command_available(
            section_command,
            CommandContext(tab="changespecs"),  # legacy tab id
        )
        assert not is_command_available(section_command, CommandContext(tab="axe"))

    for tab in ("changespecs", "agents", "axe"):  # legacy tab id
        assert is_command_available(jump_forward, CommandContext(tab=tab))


def test_fold_palette_commands_are_scoped_by_fold_surface() -> None:
    catalog = _catalog_by_id()
    patch_fold = catalog["fold.cycle_stitches"]
    agent_fold = catalog["fold.agents.cycle_level"]
    regular_agent = SimpleNamespace(is_family_container_row=False)

    assert is_command_available(
        patch_fold, CommandContext(tab="changespecs")
    )  # legacy tab id
    assert not is_command_available(patch_fold, CommandContext(tab="agents"))
    assert is_command_available(
        agent_fold,
        CommandContext(tab="agents", agent=regular_agent),  # type: ignore[arg-type]
    )
    assert not is_command_available(
        agent_fold, CommandContext(tab="changespecs")
    )  # legacy tab id


def test_direct_fold_palette_commands_follow_active_context_scale() -> None:
    catalog = _catalog_by_id()
    family = SimpleNamespace(is_family_container_row=True)
    clan = SimpleNamespace(is_family_container_row=False)

    family_ctx = CommandContext(tab="agents", agent=family)  # type: ignore[arg-type]
    clan_ctx = CommandContext(tab="agents", agent=clan)  # type: ignore[arg-type]
    tribe_ctx = CommandContext(
        tab="agents",
        agent=clan,  # type: ignore[arg-type]
        panel_focused=True,
    )

    for position in range(1, 5):
        spec = catalog[f"fold.agents.set_level_{position}"]
        assert is_command_available(spec, family_ctx) is (position <= 2)
        assert is_command_available(spec, clan_ctx) is (position <= 3)
        assert is_command_available(spec, tribe_ctx)

    for position in range(1, 4):
        spec = catalog[f"fold.set_level_{position}"]
        assert is_command_available(
            spec,
            CommandContext(tab="changespecs", artifacts_subtab="prs"),  # legacy tab id
        )
        assert not is_command_available(
            spec,
            CommandContext(
                tab="changespecs", artifacts_subtab="stitches"
            ),  # legacy tab id
        )
        assert not is_command_available(spec, CommandContext(tab="axe"))


def test_agent_fold_palette_is_hidden_without_summary_selection() -> None:
    catalog = _catalog_by_id()
    ctx = CommandContext(tab="agents", agent=None)
    group_ctx = CommandContext(
        tab="agents",
        agent=SimpleNamespace(is_family_container_row=False),  # type: ignore[arg-type]
        group_focused=True,
    )

    assert not is_command_available(catalog["app.start_fold_mode"], ctx)
    assert not is_command_available(catalog["fold.agents.set_level_1"], ctx)
    assert not is_command_available(catalog["app.start_fold_mode"], group_ctx)


def test_metadata_search_palette_entries_follow_transient_search_state() -> None:
    catalog = _catalog_by_id()
    ctx = CommandContext(tab="agents")

    assert is_command_available(catalog["app.search_forward"], ctx)
    assert not is_command_available(catalog["app.search_reverse"], ctx)
    assert is_command_available(
        catalog["app.search_reverse"],
        CommandContext(tab="agents", agents_metadata_search_active=True),
    )


def test_show_help_palette_entry_is_available_across_tabs_and_artifacts() -> None:
    catalog = _catalog_by_id()
    show_help = catalog["app.show_help"]

    assert is_command_available(show_help, CommandContext(tab="agents"))
    assert is_command_available(show_help, CommandContext(tab="axe"))
    for subtab in ("prs", "stitches", "bugs", "beads", "plans", "chats", "other"):
        assert is_command_available(
            show_help,
            CommandContext(tab="changespecs", artifacts_subtab=subtab),  # type: ignore[arg-type]  # legacy tab id
        )


def test_bead_issue_palette_commands_are_scoped_to_beads_subtab() -> None:
    catalog = _catalog_by_id()
    command = catalog["bead_issue.view"]
    direct_mode = catalog["app.start_bead_issue_mode"]

    beads_ctx = CommandContext(tab="artifacts", artifacts_subtab="beads")
    bugs_ctx = CommandContext(tab="artifacts", artifacts_subtab="bugs")

    assert is_command_available(command, beads_ctx)
    assert is_command_available(direct_mode, beads_ctx)
    assert not is_command_available(command, bugs_ctx)
    assert not is_command_available(direct_mode, bugs_ctx)
