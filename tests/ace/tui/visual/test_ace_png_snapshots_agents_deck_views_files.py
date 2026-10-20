"""sase's TUI PNG visual snapshots for Agents Files-deck view chips."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.widgets import AgentDetail
from sase.ace.tui.widgets.decks.model import DeckId, DeckView, RenderMode
from tests.ace.tui.visual._ace_agents_deck_views_png_snapshot_shared import (
    goto_agents,
    title_plain,
    view_turn,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _files_agent(tmp_path: Path, *, lines_per_file: int = 200) -> Agent:
    """Build a session agent with two tall text files (AUTO pages Files)."""
    root = view_turn(tmp_path, "viewfiles", "plan", "--plan", 10, plan_chain_root=True)
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
    root = view_turn(
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
    root = view_turn(tmp_path, "viewmedia", "plan", "--plan", 20, plan_chain_root=True)
    notes = tmp_path / "view_notes.md"
    notes.write_text("".join(f"note line {i}\n" for i in range(10)), encoding="utf-8")
    shot = tmp_path / "view_shot.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\n")
    root.extra_files = ["view_notes.md", "view_shot.png"]
    return root


async def test_agents_deck_view_files_fixed_spread_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[_files_agent(tmp_path)])
    # A wider terminal keeps the deck column wide enough for the long view
    # badge; at 120 columns the title ladder drops to a shorter rung.
    async with AcePage(query='"visual"', size=(160, 40), patches=patches()) as page:
        await goto_agents(page, 1)
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
        files_title = title_plain(detail)
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
        await goto_agents(page, 1)
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
        await goto_agents(page, 1)
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
        blocked_title = title_plain(detail)
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
