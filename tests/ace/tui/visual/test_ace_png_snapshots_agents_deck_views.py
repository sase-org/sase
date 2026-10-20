"""sase's TUI PNG visual snapshots for Agents deck views.

Covers the view chip (effective layout plus lock) on Main and Files decks:
automatic page blocks, one ``P`` to locked page cards, two ``P`` to locked
spread, a narrow split with a focused lock versus an unfocused auto chip, a
forced Files spread, and a media-blocked Files spread request.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets import AgentDetail
from sase.ace.tui.widgets.decks.availability import DeckAvailability
from sase.ace.tui.widgets.decks.model import DeckId, DeckView, RenderMode
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import show_reply_card
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture
from tests.ace.tui.widgets._agent_display_agent_session_helpers import (
    write_phase_content,
)

pytestmark = pytest.mark.visual

_STARTED = datetime(2026, 9, 24, 10, 0, 0)


def _view_turn(
    tmp_path: Path,
    session: str,
    role: str,
    suffix: str,
    index: int,
    *,
    extra_reply_lines: int = 0,
    **overrides: object,
) -> Agent:
    """Build one concrete turn member with deterministic content and times."""
    directory = tmp_path / f"{session}-{suffix.strip('-')}"
    directory.mkdir(parents=True, exist_ok=True)
    write_phase_content(directory, role)
    if extra_reply_lines:
        with open(directory / "response.md", "a", encoding="utf-8") as handle:
            for line in range(extra_reply_lines):
                handle.write(f"{role} filler line {line:03d} keeps the block tall.\n")
    start = _STARTED + timedelta(minutes=2 * index)
    values: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "visual-views",
        "project_file": "/workspace/sase/visual_views.sase",
        "status": "DONE",
        "start_time": start,
        "stop_time": start + timedelta(minutes=1),
        "raw_suffix": f"2026092410{index:02d}00",
        "artifacts_dir": str(directory),
        "response_path": str(directory / "response.md"),
        "agent_name": f"visual{session}{suffix}",
        "agent_session": f"visual{session}",
        "agent_session_role": role,
        "role_suffix": suffix,
        "model": "claude/opus",
    }
    values.update(overrides)
    return Agent(**values)  # type: ignore[arg-type]


def _view_session(tmp_path: Path, *, extra_reply_lines: int = 0) -> Agent:
    """Build a deterministic session whose Reply auto-resolves to page blocks.

    Mirrors the deck-blocks ``paged newest`` fixture shape (plan, gate,
    monitor, then a running code turn), so the tall newest block lands the
    Main deck in block-paged AUTO.
    """
    plan = _view_turn(tmp_path, "views", "plan", "--plan", 0, plan_chain_root=True)
    gate = _view_turn(
        tmp_path,
        "views",
        "gate",
        "--gate",
        1,
        status="APPROVE",
        gate_id="g123abc456def",
        gate_kind="approval",
        gate_state="answered",
        gate_start_status="APPROVE",
        gate_stop_status="APPROVED",
        gate_accent="#0BCDEC",
        gate_label="Approve deploy",
    )
    monitor = _view_turn(
        tmp_path,
        "views",
        "monitor",
        "--mon",
        2,
        status="MONITORED",
        monitor_id="m123abc456def",
        monitor_state="completed",
        monitor_label="just check",
        monitor_command="just check",
    )
    code = _view_turn(
        tmp_path,
        "views",
        "code",
        "--code",
        3,
        extra_reply_lines=extra_reply_lines,
        status="RUNNING",
        stop_time=None,
    )
    members = [plan, gate, monitor, code]
    plan.followup_agents = members[1:]
    for member in members[1:]:
        member.agent_session_container = plan
    assert plan.is_agent_session_container_row is True
    return plan


def _files_agent(tmp_path: Path, *, lines_per_file: int = 200) -> Agent:
    """Build a session agent with two tall text files (AUTO pages Files)."""
    root = _view_turn(tmp_path, "viewfiles", "plan", "--plan", 10, plan_chain_root=True)
    first = tmp_path / "view_alpha.py"
    second = tmp_path / "view_beta.py"
    first.write_text(
        "".join(f"alpha line {i:04d}\n" for i in range(lines_per_file)),
        encoding="utf-8",
    )
    second.write_text(
        "".join(f"beta line {i:04d}\n" for i in range(lines_per_file)),
        encoding="utf-8",
    )
    root.extra_files = [str(first), str(second)]
    return root


def _bundle_files_agent(tmp_path: Path) -> Agent:
    """Build a session agent whose Files deck lists recorded instruction bundles."""
    root = _view_turn(
        tmp_path, "viewbundles", "plan", "--plan", 10, plan_chain_root=True
    )
    instructions = tmp_path / "artifacts" / "instructions"
    instructions.mkdir(parents=True, exist_ok=True)
    root_bundle = instructions / "00-claude.md"
    helper_bundle = instructions / "00-claude.helper.md"
    root_bundle.write_text(
        "# Root bundle\n\nYou are a SASE agent. Follow the recorded instructions.\n",
        encoding="utf-8",
    )
    helper_bundle.write_text(
        "# Helper bundle\n\nReturn your result to the parent agent.\n",
        encoding="utf-8",
    )
    root.instruction_bundle_files = [str(root_bundle), str(helper_bundle)]
    return root


def _media_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Agent:
    """Build a session agent whose Files deck holds text plus an image.

    Slots are bare basenames with cwd pointed at ``tmp_path`` so the paged
    file header renders identically on every run and machine (absolute tmp
    paths embed a run counter that drifts goldens).
    """
    monkeypatch.chdir(tmp_path)
    root = _view_turn(tmp_path, "viewmedia", "plan", "--plan", 20, plan_chain_root=True)
    notes = tmp_path / "view_notes.md"
    notes.write_text("".join(f"note line {i}\n" for i in range(10)), encoding="utf-8")
    shot = tmp_path / "view_shot.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\n")
    root.extra_files = ["view_notes.md", "view_shot.png"]
    return root


def _title_plain(detail: AgentDetail, panel_index: int = 0) -> str:
    return detail.deck_area.panel(panel_index)._border_title.plain


async def _goto_agents(page: AcePage, count: int) -> None:
    await wait_for_startup(page)
    await page.press("shift+tab")
    await page.expect_state("tab", "agents")
    await page.expect_state("agent_count", count)
    await wait_for_visual_idle(page)


async def _show_reply(page: AcePage) -> AgentDetail:
    return await show_reply_card(page)


async def _press_view(page: AcePage, detail: AgentDetail, view: DeckView) -> None:
    """Press ``P`` until the focused Main panel fixes ``view`` (toast-free)."""
    await page.press("P")
    await wait_for_state(
        page,
        lambda: detail.deck_area.panel(0).view_policy(DeckId.MAIN) is view,
        description=f"Main deck fixes {view.value}",
    )
    # Deferred Main bodies apply off the pump; wait for this generation
    # before the snapshot so pixels match the synchronous layout.
    await wait_for_state(
        page,
        lambda: (
            int(getattr(detail.deck_area.panel(0), "_main_view_applied_generation", 0))
            >= int(getattr(detail.deck_area.panel(0), "_view_generation", 0))
        ),
        description="Main deck deferred body applied",
    )
    page.app.clear_notifications()
    await wait_for_visual_idle(page)


async def test_agents_deck_view_auto_page_blocks_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(
        monkeypatch,
        agents=[_view_session(tmp_path, extra_reply_lines=60)],
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _goto_agents(page, 1)
        detail = await _show_reply(page)
        panel = detail.deck_area.panel(0)
        card = panel._main_document.card("reply")
        assert card is not None and card.has_block_navigation
        assert panel.effective_layout(DeckId.MAIN) is DeckView.PAGE_BLOCKS
        assert panel.view_policy(DeckId.MAIN) is DeckView.AUTO
        title = _title_plain(detail)
        assert "BLOCKS" in title or "PAGE BLOCKS" in title or " B " in f" {title} "
        assert "\U0001f512" not in title
        assert panel._block_rail_widget().has_class("-shown")
        ace_png_visual.assert_page_png(
            page,
            "agents_deck_view_auto_page_blocks_120x40",
            title="ACE agents deck view auto page blocks",
        )


async def test_agents_deck_view_fixed_page_cards_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(
        monkeypatch,
        agents=[_view_session(tmp_path, extra_reply_lines=60)],
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _goto_agents(page, 1)
        detail = await _show_reply(page)
        panel = detail.deck_area.panel(0)
        assert panel.effective_layout(DeckId.MAIN) is DeckView.PAGE_BLOCKS
        # One P widens page blocks to fixed page cards.
        await _press_view(page, detail, DeckView.PAGE_CARDS)
        assert panel.effective_layout(DeckId.MAIN) is DeckView.PAGE_CARDS
        title = _title_plain(detail)
        assert "CARDS" in title or "PAGE CARDS" in title
        assert "\U0001f512" in title
        ace_png_visual.assert_page_png(
            page,
            "agents_deck_view_fixed_page_cards_120x40",
            title="ACE agents deck view fixed page cards",
        )


async def test_agents_deck_view_fixed_spread_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(
        monkeypatch,
        agents=[_view_session(tmp_path, extra_reply_lines=60)],
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _goto_agents(page, 1)
        detail = await _show_reply(page)
        panel = detail.deck_area.panel(0)
        assert panel.effective_layout(DeckId.MAIN) is DeckView.PAGE_BLOCKS
        # Two P presses widen through page cards to locked spread.
        await _press_view(page, detail, DeckView.PAGE_CARDS)
        await _press_view(page, detail, DeckView.SPREAD)
        assert panel.effective_layout(DeckId.MAIN) is DeckView.SPREAD
        title = _title_plain(detail)
        assert "SPREAD" in title
        assert "\U0001f512" in title
        assert "\u2503" not in title
        ace_png_visual.assert_page_png(
            page,
            "agents_deck_view_fixed_spread_120x40",
            title="ACE agents deck view fixed spread",
        )


async def test_agents_deck_view_split_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(
        monkeypatch,
        agents=[_view_session(tmp_path, extra_reply_lines=60)],
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _goto_agents(page, 1)
        detail = await _show_reply(page)
        # Force known no-files/no-tools so the new panel duplicates Main.
        detail.deck_area.panel(0)._availability = {
            DeckId.MAIN: DeckAvailability(True, 2),
            DeckId.FILES: DeckAvailability(False, 0),
            DeckId.TOOLS: DeckAvailability(False, 0),
        }
        await page.press("vertical_line")
        await wait_for_state(
            page,
            lambda: detail.deck_area.panel(1).deck is DeckId.MAIN,
            description="Right panel duplicates the Main deck",
        )
        detail.set_deck_preferred_card(0, "reply")
        detail.set_deck_preferred_card(1, "reply")
        page.app._refresh_agents_display(list_changed=True, defer_detail=True)
        await wait_for_state(
            page,
            lambda: (
                detail.deck_area.panel(0).main_view.active_card_id == "reply"
                and detail.deck_area.panel(1).main_view.active_card_id == "reply"
            ),
            description="Both panels show the Reply card",
        )
        # The new right panel takes focus; move focus back left so P fixes
        # the left panel while the right panel stays automatic.
        await page.press("ctrl+f")
        await wait_for_state(
            page,
            lambda: detail.deck_area.focused_panel().panel_index == 0,
            description="Left panel is focused",
        )
        # Fix the focused (left) panel; the right panel stays automatic.
        await page.press("P")
        await wait_for_state(
            page,
            lambda: (
                detail.deck_area.panel(0).view_policy(DeckId.MAIN) is not DeckView.AUTO
            ),
            description="Left panel fixes its view",
        )
        page.app.clear_notifications()
        await wait_for_visual_idle(page)
        assert detail.deck_area.panel(1).view_policy(DeckId.MAIN) is DeckView.AUTO
        # Narrow split panels ladder down to short or tiny rungs.
        left_title = _title_plain(detail, 0)
        right_title = _title_plain(detail, 1)
        assert "\U0001f512" in left_title
        assert "\U0001f512" not in right_title
        ace_png_visual.assert_page_png(
            page,
            "agents_deck_view_split_narrow_120x40",
            title="ACE agents deck view split narrow",
        )


async def test_agents_deck_view_files_fixed_spread_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[_files_agent(tmp_path)])
    # A wider terminal keeps the deck column wide enough for the long view
    # badge; at 120 columns the title ladder drops to a shorter rung.
    async with AcePage(query='"visual"', size=(160, 40), patches=patches()) as page:
        await _goto_agents(page, 1)
        detail = page.app.query_one("#agent-detail-panel", AgentDetail)
        detail.show_deck(0, DeckId.FILES)
        panel = detail.deck_area.panel(0)
        await wait_for_state(page, detail.is_file_visible, description="Files deck")
        await wait_for_state(
            page,
            lambda: panel._render_mode.get(DeckId.FILES) is RenderMode.PAGED,
            description="Files deck settles paged under AUTO",
        )
        assert panel.view_policy(DeckId.FILES) is DeckView.AUTO
        # One P fixes spread; the complete probe spreads off-thread.
        await page.press("P")
        await wait_for_state(
            page,
            lambda: panel.view_policy(DeckId.FILES) is DeckView.SPREAD,
            description="Files deck fixes spread",
        )
        page.app.clear_notifications()
        await wait_for_state(
            page,
            lambda: panel.is_spread(DeckId.FILES),
            description="Files deck spreads after the complete probe",
        )
        await wait_for_visual_idle(page)
        files_title = _title_plain(detail)
        assert "SPREAD" in files_title
        assert "\U0001f512" in files_title
        ace_png_visual.assert_page_png(
            page,
            "agents_deck_view_files_fixed_spread_160x40",
            title="ACE agents deck view Files fixed spread",
        )


async def test_agents_deck_view_files_instruction_bundles_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[_bundle_files_agent(tmp_path)])
    async with AcePage(query='"visual"', size=(160, 40), patches=patches()) as page:
        await _goto_agents(page, 1)
        detail = page.app.query_one("#agent-detail-panel", AgentDetail)
        detail.show_deck(0, DeckId.FILES)
        panel = detail.deck_area.panel(0)
        await wait_for_state(page, detail.is_file_visible, description="Files deck")
        await wait_for_state(
            page,
            lambda: "00-claude.md" in (panel.file_view.current_source_label() or ""),
            description="Files deck shows the root bundle",
        )
        assert (
            panel.file_view.source_label_for_slot(panel.file_view._file_list[0]).tag
            == "bundle"
        )
        await wait_for_svg_contains(page, "00-claude.md")
        await wait_for_svg_contains(page, "You are a SASE agent")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "agents_deck_view_files_instruction_bundles_160x40",
            title="ACE agents deck Files instruction bundles",
        )


async def test_agents_deck_view_files_media_blocked_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[_media_agent(tmp_path, monkeypatch)])
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _goto_agents(page, 1)
        detail = page.app.query_one("#agent-detail-panel", AgentDetail)
        detail.show_deck(0, DeckId.FILES)
        panel = detail.deck_area.panel(0)
        await wait_for_state(page, detail.is_file_visible, description="Files deck")
        await wait_for_state(
            page,
            lambda: panel._files_probe_slots != (),
            description="Files probe saw both slots",
        )
        # P is unavailable on a single-layout media deck, so the spread
        # request takes the palette path: the preference is kept, the deck
        # stays paged, and the badge names the blocked request.
        assert detail.set_focused_deck_view(DeckView.SPREAD) is True
        await wait_for_state(
            page,
            lambda: bool(panel._files_spread_blocked),
            description="Files deck reports spread blocked",
        )
        assert detail.cycle_focused_deck_view() is None
        page.app.clear_notifications()
        await wait_for_visual_idle(page)
        assert panel._render_mode.get(DeckId.FILES) is RenderMode.PAGED
        blocked_title = _title_plain(detail)
        assert (
            "spread unavailable" in blocked_title
            or "no spread" in blocked_title
            or "!" in blocked_title
        )
        ace_png_visual.assert_page_png(
            page,
            "agents_deck_view_files_media_blocked_120x40",
            title="ACE agents deck view Files media blocked",
        )


async def test_agents_deck_view_split_spread_paged_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(
        monkeypatch,
        agents=[_view_session(tmp_path, extra_reply_lines=60)],
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _goto_agents(page, 1)
        detail = await _show_reply(page)
        detail.deck_area.panel(0)._availability = {
            DeckId.MAIN: DeckAvailability(True, 2),
            DeckId.FILES: DeckAvailability(False, 0),
            DeckId.TOOLS: DeckAvailability(False, 0),
        }
        await page.press("vertical_line")
        await wait_for_state(
            page,
            lambda: detail.deck_area.panel(1).deck is DeckId.MAIN,
            description="Right panel duplicates the Main deck",
        )
        detail.set_deck_preferred_card(0, "reply")
        detail.set_deck_preferred_card(1, "reply")
        page.app._refresh_agents_display(list_changed=True, defer_detail=True)
        await wait_for_state(
            page,
            lambda: (
                detail.deck_area.panel(0).main_view.active_card_id == "reply"
                and detail.deck_area.panel(1).main_view.active_card_id == "reply"
            ),
            description="Both panels show the Reply card",
        )
        await page.press("ctrl+f")
        await wait_for_state(
            page,
            lambda: detail.deck_area.focused_panel().panel_index == 0,
            description="Left panel is focused",
        )
        await _press_view(page, detail, DeckView.PAGE_CARDS)
        await _press_view(page, detail, DeckView.SPREAD)
        page.app.clear_notifications()
        await wait_for_visual_idle(page)
        left_title = _title_plain(detail, 0)
        right_title = _title_plain(detail, 1)
        assert (
            "SPREAD" in left_title
            or " S " in f" {left_title} "
            or "\U0001f512" in left_title
        )
        assert "\u2503" not in left_title
        # Split-narrow panels collapse the unfocused PAGE BLOCKS chip to
        # ``B  2/2``; N/M and the tiny ``B`` mark paged chrome when ┃/‹
        # do not fit.
        assert (
            "\u2503" in right_title
            or "\u2039" in right_title
            or "2/2" in right_title
            or " B " in f" {right_title} "
            or "BLOCKS" in right_title
        )
        assert "\u25b4" not in right_title and "\u25be" not in right_title
        ace_png_visual.assert_page_png(
            page,
            "agents_deck_view_split_spread_paged_120x40",
            title="ACE agents deck view split spread and paged",
        )


async def test_agents_deck_view_one_card_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from rich.text import Text

    from sase.ace.tui.widgets.decks.card_part import context_card
    from sase.ace.tui.widgets.decks.main_document import MainDeckDocument

    patch_startup_loaders(
        monkeypatch,
        agents=[_view_session(tmp_path, extra_reply_lines=0)],
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _goto_agents(page, 1)
        detail = await _show_reply(page)
        panel = detail.deck_area.panel(0)
        panel.show_main_document(
            MainDeckDocument(
                cards=(context_card(Text("only-context")),),
                subject="one-card",
                partial=False,
                digest="one-card-heading",
            ),
            "context",
        )
        await wait_for_state(
            page,
            lambda: len(panel._main_document.cards) == 1,
            description="Main deck shows one card",
        )
        panel.refresh_chrome()
        page.app.clear_notifications()
        await wait_for_visual_idle(page)
        title = _title_plain(detail)
        assert "\u2503" not in title
        assert "SPREAD" not in title
        assert "PAGE" not in title
        ace_png_visual.assert_page_png(
            page,
            "agents_deck_view_one_card_120x40",
            title="ACE agents deck view one-card heading",
        )


async def test_agents_deck_view_spread_all_in_view_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from rich.text import Text

    from sase.ace.tui.widgets.decks.card_part import context_card, reply_card
    from sase.ace.tui.widgets.decks.main_document import MainDeckDocument

    patch_startup_loaders(
        monkeypatch,
        agents=[_view_session(tmp_path, extra_reply_lines=0)],
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _goto_agents(page, 1)
        detail = await _show_reply(page)
        panel = detail.deck_area.panel(0)
        panel.show_main_document(
            MainDeckDocument(
                cards=(
                    context_card(Text("all in view context")),
                    reply_card(Text("all in view reply")),
                ),
                subject="all-in-view",
                partial=False,
                digest="all-in-view-spread",
            ),
            # Open at the first card with no scroll reserve so the whole
            # tiny deck fits the viewport: the title names the all-in-view
            # state instead of a direction.
            "context",
        )
        await wait_for_state(
            page,
            lambda: panel.is_spread(DeckId.MAIN),
            description="Main deck spreads the tiny document",
        )
        await wait_for_visual_idle(page)
        panel.refresh_chrome()
        page.app.clear_notifications()
        await wait_for_visual_idle(page)
        title = _title_plain(detail)
        assert "\u2503" not in title
        assert "SPREAD" in title
        assert "in view" in title
        assert "\u25b4" not in title and "\u25be" not in title
        ace_png_visual.assert_page_png(
            page,
            "agents_deck_view_spread_all_in_view_120x40",
            title="ACE agents deck view spread all in view",
        )


async def test_agents_deck_view_paged_bottom_cue_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from textual.containers import VerticalScroll

    patch_startup_loaders(
        monkeypatch,
        agents=[_view_session(tmp_path, extra_reply_lines=60)],
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _goto_agents(page, 1)
        detail = await _show_reply(page)
        panel = detail.deck_area.panel(0)
        assert panel.effective_layout(DeckId.MAIN) is DeckView.PAGE_BLOCKS
        # One P widens page blocks to locked page cards: "+1 card" cue.
        await _press_view(page, detail, DeckView.PAGE_CARDS)
        assert panel.effective_layout(DeckId.MAIN) is DeckView.PAGE_CARDS
        panel.set_focused(True)
        scroll = panel.query_one("#agent-deck-panel-0-main-scroll", VerticalScroll)
        try:
            max_y = int(scroll.max_scroll_y)
        except Exception:
            max_y = 0
        if max_y > 0:
            scroll.scroll_to(y=max_y, animate=False)
        await wait_for_state(
            page,
            lambda: panel._paged_at_bottom(DeckId.MAIN) is True,
            description="Paged Main deck reaches its bottom",
        )
        page.app.clear_notifications()
        await wait_for_visual_idle(page)
        subtitle = panel._border_subtitle.plain
        assert "+1 card" in subtitle
        ace_png_visual.assert_page_png(
            page,
            "agents_deck_view_paged_bottom_cue_120x40",
            title="ACE agents deck view paged bottom cue",
        )
