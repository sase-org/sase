"""Tests for the Tab Guide modal guide selection."""

from __future__ import annotations

from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.modals.tab_guide_modal import TabGuideModal
from sase.ace.tui.widgets import AgentOnboarding, AxeOnboarding, ChangeSpecOnboarding


def test_tab_guide_modal_builds_changespec_guide_with_modal_footer() -> None:
    registry = load_keymap_registry({})
    modal = TabGuideModal(current_tab="changespecs", registry=registry)

    guide = modal._build_guide()

    assert isinstance(guide, ChangeSpecOnboarding)
    sections = ChangeSpecOnboarding.render_content(registry)
    assert "esc closes" in sections["#changespec-onboarding-footer"].plain
    assert modal._guide_border_subtitle() == "esc closes · tab/shift+tab tabs"


def test_tab_guide_modal_forwards_agents_onboarding_state() -> None:
    registry = load_keymap_registry({})
    modal = TabGuideModal(
        current_tab="agents",
        registry=registry,
        agents_launch_targets_available=True,
        agents_plugins_installed=False,
    )

    guide = modal._build_guide()

    assert isinstance(guide, AgentOnboarding)
    sections = guide.render_content(registry)
    assert (
        "launch against a specific project or PR instead."
        in sections["#agent-onboarding-launch"].plain
    )
    assert guide.numbered_step_titles() == [
        "1 Launch your first agent",
        "2 Inspect the results",
        "3 The three tabs",
        "4 Install plugins & keep sase current",
        "5 Get more help",
    ]
    assert "esc closes" in sections["#agent-onboarding-footer"].plain


def test_tab_guide_modal_builds_axe_guide() -> None:
    modal = TabGuideModal(current_tab="axe", registry=load_keymap_registry({}))

    guide = modal._build_guide()

    assert isinstance(guide, AxeOnboarding)


def test_tab_guide_modal_refresh_for_tab_rebuilds_guide_state() -> None:
    registry = load_keymap_registry({})
    modal = TabGuideModal(current_tab="changespecs", registry=registry)

    modal.refresh_for_tab(
        current_tab="agents",
        registry=registry,
        agents_launch_targets_available=True,
        agents_plugins_installed=False,
    )

    assert modal._current_tab == "agents"
    guide = modal._build_guide()
    assert isinstance(guide, AgentOnboarding)
    sections = guide.render_content(registry)
    assert (
        "launch against a specific project or PR instead."
        in sections["#agent-onboarding-launch"].plain
    )
