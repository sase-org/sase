"""sase's TUI PNG visual snapshots for Agents deck card blocks."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets import AgentDetail
from sase.ace.tui.widgets.decks.availability import DeckAvailability
from sase.ace.tui.widgets.decks.model import DeckId, RenderMode
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture
from tests.ace.tui.widgets._agent_display_agent_session_helpers import (
    write_phase_content,
)

pytestmark = pytest.mark.visual

_STARTED = datetime(2026, 9, 24, 10, 0, 0)


def _block_shell(
    tmp_path: Path,
    session: str,
    role: str,
    suffix: str,
    index: int,
    *,
    extra_reply_lines: int = 0,
    extra_context_lines: int = 0,
    tiny_content: bool = False,
    **overrides: object,
) -> Agent:
    """Build one concrete shell member with deterministic content and times."""
    directory = tmp_path / f"{session}-{suffix.strip('-')}"
    directory.mkdir(parents=True, exist_ok=True)
    write_phase_content(directory, role)
    if tiny_content:
        (directory / "raw_xprompt.md").write_text(
            f"{role} goal\n{role} scope\n", encoding="utf-8"
        )
        (directory / "01_prompt.md").write_text(f"{role} detail\n", encoding="utf-8")
        (directory / "response.md").write_text(
            f"{role} outcome line one\n{role} outcome line two\n", encoding="utf-8"
        )
    if extra_reply_lines:
        with open(directory / "response.md", "a", encoding="utf-8") as handle:
            for line in range(extra_reply_lines):
                handle.write(f"{role} filler line {line:03d} keeps the block tall.\n")
    if extra_context_lines:
        with open(directory / "01_prompt.md", "a", encoding="utf-8") as handle:
            for line in range(extra_context_lines):
                handle.write(f"{role} context line {line:03d} keeps Context tall.\n")
    start = _STARTED + timedelta(minutes=2 * index)
    values: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "visual-blocks",
        "project_file": "/workspace/sase/visual_blocks.sase",
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


def _block_session(
    tmp_path: Path,
    *,
    session: str = "alpha",
    code_shells: int = 1,
    extra_reply_lines: int = 0,
    extra_context_lines: int = 0,
    tiny_content: bool = False,
    include_gate_monitor: bool = True,
    running_last: bool = False,
) -> Agent:
    """Build a deterministic session: plan, gate, monitor, then code shells."""
    plan = _block_shell(
        tmp_path,
        session,
        "plan",
        "--plan",
        0,
        extra_reply_lines=extra_reply_lines,
        extra_context_lines=extra_context_lines,
        tiny_content=tiny_content,
        plan_chain_root=True,
    )
    members = [plan]
    base = 1
    if include_gate_monitor:
        gate = _block_shell(
            tmp_path,
            session,
            "gate",
            "--gate",
            1,
            extra_reply_lines=extra_reply_lines,
            extra_context_lines=extra_context_lines,
            tiny_content=tiny_content,
            status="APPROVE",
            gate_id="g123abc456def",
            gate_kind="approval",
            gate_state="answered",
            gate_start_status="APPROVE",
            gate_stop_status="APPROVED",
            gate_accent="#0BCDEC",
            gate_label="Approve deploy",
        )
        monitor = _block_shell(
            tmp_path,
            session,
            "monitor",
            "--mon",
            2,
            extra_reply_lines=extra_reply_lines,
            extra_context_lines=extra_context_lines,
            tiny_content=tiny_content,
            status="MONITORED",
            monitor_id="m123abc456def",
            monitor_state="completed",
            monitor_label="just check",
            monitor_command="just check",
        )
        members.extend([gate, monitor])
        base = 3
    for shell in range(code_shells):
        index = base + shell
        suffix = "--code" if code_shells == 1 else f"--code-{shell}"
        last = shell == code_shells - 1
        members.append(
            _block_shell(
                tmp_path,
                session,
                "code",
                suffix,
                index,
                extra_reply_lines=extra_reply_lines,
                extra_context_lines=extra_context_lines,
                tiny_content=tiny_content,
                **(
                    {"status": "RUNNING", "stop_time": None}
                    if running_last and last
                    else {}
                ),
            )
        )
    root = members[0]
    root.followup_agents = members[1:]
    for member in members[1:]:
        member.agent_session_container = root
    assert root.is_agent_session_container_row is True
    return root


async def _goto_agents(page: AcePage, count: int) -> None:
    await wait_for_startup(page)
    await page.press("shift+tab")
    await page.expect_state("tab", "agents")
    await page.expect_state("agent_count", count)
    await wait_for_visual_idle(page)


async def _show_reply(page: AcePage) -> AgentDetail:
    detail = page.app.query_one("#agent-detail-panel", AgentDetail)
    await wait_for_state(
        page,
        lambda: set(detail._main_deck_document.card_ids) == {"context", "reply"},
        description="Main deck has Context and Reply cards",
    )
    await page.press("ctrl+j")
    await wait_for_state(
        page,
        lambda: detail.deck_area.panel(0).main_view.active_card_id == "reply",
        description="Main deck shows the Reply card",
    )
    await wait_for_visual_idle(page)
    return detail


async def test_agents_deck_blocks_paged_newest_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(
        monkeypatch,
        agents=[
            _block_session(tmp_path, extra_reply_lines=60, running_last=True),
        ],
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _goto_agents(page, 1)
        detail = await _show_reply(page)
        panel = detail.deck_area.panel(0)
        card = panel._main_document.card("reply")
        assert card is not None and card.has_block_navigation
        assert panel.block_mode_for_active_card() is RenderMode.PAGED
        # Every node lands on its newest block.
        assert panel.main_view.active_block_id("reply") == card.block_ids[-1]
        ace_png_visual.assert_page_png(
            page,
            "agents_deck_blocks_paged_newest_120x40",
            title="ACE agents deck blocks paged on newest",
        )


async def test_agents_deck_blocks_paged_older_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(
        monkeypatch,
        agents=[
            _block_session(tmp_path, extra_reply_lines=60, running_last=True),
        ],
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _goto_agents(page, 1)
        detail = await _show_reply(page)
        panel = detail.deck_area.panel(0)
        card = panel._main_document.card("reply")
        assert card is not None and card.has_block_navigation
        await page.press("left_square_bracket")
        await wait_for_state(
            page,
            lambda: panel.main_view.active_block_id("reply") == card.block_ids[-2],
            description="Second-to-last block is active after [",
        )
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "agents_deck_blocks_paged_older_120x40",
            title="ACE agents deck blocks paged after bracket",
        )


async def test_agents_deck_blocks_spread_landing_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(
        monkeypatch,
        agents=[
            _block_session(
                tmp_path,
                session="spread",
                include_gate_monitor=False,
                extra_context_lines=40,
                running_last=True,
            ),
        ],
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _goto_agents(page, 1)
        detail = await _show_reply(page)
        panel = detail.deck_area.panel(0)
        card = panel._main_document.card("reply")
        assert card is not None and card.has_block_navigation
        assert panel.block_mode_for_active_card() is RenderMode.SPREAD
        assert panel.main_view.active_block_id("reply") == card.block_ids[-1]
        ace_png_visual.assert_page_png(
            page,
            "agents_deck_blocks_spread_landing_120x40",
            title="ACE agents deck blocks spread landing",
        )


async def test_agents_deck_blocks_split_rails_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(
        monkeypatch,
        agents=[
            _block_session(tmp_path, session="split", code_shells=9),
        ],
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _goto_agents(page, 1)
        detail = page.app.query_one("#agent-detail-panel", AgentDetail)
        # Collapse the node list so the split panels are wide enough for
        # windowed rails with overflow counts.
        await page.press("ctrl+s")
        await wait_for_state(
            page,
            lambda: detail.is_nodes_collapsed is True,
            description="Node panel is collapsed",
        )
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
        # Step the focused (left) panel back; the right keeps its own cursor.
        await page.press("ctrl+f")
        await wait_for_visual_idle(page)
        left = detail.deck_area.panel(0)
        right = detail.deck_area.panel(1)
        card = left._main_document.card("reply")
        assert card is not None and card.has_block_navigation
        await page.press("left_square_bracket")
        await wait_for_state(
            page,
            lambda: left.main_view.active_block_id("reply") == card.block_ids[-2],
            description="Left panel steps to the older block",
        )
        await wait_for_visual_idle(page)
        assert right.main_view.active_block_id("reply") == card.block_ids[-1]
        ace_png_visual.assert_page_png(
            page,
            "agents_deck_blocks_split_rails_120x40",
            title="ACE agents deck blocks split rails",
        )


async def test_agents_deck_blocks_spread_deck_sticky_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(
        monkeypatch,
        agents=[
            _block_session(
                tmp_path,
                session="tiny",
                code_shells=1,
                include_gate_monitor=False,
                tiny_content=True,
                extra_reply_lines=4,
            ),
        ],
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _goto_agents(page, 1)
        detail = page.app.query_one("#agent-detail-panel", AgentDetail)
        await wait_for_state(
            page,
            lambda: set(detail._main_deck_document.card_ids) == {"context", "reply"},
            description="Main deck has Context and Reply cards",
        )
        panel = detail.deck_area.panel(0)
        await wait_for_state(
            page,
            lambda: panel.is_spread(DeckId.MAIN),
            description="Small session renders a spread deck",
        )
        # Sticky-Reply landing scrolls a scrollable spread deck to Reply.
        await wait_for_state(
            page,
            lambda: panel.main_view.spread_active_card() == "reply",
            description="Spread deck lands on the Reply card",
        )
        await wait_for_visual_idle(page)
        # No rail in a spread deck.
        assert not panel._block_rail_widget().has_class("-shown")
        ace_png_visual.assert_page_png(
            page,
            "agents_deck_blocks_spread_deck_sticky_120x40",
            title="ACE agents deck blocks spread deck sticky",
        )


async def test_agents_deck_blocks_arrival_dot_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = _block_session(tmp_path, session="arrive", extra_reply_lines=40)
    patch_startup_loaders(monkeypatch, agents=[root])
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _goto_agents(page, 1)
        detail = await _show_reply(page)
        panel = detail.deck_area.panel(0)
        card = panel._main_document.card("reply")
        assert card is not None and card.has_block_navigation
        # Read history first: stepping back stops following.
        await page.press("left_square_bracket")
        await wait_for_state(
            page,
            lambda: panel.main_view.active_block_id("reply") == card.block_ids[-2],
            description="Second-to-last block is active after [",
        )
        # A new shell starts while not following: the rail gains an arrival dot.
        late = _block_shell(
            tmp_path,
            "arrive",
            "code",
            "--code-late",
            10,
            extra_reply_lines=40,
            status="RUNNING",
            stop_time=None,
        )
        late.agent_session_container = root
        root.followup_agents = [*root.followup_agents, late]
        # Re-render through the hidden prompt source, the same sink a live
        # streaming update takes: same subject, so the cursor is kept by id
        # and the new shell gains an arrival dot.
        detail._deck_source_panel().update_display(root)
        await wait_for_state(
            page,
            lambda: bool(panel.arrived_block_ids("reply")),
            description="New shell arrives while reading history",
        )
        await wait_for_visual_idle(page)
        assert panel.main_view.active_block_id("reply") == card.block_ids[-2]
        ace_png_visual.assert_page_png(
            page,
            "agents_deck_blocks_arrival_dot_120x40",
            title="ACE agents deck blocks arrival dot",
        )


async def test_agents_deck_blocks_micro_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # A narrow split renders micro-tier rails: the active pill plus bare
    # counts, with the pill label middle-ellipsized as a last resort.
    patch_startup_loaders(
        monkeypatch,
        agents=[
            _block_session(tmp_path, session="micro", code_shells=9),
        ],
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _goto_agents(page, 1)
        detail = page.app.query_one("#agent-detail-panel", AgentDetail)
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
        # Showing the stored document per panel is synchronous; no app-level
        # refresh is needed (its list rebuild steals DOM focus and jitters
        # the narrow split widths the micro tier is balanced on).
        detail.set_deck_preferred_card(0, "reply")
        detail.set_deck_preferred_card(1, "reply")
        await wait_for_state(
            page,
            lambda: (
                detail.deck_area.panel(0).main_view.active_card_id == "reply"
                and detail.deck_area.panel(1).main_view.active_card_id == "reply"
            ),
            description="Both panels show the Reply card",
        )
        left = detail.deck_area.panel(0)
        card = left._main_document.card("reply")
        assert card is not None and card.has_block_navigation
        # Pin focus to the left panel so the split divider renders
        # deterministically.
        await page.press("ctrl+f")
        await wait_for_visual_idle(page)
        # Re-sync the left panel's scrollbar: the block-spread to
        # block-paged switch can leave its position stale, which flips the
        # thumb between captures. An explicit down-and-back scroll forces
        # the widget to converge with the scroller.
        widget, _region = page.app.screen.get_widget_at(90, 20)
        scroller = widget.parent
        scroller.scroll_to(y=scroller.max_scroll_y, animate=False)
        await wait_for_state(
            page,
            lambda: widget.position == scroller.scroll_y,
            description="scrollbar follows the scroller to the bottom",
        )
        scroller.scroll_to(y=0, animate=False)
        await wait_for_state(
            page,
            lambda: widget.position == scroller.scroll_y == 0,
            description="scrollbar follows the scroller back to the top",
        )
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "agents_deck_blocks_micro_120x40",
            title="ACE agents deck blocks micro rail",
        )
