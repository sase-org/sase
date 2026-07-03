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
    assert "?" not in learn_text
