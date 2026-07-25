"""Tests for the ACE help modal tab-scoped content."""

from __future__ import annotations

from rich.text import Text

from sase.ace.testing import AcePage
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.modals.help_modal import HelpModal
from sase.ace.tui.modals.help_modal.query_sections import add_saved_queries_section


def test_help_modal_refresh_for_tab_rebuilds_sections() -> None:
    modal = HelpModal(
        current_tab="changespecs",
        active_query='"feature"',
        registry=load_keymap_registry({}),
        saved_queries={"1": '"feature"'},
    )

    left = modal._build_left_column().plain
    right = modal._build_right_column().plain
    assert "Artifact Sub-tabs" in left
    assert "Commits Pane" in left
    assert "Bugs Pane" in right
    assert "Plans Pane" in right
    assert "Chats Pane" in right
    assert "Filter kind, status, or tier" in right
    assert "Filter project or creation date" in right
    assert "Title/body/id/metadata (AND)" in right
    assert "PR Actions" in right
    assert "[*1]" in left
    assert "*1-9 / *0" in right
    assert "1 / 2 / 3 / 4 / 5" in left
    assert "Jump all five artifact panes" in left
    assert "Cycle all five artifact panes" in left
    combined = left + right
    assert "Select first / last entry" in combined
    assert "Scroll right detail down / up" in combined
    assert "Move down / up 10 entries" in combined
    assert "Move down / up 5 entries" not in combined
    assert "Hint jump (' first / back)" in combined
    assert "omitted/all unlimited" in combined
    assert "PR Navigation" in combined
    assert "Indent / dedent bullet marker" in combined

    modal.refresh_for_tab("agents", active_query=None)

    assert modal._current_tab == "agents"
    assert modal._active_query is None
    assert "Agents Tab" in modal._build_title().plain
    agents_left = modal._build_left_column().plain
    agents_right = modal._build_right_column().plain
    assert "Agent Actions" in agents_left
    assert "Jump numbered member/neighbor" in agents_left
    assert "Neighbors modal (see NEIGHBORS)" in agents_left
    assert "Cycle section/member forward" in agents_right
    assert "Inherit MEMBERS then panel" in agents_right


async def test_help_digits_do_not_load_saved_queries(monkeypatch) -> None:
    async with AcePage(query='"feature"') as page:
        calls: list[str] = []
        monkeypatch.setattr(
            page.app,
            "action_load_saved_query_7",
            lambda: calls.append("7"),
        )
        page.app.push_screen(
            HelpModal(
                current_tab="changespecs",
                active_query=page.app.canonical_query_string,
                registry=page.app._keymap_registry,
                saved_queries={"7": '"other"'},
            )
        )
        await page.expect_modal("HelpModal")

        await page.press("7", "2")
        await page.pause()
        assert calls == []
        assert page.app.canonical_query_string == '"feature"'
        assert page.state["modal"] == "HelpModal"


def test_saved_query_help_badges_keep_fixed_box_width() -> None:
    text = Text()
    add_saved_queries_section(
        text,
        'STATUS="Ready"',
        queries={"1": 'STATUS="Ready"', "9": "X" * 100},
        saved_query_prefix="Ctrl+X",
    )

    lines = text.plain.splitlines()[1:]
    assert lines
    assert all(len(line) == 57 for line in lines)
    assert "[Ctrl+X1]" in text.plain
