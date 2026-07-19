"""Tests for the AXE Tab Guide onboarding widget."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.widgets.axe_onboarding import AxeOnboarding


def _section_plain(sections: dict[str, Text], selector: str) -> str:
    return sections[selector].plain


def test_axe_onboarding_content_describes_axe_chops_bgcmds_and_docs() -> None:
    sections = AxeOnboarding.render_content(load_keymap_registry({}))
    rendered = "\n".join(text.plain for text in sections.values())

    assert "Automation, always on" in rendered
    assert "Axe is the daemon" in rendered
    assert "Axe starts automatically with sase ace" in rendered
    assert "start or stop Axe (with the Axe row selected)" in rendered
    assert "lumberjack" in rendered
    assert "chops" in rendered
    assert "open the captured output in your editor" in rendered
    assert "runs any shell command in a background slot" in rendered
    assert "kill the selected running command" in rendered
    assert "https://sase.sh" in rendered
    assert "https://sase.sh/axe/" in rendered
    assert "https://sase.sh/workflow_spec/" in rendered
    assert "https://sase.sh/mentors/" in rendered
    assert ",?" in rendered


def test_axe_onboarding_uses_active_keymap_registry() -> None:
    registry = load_keymap_registry(
        {
            "keymaps": {
                "app": {
                    "kill_agent": "f4",
                    "edit_spec": "f5",
                    "run_workflow": "f3",
                },
                "modes": {
                    "bang_mode": {"prefix": "B", "keys": {"run_cmd": "R"}},
                    "leader_mode": {"keys": {"show_help": "f1"}},
                },
            }
        }
    )

    sections = AxeOnboarding.render_content(registry)
    what_text = _section_plain(sections, "#axe-onboarding-what")
    chops_text = _section_plain(sections, "#axe-onboarding-chops")
    bgcmd_text = _section_plain(sections, "#axe-onboarding-bgcmd")
    learn_text = _section_plain(sections, "#axe-onboarding-learn")

    assert "f4" in what_text
    assert "f4" in bgcmd_text
    assert "f5" in chops_text
    assert "f3" in chops_text
    assert "BR" in bgcmd_text
    assert "!!" not in bgcmd_text
    assert "f1" in learn_text
    assert ",T" not in learn_text
    assert "#axe-onboarding-footer" not in sections
