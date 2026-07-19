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
        {
            "keymaps": {
                "app": {"prev_tab": "f2"},
                "modes": {"leader_mode": {"keys": {"show_help": "f1"}}},
            }
        }
    )

    sections = ChangeSpecOnboarding.render_content(registry)
    how_text = _section_plain(sections, "#changespec-onboarding-how")
    learn_text = _section_plain(sections, "#changespec-onboarding-learn")

    assert "f2" in how_text
    assert "shift+tab" not in how_text
    assert "f1" in learn_text
    assert "full keybinding reference" in learn_text


def test_changespec_onboarding_queue_card_uses_active_keymap_registry() -> None:
    registry = load_keymap_registry(
        {
            "keymaps": {
                "app": {
                    "next_changespec": "f1",
                    "prev_changespec": "f2",
                    "show_diff": "f3",
                    "change_status": "f4",
                    "mail": "f5",
                    "edit_spec": "f6",
                    "edit_query": "f7",
                },
            }
        }
    )

    sections = ChangeSpecOnboarding.render_content(registry)
    queue_text = _section_plain(sections, "#changespec-onboarding-queue")

    for key in ("f1", "f2", "f3", "f4", "f5", "f6", "f7"):
        assert key in queue_text
    assert "show the diff" in queue_text
    assert "change status" in queue_text
    assert "mail for review" in queue_text
    assert "open the spec in $EDITOR" in queue_text
    assert "filter with a query" in queue_text


def test_changespec_onboarding_omits_modal_footer() -> None:
    registry = load_keymap_registry({})

    sections = ChangeSpecOnboarding.render_content(registry)

    assert "#changespec-onboarding-footer" not in sections
