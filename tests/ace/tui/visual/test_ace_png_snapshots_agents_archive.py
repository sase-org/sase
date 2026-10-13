"""sase's TUI PNG visual snapshots for the read-only Agents Archive view.

Covers the archive-proof fixtures: day grouping with open and folded
banners, containers, interrupted rows with italic start-only time, the
archived identity header plus Reply, missing-content cards, the
empty/missing/rebuilding states, the parked tab marker, and the Archive
help box. Row dates are fixed around a pinned visual now so banners and
time chips are deterministic.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions.agents._archive_controller import (
    note_inbox_applied_for_archive,
)
from sase.ace.tui.actions.agents._archive_view import open_agents_archive_view
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_archive_controller import ArchiveRevalidationTokens
from sase.ace.tui.widgets.agents_archive import ArchiveList
from sase.feature_flags import override_flags
from tests.ace.tui._agent_archive_column_helpers import (
    ModelCorpus,
    complete_load,
    light_row,
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

NOW = datetime(2026, 10, 10, 20, 0, tzinfo=UTC)

_ARCHIVE_REPLY_SENTINEL = "the archived reply reads back verbatim"
_ARCHIVE_PROMPT_SENTINEL = "the archived prompt reads back verbatim"


def _inbox_agent() -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="live-agent",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="crs",
        raw_suffix="20260527120000",
        agent_name="live.agent",
    )


def _wire(app: Any, corpus: ModelCorpus, *, rebuilding: bool = False) -> None:
    app._archive_get_corpus = lambda **kwargs: SimpleNamespace(
        corpus=corpus, profile=SimpleNamespace(digest="profile-1")
    )
    app._archive_probe_tokens = lambda: ArchiveRevalidationTokens(
        index_exists=True,
        index_stat=(1, 2),
        link_signature=(("proj", 1, 2),),
        profile_digest="profile-1",
        rebuilding=rebuilding,
        indexed_rows=41 if rebuilding else 0,
    )
    app._archive_load_facets = lambda: {}
    app._archive_profile = SimpleNamespace(digest="profile-1")
    app._archive_now = lambda: NOW


def _list_history() -> list[dict[str, Any]]:
    rows = [
        light_row("d01", day="2026-10-10", hour=18, name="today.done"),
        light_row(
            "d02",
            day="2026-10-10",
            hour=17,
            name="today.failed",
            outcome="failed",
            status="FAILED",
        ),
        light_row(
            "d03",
            day="2026-10-10",
            hour=16,
            name="today.running",
            status="RUNNING",
            stop_time=None,
            time_basis="started",
            outcome="interrupted",
        ),
    ]
    rows += [
        light_row(
            "c1",
            day="2026-10-09",
            hour=15,
            name="clan.alpha",
            container_key="archive:u.m@clan1",
        ),
        light_row(
            "c2",
            day="2026-10-09",
            hour=14,
            name="clan.beta",
            container_key="archive:u.m@clan1",
        ),
    ]
    rows += [light_row("o01", day="2026-09-20", hour=12, name="old.solo")]
    return rows


async def _wait_for_rows(page: AcePage) -> None:
    await page.wait_for(
        lambda _state: any(
            "@" in key
            for key in (
                page.app.query_one("#archive-list", ArchiveList).item_keys
                if page.app.query("#archive-list")
                else ()
            )
        ),
        timeout=15.0,
    )


async def _wait_for_svg(page: AcePage, needle: str, timeout: float = 15.0) -> None:
    """Poll decoded screen text until ``needle`` paints (spaces are plain)."""
    import asyncio

    from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import page_svg_text

    start = asyncio.get_running_loop().time()
    while asyncio.get_running_loop().time() - start < timeout:
        if needle in page_svg_text(page):
            return
        await asyncio.sleep(0.1)  # sase-test-wait: poll SVG text paint
    raise AssertionError(f"timed out waiting for {needle!r} in the Archive view")


async def _open_archive(
    page: AcePage, rows: list[dict[str, Any]], *, rebuilding: bool = False
) -> None:
    _wire(page.app, ModelCorpus(rows), rebuilding=rebuilding)
    note_inbox_applied_for_archive(page.app, load_state=complete_load())
    open_agents_archive_view(page.app)
    await _wait_for_rows(page)
    await _settle_archive_detail(page)
    await wait_for_visual_idle(page)


async def _settle_archive_detail(page: AcePage) -> None:
    """Outlast the 150 ms detail debounce plus the hydration worker.

    Visual-idle detection does not track the Archive reader's debounced
    off-thread hydration, so a bare ``wait_for_visual_idle`` can converge
    while a placeholder-to-content repaint is still queued and the capture
    then sees a changed frame. One beat covers debounce and disk read.
    """
    import asyncio

    await asyncio.sleep(1.0)  # sase-test-wait: detail debounce settle


async def test_archive_list_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Day banners, a container, an interrupted row, pulse, and tab marker."""
    patch_startup_loaders(monkeypatch, agents=[_inbox_agent()])
    pin_agents_visual_now(monkeypatch, NOW)
    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        await _open_archive(page, _list_history())

        assert_page_svg_contains(page, "Agents ◷")
        assert_page_svg_contains(page, "Today")
        assert_page_svg_contains(page, "Yesterday")
        assert_page_svg_contains(page, "⌂ Inbox")
        assert_page_svg_contains(page, "in:archive")
        assert_page_svg_contains(page, "today.done")
        assert_page_svg_contains(page, "WAS")

        # Expand the Yesterday container so member rows join the golden.
        for _ in range(12):
            selected = page.app._agents_archive_view.archive.selected_key
            if selected is not None and selected.startswith("container:"):
                break
            await page.press("j")
        else:
            raise AssertionError("never reached the container summary row")
        await page.press("l")
        await _wait_for_svg(page, "clan.alpha")
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "clan.alpha")
        assert_page_svg_contains(page, "clan.beta")
        assert "go to PR" not in page_svg_text(page)
        ace_png_visual.assert_page_png(
            page,
            "agents_archive_list_120x40",
            title="ACE Agents Archive list",
        )


async def test_archive_folded_banners_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Folded Yesterday banner keeps Today open; the parked marker survives."""
    patch_startup_loaders(monkeypatch, agents=[_inbox_agent()])
    pin_agents_visual_now(monkeypatch, NOW)
    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        await _open_archive(page, _list_history())

        # Walk down to the Yesterday banner and fold it.
        archive_list = page.app.query_one("#archive-list", ArchiveList)
        for _ in range(10):
            keys = archive_list.item_keys
            target = keys.index("banner:day:2026-10-09")
            if archive_list.highlighted == target:
                break
            await page.press("j")
        assert archive_list.highlighted == target
        await page.press("h")
        await page.pause()
        # Step back onto a run row: a cursor parked on a banner keeps
        # the last placeholder painted with the reader idle (recorded
        # as a follow-up), which must not leak into the golden.
        await page.press("k")
        await _settle_archive_detail(page)
        await wait_for_visual_idle(page)
        text = page_svg_text(page)
        assert "▸" in text and "Yesterday" in text
        assert "clan.alpha" not in text and "clan.beta" not in text
        assert_page_svg_contains(page, "Today")
        assert_page_svg_contains(page, "today.done")
        ace_png_visual.assert_page_png(
            page,
            "agents_archive_folded_banners_120x40",
            title="ACE Agents Archive folded banners",
        )


async def test_archive_parked_marker_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tab marker stays visible while another main tab is active."""
    patch_startup_loaders(monkeypatch, agents=[_inbox_agent()])
    pin_agents_visual_now(monkeypatch, NOW)
    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        await _open_archive(page, _list_history())

        await page.press("shift+tab")
        await page.expect_state("tab", "services")
        await _settle_archive_detail(page)
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "Agents ◷")
        ace_png_visual.assert_page_png(
            page,
            "agents_archive_parked_marker_120x40",
            title="ACE Agents Archive parked marker",
        )


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
    patch_startup_loaders(monkeypatch, agents=[_inbox_agent()])
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
        await _open_archive(page, rows)

        await _wait_for_svg(page, "ARCHIVED")
        await _wait_for_svg(page, _ARCHIVE_PROMPT_SENTINEL)
        assert_page_svg_contains(page, "read-only")
        # Cycle the Main deck to its Reply card: the golden must show
        # retained reply content, not just the Context card.
        await show_reply_card(page)
        await _wait_for_svg(page, _ARCHIVE_REPLY_SENTINEL)
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
    patch_startup_loaders(monkeypatch, agents=[_inbox_agent()])
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
        await _open_archive(page, rows)

        await _wait_for_svg(page, "Record only")
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
    patch_startup_loaders(monkeypatch, agents=[_inbox_agent()])
    pin_agents_visual_now(monkeypatch, NOW)
    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        _wire(page.app, ModelCorpus([]))
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
    patch_startup_loaders(monkeypatch, agents=[_inbox_agent()])
    pin_agents_visual_now(monkeypatch, NOW)
    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        _wire(page.app, ModelCorpus([], status="missing"))
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
    patch_startup_loaders(monkeypatch, agents=[_inbox_agent()])
    pin_agents_visual_now(monkeypatch, NOW)
    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        await _open_archive(page, _list_history(), rebuilding=True)

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
    patch_startup_loaders(monkeypatch, agents=[_inbox_agent()])
    pin_agents_visual_now(monkeypatch, NOW)
    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        await _open_archive(page, _list_history())

        await page.press("?")
        await page.expect_modal("HelpModal")
        await wait_for_visual_idle(page)
        # The Keymaps view is taller than the modal viewport. Check the
        # Archive section heading and its final note as they scroll by.
        for _ in range(60):
            if "Archive (read-only)" in page_svg_text(page):
                break
            await page.press("ctrl+d")
            await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "Archive (read-only)")
        for _ in range(60):
            if "Live actions stay in Inbox" in page_svg_text(page):
                break
            await page.press("ctrl+d")
            await wait_for_visual_idle(page)
        await _settle_archive_detail(page)
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "Live actions stay in Inbox")
        ace_png_visual.assert_page_png(
            page,
            "agents_archive_help_120x40",
            title="ACE Agents Archive help",
        )


async def test_archive_marked_row_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A marked Archive run draws the Inbox mark style."""
    from sase.ace.tui.actions.agents._archive_actions import archive_marked_run_keys

    patch_startup_loaders(monkeypatch, agents=[_inbox_agent()])
    pin_agents_visual_now(monkeypatch, NOW)
    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        await _open_archive(page, _list_history())

        await page.press("m")
        assert len(archive_marked_run_keys(page.app)) == 1
        await _settle_archive_detail(page)
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "[✓]")
        assert_page_svg_contains(page, "unmark (1)")
        ace_png_visual.assert_page_png(
            page,
            "agents_archive_marked_120x40",
            title="ACE Agents Archive marked row",
        )


async def test_archive_restored_overlay_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A restored Archive row renders the restore overlay chip."""
    from sase.ace.tui.actions.agents._archive_view import mark_archive_row_restored

    patch_startup_loaders(monkeypatch, agents=[_inbox_agent()])
    pin_agents_visual_now(monkeypatch, NOW)
    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        await _open_archive(page, _list_history())

        selected = page.app._agents_archive_view.archive.selected_key
        assert selected is not None and "@" in selected
        mark_archive_row_restored(page.app, selected)
        await _settle_archive_detail(page)
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "⌂ restored")
        ace_png_visual.assert_page_png(
            page,
            "agents_archive_restored_120x40",
            title="ACE Agents Archive restored overlay",
        )


async def test_archive_restored_row_with_toast_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real Archive restore paints the dimmed row with its single toast."""
    from textual.widgets._toast import Toast

    from sase.ace.tui.actions.agents._archive_restore import run_archive_restore
    from tests.ace.tui.visual._ace_png_snapshot_helpers import stabilize_toast_frame

    patch_startup_loaders(monkeypatch, agents=[_inbox_agent()])
    pin_agents_visual_now(monkeypatch, NOW)
    async with AcePage(
        initial_tab="agents", size=(120, 40), notifications=True
    ) as page:
        await wait_for_startup(page)
        await _open_archive(page, _list_history())

        selected = page.app._agents_archive_view.archive.selected_key
        assert selected is not None and "@" in selected
        agent = SimpleNamespace(
            identity=("agent", "today.done", None),
            agent_name="today.done",
            display_name="today.done",
        )
        monkeypatch.setattr(
            "sase.ace.tui.actions.agents._archive_reader._load_archive_bundle",
            lambda _owner, _row: {"unreadable": False, "agent": agent},
        )
        monkeypatch.setattr(
            page.app,
            "_do_revive_agents",
            lambda agents: SimpleNamespace(failed=[]),
        )
        summary = run_archive_restore(page.app)
        assert [name for _key, name in summary.restored] == ["today.done"]
        await page.wait_for(
            lambda _state: bool(list(page.app.screen.query(Toast))), timeout=15.0
        )
        await _wait_for_svg(page, "is back in the inbox")
        await _settle_archive_detail(page)
        await wait_for_visual_idle(page)
        await stabilize_toast_frame(page)
        assert_page_svg_contains(page, "⌂ restored")
        assert_page_svg_contains(page, "is back in the inbox")
        ace_png_visual.assert_page_png(
            page,
            "agents_archive_restored_toast_120x40",
            title="ACE Agents Archive restored row with toast",
        )


def _archive_chooser_choices(*, marked: int = 0) -> tuple[Any, ...]:
    from sase.ace.tui.actions.agents._archive_restore_types import (
        CHOICE_COPY_MORE,
        CHOICE_COPY_REF,
        CHOICE_FORK,
        CHOICE_OPEN_CHAT,
        CHOICE_RESTORE,
        CHOICE_RESTORE_SHOW,
    )
    from sase.ace.tui.modals.agent_action_chooser_modal import AgentActionChoice

    restore_label = f"Restore {marked} marked" if marked else "Restore to inbox"
    return (
        AgentActionChoice(
            result=CHOICE_RESTORE,
            section="archive",
            label=restore_label,
            detail="shows it again · starts no new run",
            glyph="⌂",
            glyph_style="",
            badge=None,
            badge_style=None,
            age=None,
            hotkey="r",
        ),
        AgentActionChoice(
            result=CHOICE_RESTORE_SHOW,
            section="archive",
            label="Restore and show in inbox",
            detail="reveals the agent in the Inbox",
            glyph="⌂",
            glyph_style="",
            badge=None,
            badge_style=None,
            age=None,
            hotkey="s",
        ),
        AgentActionChoice(
            result=CHOICE_FORK,
            section="archive",
            label="Fork into a new agent",
            detail="starts a new run from this one",
            glyph="⑂",
            glyph_style="",
            badge=None,
            badge_style=None,
            age=None,
            hotkey="F",
        ),
        AgentActionChoice(
            result=CHOICE_OPEN_CHAT,
            section="read",
            label="Open chat in $EDITOR",
            detail="read-only",
            glyph="▤",
            glyph_style="",
            badge=None,
            badge_style=None,
            age=None,
            hotkey="e",
        ),
        AgentActionChoice(
            result=CHOICE_COPY_REF,
            section="read",
            label="Copy @agent reference",
            detail=None,
            glyph="@",
            glyph_style="",
            badge=None,
            badge_style=None,
            age=None,
            hotkey="y",
        ),
        AgentActionChoice(
            result=CHOICE_COPY_MORE,
            section="read",
            label="More copy targets",
            detail=None,
            glyph="%",
            glyph_style="",
            badge=None,
            badge_style=None,
            age=None,
            hotkey="%",
        ),
    )


async def test_archive_chooser_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Archive chooser paints ARCHIVE then READ without marks."""
    from sase.ace.tui.modals.agent_action_chooser_modal import AgentActionChooserModal

    patch_startup_loaders(monkeypatch, agents=[_inbox_agent()])
    pin_agents_visual_now(monkeypatch, NOW)
    async with AcePage(initial_tab="agents", size=(120, 40)) as page:
        await wait_for_startup(page)
        await _open_archive(page, _list_history())
        page.app.push_screen(
            AgentActionChooserModal(
                _archive_chooser_choices(),
                title="Act on bob-cli-5p.4 · archived",
            )
        )
        await page.expect_modal("AgentActionChooserModal")
        await _wait_for_svg(page, "Act on bob-cli-5p.4")
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "ARCHIVE")
        assert_page_svg_contains(page, "READ")
        assert_page_svg_contains(page, "Restore to inbox")
        ace_png_visual.assert_page_png(
            page,
            "agents_archive_chooser_120x40",
            title="ACE Agents Archive chooser",
        )


async def test_archive_chooser_marked_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Archive chooser paints Restore N marked when marks exist."""
    from sase.ace.tui.modals.agent_action_chooser_modal import AgentActionChooserModal

    patch_startup_loaders(monkeypatch, agents=[_inbox_agent()])
    pin_agents_visual_now(monkeypatch, NOW)
    async with AcePage(initial_tab="agents", size=(120, 40)) as page:
        await wait_for_startup(page)
        await _open_archive(page, _list_history())
        page.app.push_screen(
            AgentActionChooserModal(
                _archive_chooser_choices(marked=2),
                title="Act on bob-cli-5p.4 · archived",
            )
        )
        await page.expect_modal("AgentActionChooserModal")
        await _wait_for_svg(page, "Restore 2 marked")
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "ARCHIVE")
        assert_page_svg_contains(page, "READ")
        assert_page_svg_contains(page, "Restore 2 marked")
        ace_png_visual.assert_page_png(
            page,
            "agents_archive_chooser_marked_120x40",
            title="ACE Agents Archive chooser with marks",
        )
