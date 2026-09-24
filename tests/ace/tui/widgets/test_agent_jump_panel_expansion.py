"""Jump-panel expansion, roster repaint, and layout pinning."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from tests.ace.tui.widgets._agent_display_family_helpers import make_family
from tests.ace.tui.widgets._agent_jump_panel_helpers import (
    _DetailApp,
    _jump_panel,
    _jump_text,
    _labeled_map,
    _labeled_map_and_roster,
    _show_agent,
    _solo,
)


async def test_toggle_expands_to_every_target_and_back(tmp_path: Path) -> None:
    root, _child = make_family(tmp_path)
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, root, pilot)
        panel = _jump_panel(detail)

        assert detail.toggle_jump_panel_expanded() is True
        await pilot.pause()
        assert panel.is_expanded
        assert "less" in str(panel.border_subtitle)
        body = _jump_text(panel)
        assert "--plan" in body and "--code" in body
        assert "❖ FAMILY SHELLS" in body
        # Expanded content equals the carried roster verbatim.
        assert panel._member_roster is not None  # noqa: SLF001
        assert body.strip() == panel._member_roster.plain.strip()  # noqa: SLF001

        assert detail.toggle_jump_panel_expanded() is False
        await pilot.pause()
        assert not panel.is_expanded
        assert "more" in str(panel.border_subtitle)


async def test_expanded_roster_matches_carried_text_and_metadata_has_no_roster(
    tmp_path: Path,
) -> None:
    from sase.ace.tui.widgets.prompt_panel._identity_header import (
        find_member_roster,
    )
    from sase.ace.tui.widgets.renderable_text import renderable_to_text as to_text

    root, _child = make_family(tmp_path)
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, root, pilot)
        panel = _jump_panel(detail)
        prompt = detail.query_one("#agent-prompt-panel", AgentPromptPanel)
        content = getattr(prompt, "_identity_last_content", None)
        roster = find_member_roster(content)
        assert roster is not None
        metadata_text = to_text(content) or ""
        assert "❖ FAMILY SHELLS" not in metadata_text
        assert detail.toggle_jump_panel_expanded() is True
        await pilot.pause()
        assert _jump_text(panel).strip() == roster.plain.strip()
        assert detail.toggle_jump_panel_expanded() is False
        await pilot.pause()


async def test_expanded_roster_repaints_on_roster_only_change() -> None:
    from rich.text import Text as RichText

    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        solo = _solo()
        jump_map, roster = _labeled_map_and_roster(solo, ["aa", "bb"])
        assert roster is not None
        detail._on_member_jump_map(jump_map, roster)  # noqa: SLF001
        await pilot.pause()
        panel = _jump_panel(detail)
        assert detail.toggle_jump_panel_expanded() is True
        await pilot.pause()
        assert "aa" in _jump_text(panel)
        # Roster change while expanded repaints even though the map is same.
        changed = RichText(roster.plain.replace("aa", "zz"))
        detail._on_member_jump_map(jump_map, changed)  # noqa: SLF001
        await pilot.pause()
        assert "zz" in _jump_text(panel)
        # Change while collapsed is visible as soon as the panel expands.
        assert detail.toggle_jump_panel_expanded() is False
        await pilot.pause()
        changed_again = RichText(changed.plain.replace("bb", "qq"))
        detail._on_member_jump_map(jump_map, changed_again)  # noqa: SLF001
        await pilot.pause()
        assert "qq" not in _jump_text(panel)
        assert detail.toggle_jump_panel_expanded() is True
        await pilot.pause()
        assert "qq" in _jump_text(panel)


async def test_expanded_state_persists_across_selection(tmp_path: Path) -> None:
    root, _child = make_family(tmp_path)
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, root, pilot)
        assert detail.toggle_jump_panel_expanded() is True

        await _show_agent(detail, _solo(), pilot)
        await _show_agent(detail, root, pilot)
        panel = _jump_panel(detail)
        assert panel.is_expanded
        assert "less" in str(panel.border_subtitle)


async def test_identity_change_resets_panel_scroll(tmp_path: Path) -> None:
    root, _child = make_family(tmp_path)
    app = _DetailApp()
    async with app.run_test(size=(80, 12)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, root, pilot)
        detail._on_member_jump_map(  # noqa: SLF001
            _labeled_map(_solo(), [f"target-{index:02d}" for index in range(12)])
        )
        assert detail.toggle_jump_panel_expanded() is True
        await pilot.pause()
        panel = _jump_panel(detail)
        assert panel.max_scroll_y > 0
        panel.scroll_y = panel.max_scroll_y
        await pilot.pause()
        assert panel.scroll_y > 0

        await _show_agent(detail, _solo(), pilot)
        assert panel.scroll_y == 0


async def test_bottom_pinned_body_stays_pinned_across_jump_toggle() -> None:
    from sase.ace.tui.widgets.decks.model import DeckId, DeckLayout

    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
        await pilot.pause()
        detail.show_deck(0, DeckId.MAIN)
        detail.show_deck(1, DeckId.FILES)
        await pilot.pause()
        detail._on_member_jump_map(_labeled_map(_solo(), ["aa", "bb"]))  # noqa: SLF001
        await pilot.pause()
        main_view = detail.deck_area.panel(0).main_view
        main_view.pin_to_bottom()
        assert bool(main_view.is_pinned_to_bottom) is True
        detail.toggle_jump_panel_expanded()
        await pilot.pause()
        main_view = detail.deck_area.panel(0).main_view
        assert bool(main_view.is_pinned_to_bottom) is True
