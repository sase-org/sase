"""Tests for the Agents-tab onboarding widget."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.widgets.agent_onboarding import AgentOnboarding


def _section_plain(sections: dict[str, Text], selector: str) -> str:
    return sections[selector].plain


def test_agent_onboarding_content_includes_tabs_and_docs_link() -> None:
    widget = AgentOnboarding()
    sections = widget.render_content(load_keymap_registry({}))
    rendered = "\n".join(text.plain for text in sections.values())

    assert "Welcome to sase ace" in rendered
    assert "PRs" in rendered
    assert "Agents" in rendered
    assert "AXE" in rendered
    assert "https://sase.sh" in rendered


def test_agent_onboarding_uses_active_keymap_registry() -> None:
    registry = load_keymap_registry({"keymaps": {"app": {"show_help": "f1"}}})
    widget = AgentOnboarding()

    sections = widget.render_content(registry)
    help_text = _section_plain(sections, "#agent-onboarding-help")

    assert "f1" in help_text
    assert "?" not in help_text


def test_launch_card_includes_project_cl_hint_when_targets_exist() -> None:
    widget = AgentOnboarding()
    sections = widget.render_content(
        load_keymap_registry({}),
        launch_targets_available=True,
    )
    launch_text = _section_plain(sections, "#agent-onboarding-launch")

    assert "open the prompt bar in your home workspace." in launch_text
    assert "pick a project or CL first." in launch_text
    assert "Works from any tab; shell: sase ace." in launch_text


def test_launch_card_omits_project_cl_hint_without_targets() -> None:
    widget = AgentOnboarding()
    sections = widget.render_content(
        load_keymap_registry({}),
        launch_targets_available=False,
    )
    launch_text = _section_plain(sections, "#agent-onboarding-launch")

    assert "open the prompt bar in your home workspace." in launch_text
    assert "pick a project or CL first." not in launch_text
    assert "Works from any tab; shell: sase ace." in launch_text
