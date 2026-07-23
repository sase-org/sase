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
    assert "Artifacts" in rendered
    assert "Agents" in rendered
    assert "AXE" in rendered
    assert "https://sase.sh" in rendered
    assert "https://sase.sh/ace/" in rendered
    assert "https://sase.sh/xprompt/" in rendered
    assert "tools, and artifact files" in rendered


def test_agent_onboarding_tab_rows_follow_visible_tab_order() -> None:
    widget = AgentOnboarding()
    sections = widget.render_content(load_keymap_registry({}))
    tabs_text = _section_plain(sections, "#agent-onboarding-tabs")

    positions = {
        label: tabs_text.index(label) for label in ("Agents", "Artifacts", "AXE")
    }

    assert positions["Agents"] < positions["Artifacts"] < positions["AXE"]


def test_agent_onboarding_uses_active_keymap_registry() -> None:
    registry = load_keymap_registry(
        {"keymaps": {"modes": {"leader_mode": {"keys": {"show_help": "f1"}}}}}
    )
    widget = AgentOnboarding()

    sections = widget.render_content(registry)
    help_text = _section_plain(sections, "#agent-onboarding-help")

    assert "f1" in help_text
    assert "full keybinding reference" in help_text


def test_agent_onboarding_inspect_card_uses_active_keymap_registry() -> None:
    registry = load_keymap_registry(
        {
            "keymaps": {
                "app": {
                    "next_changespec": "f1",
                    "prev_changespec": "f2",
                    "edit_spec": "f3",
                    "jump_to_agent_changespec": "f4",
                    "open_artifact_files": "f5",
                }
            }
        }
    )
    widget = AgentOnboarding()

    sections = widget.render_content(registry)
    inspect_text = _section_plain(sections, "#agent-onboarding-inspect")

    for key in ("f1", "f2", "f3", "f4", "f5"):
        assert key in inspect_text
    assert "Watch a running agent live" in inspect_text
    assert "when it finishes, review its transcript" in inspect_text
    assert "open a finished agent's chat transcript" in inspect_text
    assert "jump to the PR it produced" in inspect_text
    assert "browse artifact files" in inspect_text


def test_plugins_card_includes_admin_center_updates_and_github_copy() -> None:
    widget = AgentOnboarding()
    sections = widget.render_content(load_keymap_registry({}))
    plugins_text = _section_plain(sections, "#agent-onboarding-plugins")

    assert "Extend sase from the Admin Center" in plugins_text
    assert "SASE Admin Center" in plugins_text
    assert "Updates" in plugins_text
    assert "install a plugin" in plugins_text
    assert "update sase & all plugins" in plugins_text
    assert "sase-github" in plugins_text
    assert "GitHub PR & repo workflows" in plugins_text


def test_plugins_card_uses_active_admin_center_keymap() -> None:
    registry = load_keymap_registry({"keymaps": {"app": {"open_config_center": "f2"}}})
    widget = AgentOnboarding()

    sections = widget.render_content(registry)
    plugins_text = _section_plain(sections, "#agent-onboarding-plugins")

    assert "f2" in plugins_text
    assert "#" not in plugins_text


def test_agent_onboarding_numbering_hides_plugins_when_installed() -> None:
    widget = AgentOnboarding()

    assert widget.numbered_step_titles() == [
        "1 Launch your first agent",
        "2 Inspect the results",
        "3 The three tabs",
        "4 Get more help",
    ]


def test_agent_onboarding_numbering_includes_plugins_when_none_installed() -> None:
    widget = AgentOnboarding()

    widget.set_plugins_installed(False)

    assert widget.numbered_step_titles() == [
        "1 Launch your first agent",
        "2 Inspect the results",
        "3 The three tabs",
        "4 Install plugins & keep sase current",
        "5 Get more help",
    ]


def test_launch_card_includes_project_cl_hint_when_targets_exist() -> None:
    widget = AgentOnboarding()
    sections = widget.render_content(
        load_keymap_registry({}),
        launch_targets_available=True,
    )
    launch_text = _section_plain(sections, "#agent-onboarding-launch")

    assert "open the prompt bar and describe a task" in launch_text
    assert "launches an agent in your home workspace." in launch_text
    assert "launch against a specific project or PR instead." in launch_text
    assert "The prompt bar works from any tab." in launch_text


def test_launch_card_omits_project_cl_hint_without_targets() -> None:
    widget = AgentOnboarding()
    sections = widget.render_content(
        load_keymap_registry({}),
        launch_targets_available=False,
    )
    launch_text = _section_plain(sections, "#agent-onboarding-launch")

    assert "open the prompt bar and describe a task" in launch_text
    assert "launch against a specific project or PR instead." not in launch_text
    assert "The prompt bar works from any tab." in launch_text


def test_agent_onboarding_omits_modal_footer() -> None:
    registry = load_keymap_registry({})
    widget = AgentOnboarding()

    sections = widget.render_content(registry)

    assert "#agent-onboarding-footer" not in sections
