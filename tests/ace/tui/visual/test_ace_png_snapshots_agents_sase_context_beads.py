"""sase's TUI PNG visual snapshots for Agents-tab bead-touch context lanes."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui._bead_touches_shared import (
    BeadTouchDisplayEvent as _BeadTouchDisplayEvent,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.core.bead_touch_index_facade import (
    BeadNotePreview,
    BeadTouch,
    BeadTouchClose,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
    main_deck_scroll,
    page_svg_text,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_agents_bead_note_preview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The Context card keeps an attributed note preview within its row budget."""
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-bead-note-preview",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=datetime(2026, 9, 25, 14, 0, 0),
        raw_suffix="20260925140000",
        agent_name="visual.bead-note-preview",
        workspace_dir=str(tmp_path),
        llm_provider="codex",
        model="gpt-5",
    )
    preview = BeadNotePreview(
        id="sase-visual.7:note-2",
        author="visual.bead-note-preview",
        timestamp="2026-09-25T14:03:00Z",
        text=" ".join(
            (
                "Render the compact current note preview without changing the existing "
                "bead hint target or making navigation read live bead streams."
            ).split()
            * 4
        ),
        edited_at="2026-09-25T14:04:00Z",
        truncated=True,
    )
    touch = BeadTouch(
        actor="visual.bead-note-preview",
        bead_id="sase-visual.7",
        title="Render compact Context-card note previews",
        verbs={"noted": 2},
        first_at="2026-09-25T14:02:00Z",
        last_at="2026-09-25T14:05:00Z",
        current_note_count=2,
        note_preview=preview,
    )
    monkeypatch.setattr(
        "sase.ace.tui.bead_touches.load_bead_touches_for_agent_context",
        lambda _agent: (_BeadTouchDisplayEvent(touch=touch),),
    )
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_svg_contains(page, "sase-visual.7")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "SASE CONTEXT")
        assert_page_svg_contains(page, "Beads:")
        assert_page_svg_contains(page, "sase-visual.7")
        assert_page_svg_contains(page, "visual.bead-note-preview")
        assert_page_svg_contains(page, "edited")
        assert_page_svg_contains(page, "full")
        assert_page_svg_contains(page, "detail")
        assert_page_svg_contains(page, "+1 earlier")
        ace_png_visual.assert_page_png(
            page,
            "agents_bead_note_preview_120x40",
            title="ACE agents Context-card bead note preview",
        )


def _closed_bead_touches() -> tuple[_BeadTouchDisplayEvent, ...]:
    """Return touches covering standing-done, canceled, plain, stale closes.

    Bead ids stay short so the CLOSED pill fits the 90x32 split-card
    viewport as well as the wide card.
    """
    actor = "visual.bead-closed"
    return (
        _BeadTouchDisplayEvent(
            touch=BeadTouch(
                actor=actor,
                bead_id="sase-19f.2",
                title="Render closed beads distinctly",
                verbs={"closed": 1, "noted": 1},
                first_at="2026-09-25T14:02:00Z",
                last_at="2026-09-25T14:05:00Z",
                close=BeadTouchClose(
                    closed_at="2026-09-25T14:05:00Z",
                    resolution="done",
                    reason="Phase checks green",
                    standing=True,
                ),
            )
        ),
        _BeadTouchDisplayEvent(
            touch=BeadTouch(
                actor=actor,
                bead_id="sase-1a2",
                title="Canceled duplicate",
                verbs={"closed": 1, "created": 1},
                first_at="2026-09-25T14:01:00Z",
                last_at="2026-09-25T14:04:00Z",
                close=BeadTouchClose(
                    closed_at="2026-09-25T14:04:00Z",
                    resolution="canceled",
                    reason="duplicate of sase-19z",
                    standing=True,
                ),
            )
        ),
        _BeadTouchDisplayEvent(
            touch=BeadTouch(
                actor=actor,
                bead_id="sase-19f",
                title="Closed beads in Context card",
                verbs={"noted": 1},
                first_at="2026-09-25T14:00:00Z",
                last_at="2026-09-25T14:03:00Z",
            )
        ),
        _BeadTouchDisplayEvent(
            touch=BeadTouch(
                actor=actor,
                bead_id="sase-17m.4",
                title="Legacy attribution",
                verbs={"noted": 1, "closed": 1},
                first_at="2026-09-25T13:00:00Z",
                last_at="2026-09-25T14:02:00Z",
                close=BeadTouchClose(
                    closed_at="2026-09-25T14:02:00Z",
                    resolution="done",
                    reason="",
                    standing=False,
                ),
            )
        ),
    )


def _closed_bead_agent(tmp_path: Path) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-bead-closed",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=datetime(2026, 9, 25, 14, 0, 0),
        raw_suffix="20260925140000",
        agent_name="visual.bead-closed",
        workspace_dir=str(tmp_path),
        llm_provider="codex",
        model="gpt-5",
    )


async def test_agents_bead_closed_by_agent_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The Context card paints standing closes with a CLOSED pill."""
    agent = _closed_bead_agent(tmp_path)
    touches = _closed_bead_touches()
    monkeypatch.setattr(
        "sase.ace.tui.bead_touches.load_bead_touches_for_agent_context",
        lambda _agent: touches,
    )
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_svg_contains(page, "sase-19f.2")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "SASE CONTEXT")
        assert_page_svg_contains(page, "Beads:")
        assert_page_svg_contains(page, "sase-19f.2")
        assert_page_svg_contains(page, "CLOSED")
        assert_page_svg_contains(page, "canceled")
        assert_page_svg_contains(page, "reopened since")
        assert_page_svg_contains(page, "closed")
        ace_png_visual.assert_page_png(
            page,
            "agents_bead_closed_by_agent_120x40",
            title="ACE agents Context-card closed beads",
        )


async def test_agents_bead_closed_by_agent_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The CLOSED pill stays contiguous in a narrow split card."""
    agent = _closed_bead_agent(tmp_path)
    touches = _closed_bead_touches()
    monkeypatch.setattr(
        "sase.ace.tui.bead_touches.load_bead_touches_for_agent_context",
        lambda _agent: touches,
    )
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(query='"visual"', patches=patches(), size=(90, 32)) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_svg_contains(page, "Beads:")
        await wait_for_svg_contains(page, "CLOSED")
        await wait_for_visual_idle(page)

        # The narrow card wraps the "SASE CONTEXT" heading itself, so assert
        # the lane and pill tokens that prove the closed rendering instead.
        assert_page_svg_contains(page, "Beads:")
        assert_page_svg_contains(page, "CLOSED")
        ace_png_visual.assert_page_png(
            page,
            "agents_bead_closed_by_agent_90x32",
            title="ACE agents Context-card closed beads narrow",
        )


def _created_bead_touches() -> tuple[_BeadTouchDisplayEvent, ...]:
    """Return touches covering created, created-plus-closed, and legacy rows.

    Bead ids stay short so the CREATED pill fits the 90x32 split-card
    viewport as well as the wide card.
    """
    actor = "visual.bead-created"
    return (
        _BeadTouchDisplayEvent(
            touch=BeadTouch(
                actor=actor,
                bead_id="sase-1c",
                title="File creation reasons",
                verbs={"created": 1, "noted": 1},
                first_at="2026-09-26T14:02:00Z",
                last_at="2026-09-26T14:05:00Z",
                creation_reason="Second agent saw the drop",
            )
        ),
        _BeadTouchDisplayEvent(
            touch=BeadTouch(
                actor=actor,
                bead_id="sase-1d",
                title="Created then closed",
                verbs={"closed": 1, "created": 1},
                first_at="2026-09-26T14:01:00Z",
                last_at="2026-09-26T14:04:00Z",
                creation_reason="Filed from triage",
                close=BeadTouchClose(
                    closed_at="2026-09-26T14:04:00Z",
                    resolution="done",
                    reason="Landed",
                    standing=True,
                ),
            )
        ),
    )


def _created_bead_agent(
    tmp_path: Path, *, phase_bead_id: str | None = "sase-1e"
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-bead-created",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=datetime(2026, 9, 26, 14, 0, 0),
        raw_suffix="20260926140000",
        agent_name="visual.bead-created",
        workspace_dir=str(tmp_path),
        llm_provider="codex",
        model="gpt-5",
        phase_bead_id=phase_bead_id,
    )


async def test_agents_bead_created_by_agent_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The Context card distinguishes created beads with a CREATED pill."""
    agent = _created_bead_agent(tmp_path)
    touches = _created_bead_touches()
    monkeypatch.setattr(
        "sase.ace.tui.bead_touches.load_bead_touches_for_agent_context",
        lambda _agent: touches,
    )
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_svg_contains(page, "sase-1c")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "SASE CONTEXT")
        assert_page_svg_contains(page, "Beads:")
        assert_page_svg_contains(page, "sase-1c")
        assert_page_svg_contains(page, "CREATED")
        assert_page_svg_contains(page, "why:")
        assert_page_svg_contains(page, "assigned")
        assert_page_svg_contains(page, "CLOSED")
        assert_page_svg_contains(page, "created")
        ace_png_visual.assert_page_png(
            page,
            "agents_bead_created_by_agent_120x40",
            title="ACE agents Context-card created beads",
        )


async def test_agents_bead_created_by_agent_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The CREATED pill stays contiguous in a narrow split card."""
    # No phase bead: with one attached, the taller deck squeezes the split
    # card to ~6 cells, shredding "Beads:"/"CREATED" mid-token so the SVG
    # sentinels below can never match. The wide golden covers the phase-bead
    # card, including the assigned row this variant omits.
    agent = _created_bead_agent(tmp_path, phase_bead_id=None)
    touches = _created_bead_touches()
    monkeypatch.setattr(
        "sase.ace.tui.bead_touches.load_bead_touches_for_agent_context",
        lambda _agent: touches,
    )
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(query='"visual"', patches=patches(), size=(90, 32)) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_svg_contains(page, "Beads:")
        # The first bead row starts at the bottom edge, so nudge the deck
        # until its CREATED pill scrolls into view.
        scroll = main_deck_scroll(page)
        for _ in range(10):
            if "CREATED" in page_svg_text(page):
                break
            scroll.scroll_to(
                y=min(int(scroll.max_scroll_y), int(scroll.scroll_y) + 2),
                animate=False,
            )
            await wait_for_visual_idle(page)
        await wait_for_svg_contains(page, "CREATED")
        await wait_for_visual_idle(page)

        # The narrow card wraps the "SASE CONTEXT" heading itself, so assert
        # the lane and pill tokens that prove the created rendering instead.
        assert_page_svg_contains(page, "Beads:")
        assert_page_svg_contains(page, "CREATED")
        ace_png_visual.assert_page_png(
            page,
            "agents_bead_created_by_agent_90x32",
            title="ACE agents Context-card created beads narrow",
        )
