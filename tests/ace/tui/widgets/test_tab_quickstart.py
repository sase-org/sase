"""Tests for the shared tab quick-start widget."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.widgets.tab_quickstart import TabQuickStart


def _section_plain(sections: dict[str, Text], selector: str) -> str:
    return sections[selector].plain


def test_tab_quickstart_uses_active_keymap_registry() -> None:
    registry = load_keymap_registry(
        {
            "keymaps": {
                "app": {
                    "start_agent_home": "f2",
                    "open_config_center": "f3",
                    "next_tab": "f4",
                    "edit_query": "f5",
                    "show_help": "f6",
                    "open_command_palette": "f7",
                },
            }
        }
    )

    sections = TabQuickStart.render_content(registry, tab="agents")
    card = _section_plain(sections, "#agent-quickstart-card")
    hero = _section_plain(sections, "#agent-quickstart-hero")

    for key in ("f2", "f3", "f4", "f5", "f6", "f7"):
        assert key in card
    assert " ] " in card
    assert "Launch your first agent" in card
    assert "The full tour of this tab" in card
    assert "tool calls, and artifact files" in hero


def test_artifacts_quickstart_advertises_every_subtab() -> None:
    registry = load_keymap_registry({})

    agents = TabQuickStart.render_content(registry, tab="agents")
    changespecs = TabQuickStart.render_content(registry, tab="changespecs")
    agents_card = _section_plain(agents, "#agent-quickstart-card")
    artifacts_card = _section_plain(changespecs, "#changespec-quickstart-card")

    assert "Browse Artifacts: PRs · Commits · Bugs · Plans" in artifacts_card
    assert "Browse Artifacts" not in agents_card
    assert _section_plain(agents, "#agent-quickstart-hero") != _section_plain(
        changespecs, "#changespec-quickstart-hero"
    )
    assert _section_plain(agents, "#agent-quickstart-footer") != _section_plain(
        changespecs, "#changespec-quickstart-footer"
    )


def test_artifacts_quickstart_uses_configured_subtab_keys() -> None:
    registry = load_keymap_registry(
        {
            "keymaps": {
                "app": {
                    "cycle_artifacts_subtab_reverse": "f8",
                    "cycle_artifacts_subtab": "f9",
                }
            }
        }
    )

    sections = TabQuickStart.render_content(registry, tab="changespecs")
    card = _section_plain(sections, "#changespec-quickstart-card")

    assert "f8" in card
    assert "f9" in card


def test_tab_quickstart_no_match_callout_is_prs_only() -> None:
    registry = load_keymap_registry({})

    agents = TabQuickStart.render_content(
        registry,
        tab="agents",
        no_match_total=3,
    )
    empty_prs = TabQuickStart.render_content(
        registry,
        tab="changespecs",
        no_match_total=0,
    )
    no_match_prs = TabQuickStart.render_content(
        registry,
        tab="changespecs",
        no_match_total=3,
    )

    assert _section_plain(agents, "#agent-quickstart-callout") == ""
    assert _section_plain(empty_prs, "#changespec-quickstart-callout") == ""
    callout = _section_plain(no_match_prs, "#changespec-quickstart-callout")
    assert "No PRs match this query" in callout
    assert "3 exist" in callout
    assert "/ edits the query" in callout
