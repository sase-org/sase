"""Tests for the Help modal guide view selection."""

from __future__ import annotations

from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.modals.help_modal import HelpModal
from sase.ace.tui.widgets import AgentOnboarding, AxeOnboarding, PatchOnboarding


def test_help_modal_builds_patch_guide() -> None:
    registry = load_keymap_registry({})
    modal = HelpModal(current_tab="patches", registry=registry)

    guide = modal._build_guide_view()

    assert isinstance(guide, PatchOnboarding)
    sections = PatchOnboarding.render_content(registry)
    assert "#patch-onboarding-footer" not in sections
    assert "[ / ] panel tabs" in modal._build_footer()


def test_help_modal_forwards_agents_onboarding_state() -> None:
    registry = load_keymap_registry({})
    modal = HelpModal(
        current_tab="agents",
        registry=registry,
        agents_launch_targets_available=True,
        agents_plugins_installed=False,
    )

    guide = modal._build_guide_view()

    assert isinstance(guide, AgentOnboarding)
    sections = guide.render_content(registry)
    assert (
        "launch against a specific project or PR instead."
        in sections["#agent-onboarding-launch"].plain
    )
    assert "#agent-onboarding-footer" not in sections
    assert guide.numbered_step_titles() == [
        "1 Launch your first agent",
        "2 Inspect the results",
        "3 The three tabs",
        "4 Install plugins & keep sase current",
        "5 Get more help",
    ]


def test_help_modal_builds_axe_guide() -> None:
    modal = HelpModal(current_tab="axe", registry=load_keymap_registry({}))

    guide = modal._build_guide_view()

    assert isinstance(guide, AxeOnboarding)


def test_help_modal_refresh_for_tab_rebuilds_guide_state() -> None:
    registry = load_keymap_registry({})
    modal = HelpModal(current_tab="patches", registry=registry)

    modal.refresh_for_tab(
        "agents",
        active_query=None,
        registry=registry,
        agents_launch_targets_available=True,
        agents_plugins_installed=False,
    )

    assert modal._current_tab == "agents"
    guide = modal._build_guide_view()
    assert isinstance(guide, AgentOnboarding)
    sections = guide.render_content(registry)
    assert (
        "launch against a specific project or PR instead."
        in sections["#agent-onboarding-launch"].plain
    )
