"""ACE PNG snapshots for Archive identity, missing, empty, and help states."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions.agents._archive_controller import (
    note_inbox_applied_for_archive,
)
from sase.ace.tui.actions.agents._archive_view import open_agents_archive_view
from sase.ace.tui.widgets.agents_archive import ArchiveList
from tests.ace.tui._agent_archive_column_helpers import (
    ModelCorpus,
    complete_load,
    light_row,
)
from tests.ace.tui.visual._ace_agents_archive_png_snapshot_shared import (
    NOW,
    inbox_agent,
    list_history,
    open_archive,
    settle_archive_detail,
    wait_for_svg,
    wire,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
    page_svg_text,
    pin_agents_visual_now,
    pin_decks_paged,
    show_reply_card,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture
from tests.ace.tui.widgets._agent_display_helpers import make_agent

pytestmark = pytest.mark.visual

_ARCHIVE_REPLY_SENTINEL = "the archived reply reads back verbatim"
_ARCHIVE_PROMPT_SENTINEL = "the archived prompt reads back verbatim"


def _write_reply_bundle(tmp_path: Path) -> str:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "raw_prompt.md").write_text(_ARCHIVE_PROMPT_SENTINEL, encoding="utf-8")
    response = artifacts / "response.md"
    response.write_text(_ARCHIVE_REPLY_SENTINEL, encoding="utf-8")
    agent = make_agent(
        status="DONE",
        cl_name="archived",
        agent_name="archived-run",
        start_time=datetime(2026, 10, 10, 15, 0, 0),
    )
    agent.artifacts_dir = str(artifacts)
    agent.response_path = str(response)
    bundle = tmp_path / "bundles" / "r1.json"
    bundle.parent.mkdir(parents=True, exist_ok=True)
    bundle.write_text(json.dumps(agent.to_bundle_dict()), encoding="utf-8")
    return str(bundle)


async def test_archived_identity_reply_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The archived identity header with retained Reply content."""
    patch_startup_loaders(monkeypatch, agents=[inbox_agent()])
    pin_agents_visual_now(monkeypatch, NOW)
    pin_decks_paged(monkeypatch)
    bundle_path = _write_reply_bundle(tmp_path)
    rows = [
        light_row(
            "r1",
            day="2026-10-10",
            hour=15,
            name="archived-run",
            status="DONE",
            bundle_path=bundle_path,
        ),
        light_row("d02", day="2026-10-10", hour=12, name="today.other"),
    ]
    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        await open_archive(page, rows)

        await wait_for_svg(page, "ARCHIVED")
        await wait_for_svg(page, _ARCHIVE_PROMPT_SENTINEL)
        assert_page_svg_contains(page, "read-only")
        # Cycle the Main deck to its Reply card: the golden must show
        # retained reply content, not just the Context card.
        await show_reply_card(page)
        await wait_for_svg(page, _ARCHIVE_REPLY_SENTINEL)
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "agents_archive_identity_reply_120x40",
            title="ACE Agents Archive identity and reply",
        )


async def test_archive_missing_content_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreadable bundle paints titled missing-content cards, honestly."""
    patch_startup_loaders(monkeypatch, agents=[inbox_agent()])
    pin_agents_visual_now(monkeypatch, NOW)
    pin_decks_paged(monkeypatch)
    rows = [
        light_row(
            "m01",
            day="2026-10-10",
            hour=15,
            name="missing.bundle",
            bundle_path="/nonexistent/archive-missing-bundle.json",
        ),
    ]
    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        await open_archive(page, rows)

        await wait_for_svg(page, "Record only")
        # The selected unreadable row keeps read/mark chips while every
        # live Inbox action stays out of the conditional footer.
        assert_page_svg_contains(page, "read")
        assert_page_svg_contains(page, "mark")
        assert "go to PR" not in page_svg_text(page)
        ace_png_visual.assert_page_png(
            page,
            "agents_archive_missing_content_120x40",
            title="ACE Agents Archive missing content",
        )


async def test_archive_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A complete empty result says so instead of spinning."""
    patch_startup_loaders(monkeypatch, agents=[inbox_agent()])
    pin_agents_visual_now(monkeypatch, NOW)
    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        wire(page.app, ModelCorpus([]))
        note_inbox_applied_for_archive(page.app, load_state=complete_load())
        open_agents_archive_view(page.app)
        await page.wait_for(
            lambda _state: (
                "message:empty"
                in (
                    page.app.query_one("#archive-list", ArchiveList).item_keys
                    if page.app.query("#archive-list")
                    else ()
                )
            ),
            timeout=15.0,
        )
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "No archived runs match this query.")
        # No selection, no marks: the conditional footer is empty, and
        # no live Inbox action may leak into it.
        assert "go to PR" not in page_svg_text(page)
        ace_png_visual.assert_page_png(
            page,
            "agents_archive_empty_120x40",
            title="ACE Agents Archive empty",
        )


async def test_archive_missing_index_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing index names the rebuild command instead of building one."""
    patch_startup_loaders(monkeypatch, agents=[inbox_agent()])
    pin_agents_visual_now(monkeypatch, NOW)
    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        wire(page.app, ModelCorpus([], status="missing"))
        note_inbox_applied_for_archive(page.app, load_state=complete_load())
        open_agents_archive_view(page.app)
        await page.wait_for(
            lambda _state: (
                "message:status"
                in (
                    page.app.query_one("#archive-list", ArchiveList).item_keys
                    if page.app.query("#archive-list")
                    else ()
                )
            ),
            timeout=15.0,
        )
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "rebuild-index")
        ace_png_visual.assert_page_png(
            page,
            "agents_archive_missing_index_120x40",
            title="ACE Agents Archive missing index",
        )


async def test_archive_rebuilding_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rebuilding index reports row-count progress, never a fake empty."""
    patch_startup_loaders(monkeypatch, agents=[inbox_agent()])
    pin_agents_visual_now(monkeypatch, NOW)
    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        await open_archive(page, list_history(), rebuilding=True)

        assert_page_svg_contains(page, "rebuilding")
        ace_png_visual.assert_page_png(
            page,
            "agents_archive_rebuilding_120x40",
            title="ACE Agents Archive rebuilding",
        )


async def test_archive_help_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Agents help modal documents the read-only Archive surface."""
    patch_startup_loaders(monkeypatch, agents=[inbox_agent()])
    pin_agents_visual_now(monkeypatch, NOW)
    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        await open_archive(page, list_history())

        await page.press("?")
        await page.expect_modal("HelpModal")
        await wait_for_visual_idle(page)
        # The Keymaps view is taller than the modal viewport. Stop with the
        # Archive section title row visible so the golden shows its context.
        for _ in range(60):
            if "Archive (read-only)" in page_svg_text(page):
                break
            await page.press("ctrl+d")
            await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "Archive (read-only)")
        await settle_archive_detail(page)
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "Archive (read-only)")
        ace_png_visual.assert_page_png(
            page,
            "agents_archive_help_120x40",
            title="ACE Agents Archive help",
        )
