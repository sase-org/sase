"""Tests for the PRs-tab onboarding widget."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.widgets.changespec_onboarding import ChangeSpecOnboarding


def _section_plain(sections: dict[str, Text], selector: str) -> str:
    return sections[selector].plain


def test_changespec_onboarding_content_includes_docs_lifecycle_and_storage() -> None:
    sections = ChangeSpecOnboarding.render_content(load_keymap_registry({}))
    rendered = "\n".join(text.plain for text in sections.values())

    assert "Your agents' work, shipped as PRs" in rendered
    assert "https://sase.sh/change_spec/" in rendered
    assert "https://sase.sh/vcs/" in rendered
    assert "https://sase.sh/plugins/" in rendered
    assert "~/.sase/projects/" in rendered
    for status in ("WIP", "Draft", "Ready", "Mailed", "Submitted"):
        assert status in rendered


def test_changespec_onboarding_uses_active_keymap_registry() -> None:
    registry = load_keymap_registry(
        {"keymaps": {"app": {"prev_tab": "f2", "show_help": "f1"}}}
    )

    sections = ChangeSpecOnboarding.render_content(registry)
    how_text = _section_plain(sections, "#changespec-onboarding-how")
    learn_text = _section_plain(sections, "#changespec-onboarding-learn")

    assert "f2" in how_text
    assert "shift+tab" not in how_text
    assert "f1" in learn_text
    assert "open the help pop-up" in learn_text


def test_changespec_onboarding_modal_footer_replaces_empty_state_footer() -> None:
    registry = load_keymap_registry({})

    tab_sections = ChangeSpecOnboarding.render_content(registry)
    modal_sections = ChangeSpecOnboarding.render_content(registry, context="modal")

    tab_footer = _section_plain(tab_sections, "#changespec-onboarding-footer")
    modal_footer = _section_plain(modal_sections, "#changespec-onboarding-footer")

    assert "Your first ChangeSpec replaces this guide" in tab_footer
    assert "esc closes" in modal_footer
    assert ",?" in modal_footer
    assert "Your first ChangeSpec" not in modal_footer
