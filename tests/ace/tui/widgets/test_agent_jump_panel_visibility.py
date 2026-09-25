"""Jump-panel visibility for mounted agent detail views."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.text import Text

from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.prompt_panel._member_roster import (
    MemberJumpNumbering,
    MemberRosterEntry,
    append_member_roster,
)
from tests.ace.tui.widgets._agent_display_clan_helpers import make_clan_agent
from tests.ace.tui.widgets._agent_display_family_helpers import make_family
from tests.ace.tui.widgets._agent_display_tribe_helpers import make_tribe_snapshot
from tests.ace.tui.widgets._agent_jump_panel_helpers import (
    _DetailApp,
    _jump_panel,
    _jump_text,
    _show_agent,
    _solo,
)


async def test_empty_state_hides_jump_panel() -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        detail.show_empty()
        await pilot.pause()
        panel = _jump_panel(detail)
        assert panel.has_class("hidden")
        assert not panel.has_targets
        assert detail.jump_panel_toggle_available() is False


async def test_plain_node_hides_jump_panel() -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        panel = _jump_panel(detail)
        assert panel.has_class("hidden")
        assert not panel.has_targets
        assert detail.jump_panel_toggle_available() is False


async def test_all_unnumbered_document_hides_jump_panel() -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        panel = _jump_panel(detail)
        solo = _solo()
        entries = (
            MemberRosterEntry(
                identity=(solo.identity[0], "spent", None),
                presented_name="spent",
                label="spent",
                kind="agent",
                status="RUNNING",
                model="m",
                duration="1m",
            ),
        )
        spent_map = append_member_roster(
            Text(),
            container_identity=solo.identity,
            entries=entries,
            title="NEIGHBORS",
            accent="#00D7AF",
            panel_level=FoldLevel.COLLAPSED,
            numbering=MemberJumpNumbering(total=1, capacity=0),
        )
        assert spent_map.targets == ()
        assert len(spent_map.sections) == 1
        detail._on_member_jump_map(spent_map)  # noqa: SLF001
        await pilot.pause()
        assert panel.has_class("hidden")
        assert detail.jump_panel_toggle_available() is False


async def test_family_container_shows_collapsed_panel(tmp_path: Path) -> None:
    root, _child = make_family(tmp_path)
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, root, pilot)
        panel = _jump_panel(detail)
        assert not panel.has_class("hidden")
        assert panel.has_targets
        assert not panel.is_expanded
        assert detail.jump_panel_toggle_available() is True
        assert "JUMP" in str(panel.border_title)
        assert "FAMILY SHELLS" in str(panel.border_title)
        assert "more" in str(panel.border_subtitle)
        assert len(_jump_text(panel).splitlines()) <= 2


async def test_clan_selection_shows_jump_panel() -> None:
    member = make_clan_agent(
        "clan-test", status="RUNNING", start=datetime(2024, 1, 1), stop=None
    )
    container = project_clan_tree([member])[0]
    assert container.is_clan_container
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, container, pilot)
        panel = _jump_panel(detail)
        assert not panel.has_class("hidden")
        assert panel.has_targets
        assert "CLAN MEMBERS" in str(panel.border_title)
        assert detail.jump_panel_toggle_available() is True


async def test_tribe_panel_shows_jump_panel() -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.show_tribe_summary(make_tribe_snapshot())
        await pilot.pause()
        panel = _jump_panel(detail)
        assert not panel.has_class("hidden")
        assert panel.has_targets
        assert "TRIBE MEMBERS" in str(panel.border_title)


async def test_panel_sits_below_secondary_scroll_in_every_layout(
    tmp_path: Path,
) -> None:
    from sase.ace.tui.widgets.decks.model import DeckId, DeckLayout

    root, _child = make_family(tmp_path)
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, root, pilot)
        panel = _jump_panel(detail)
        detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
        await pilot.pause()
        detail.show_deck(0, DeckId.MAIN)
        detail.show_deck(1, DeckId.FILES)
        await pilot.pause()
        assert not panel.has_class("hidden")
        area = detail.query_one("#agent-deck-area")
        assert panel.region.y >= area.region.bottom
        assert panel.region.bottom <= detail.region.bottom


async def test_search_overlay_keeps_jump_panel_visible(tmp_path: Path) -> None:
    root, _child = make_family(tmp_path)
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, root, pilot)
        deck_panel = detail.deck_area.focused_panel()
        assert deck_panel is not None
        deck_panel.show_search_overlay()
        await pilot.pause()
        panel = _jump_panel(detail)
        assert not panel.has_class("hidden")
        assert detail.jump_panel_toggle_available() is True
        deck_panel.hide_search_overlay()
        await pilot.pause()
        assert not panel.has_class("hidden")


async def test_hint_document_hides_panel_and_back(tmp_path: Path) -> None:
    root, _child = make_family(tmp_path)
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, root, pilot)
        panel = _jump_panel(detail)
        assert not panel.has_class("hidden")

        detail.update_display_with_hints(root)
        await pilot.pause()
        assert panel.has_class("hidden")
        assert detail.jump_panel_toggle_available() is False

        await _show_agent(detail, root, pilot)
        assert not panel.has_class("hidden")
        assert detail.jump_panel_toggle_available() is True
