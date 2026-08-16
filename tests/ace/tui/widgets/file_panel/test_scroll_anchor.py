"""Integration tests for the file panel's scroll-anchor controller.

Drives a real ``AgentFilePanel`` inside a Textual ``run_test`` harness so the
assertions exercise the actual ``VerticalScroll#agent-file-scroll`` container
and ``Widget.render_line`` rendered-line cache, not a mock. These reproduce
the four root causes from the scroll-anchor plan and pin the fix.
"""

from __future__ import annotations

from typing import Any

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll

from sase.core.time import local_now
from sase.ace.tui.widgets.file_panel import AgentFilePanel, _LIVE_DIFF_SENTINEL
from sase.ace.tui.widgets.file_panel._display import StaticReadResult
from sase.ace.tui.widgets.file_panel._scroll_anchor import _normalize_row


class _FilePanelTestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { height: 100%; }
    #agent-file-scroll { height: 100%; overflow-y: auto; }
    """

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="agent-file-scroll"):
            yield AgentFilePanel(id="agent-file-panel")


def _seed_slot(
    panel: AgentFilePanel,
    *,
    agent_identity: object,
    file_list: list[str],
    index: int = 0,
) -> None:
    """Establish the panel's current page slot without a full Agent/cache dance."""
    panel._anchor_agent_identity = agent_identity  # type: ignore[attr-defined]
    panel._file_list = file_list
    panel._current_file_index = index
    panel._note_slot_change(panel._current_anchor_key())  # type: ignore[attr-defined]


async def _settle(pilot: Any) -> None:
    """Pump the message loop through a render and its call_after_refresh restore."""
    await pilot.pause()
    await pilot.pause()


async def _settle_static_worker(pilot: Any, panel: AgentFilePanel) -> None:
    """Await the in-flight static-read worker, then settle its render+restore."""
    worker = panel._static_worker
    if worker is not None:
        await worker.wait()
    await _settle(pilot)


def _numbered_lines(n: int, *, prefix: str = "line") -> str:
    return "\n".join(f"+{prefix} {i:04d} content here" for i in range(n)) + "\n"


async def test_async_static_render_preserves_position_after_worker_lands(
    tmp_path: Any,
) -> None:
    """The restore must apply after the async render lands, not before it.

    Regression test for root cause A: the old save/restore pair bracketed
    ``display_static_file`` (which only *schedules* a worker), so the
    restore fired a frame before the actual content replaced the old body.
    """
    content = "\n".join(f"line {i:04d}" for i in range(300)) + "\n"
    path = tmp_path / "notes.txt"
    path.write_text(content, encoding="utf-8")

    async with _FilePanelTestApp().run_test(size=(100, 30)) as pilot:
        panel = pilot.app.query_one(AgentFilePanel)
        scroll = pilot.app.query_one("#agent-file-scroll", VerticalScroll)
        _seed_slot(panel, agent_identity="agent-1", file_list=[str(path)])

        panel.display_static_file(str(path))
        await _settle_static_worker(pilot, panel)

        scroll.scroll_to(y=150, animate=False, immediate=True)
        await pilot.pause()
        assert int(scroll.scroll_y) == 150

        # Re-render the same (unchanged) static file asynchronously again —
        # e.g. a periodic zoom-modal refresh re-reading the same page.
        panel.display_static_file(str(path))
        await _settle_static_worker(pilot, panel)

        assert int(scroll.scroll_y) == 150


async def test_transient_shrink_then_regrow_recovers_live_diff() -> None:
    """A short placeholder diff must not permanently destroy the anchor."""
    diff_full = _numbered_lines(400)
    diff_short = "+only one line\n"

    async with _FilePanelTestApp().run_test(size=(100, 30)) as pilot:
        panel = pilot.app.query_one(AgentFilePanel)
        scroll = pilot.app.query_one("#agent-file-scroll", VerticalScroll)
        _seed_slot(panel, agent_identity="agent-1", file_list=[_LIVE_DIFF_SENTINEL])

        panel._display_file_with_timestamp(diff_full, local_now())
        await _settle(pilot)
        scroll.scroll_to(y=300, animate=False, immediate=True)
        await pilot.pause()
        assert int(scroll.scroll_y) == 300

        panel._display_file_with_timestamp(diff_short, local_now())
        await _settle(pilot)
        assert int(scroll.scroll_y) < 300  # clamped by the short body

        panel._display_file_with_timestamp(diff_full, local_now())
        await _settle(pilot)
        assert int(scroll.scroll_y) == 300


async def test_transient_shrink_then_regrow_recovers_static_file(tmp_path: Any) -> None:
    """The same clamp-then-forget fix applies to the static-file render path."""
    content = "\n".join(f"line {i:04d}" for i in range(400)) + "\n"
    path = str(tmp_path / "notes.txt")

    async with _FilePanelTestApp().run_test(size=(100, 30)) as pilot:
        panel = pilot.app.query_one(AgentFilePanel)
        scroll = pilot.app.query_one("#agent-file-scroll", VerticalScroll)
        _seed_slot(panel, agent_identity="agent-1", file_list=[path])

        ok_result = StaticReadResult(
            request_id=0,
            mode="file",
            path=path,
            expanded_path=path,
            status="ok",
            content=content,
            lexer="text",
        )
        panel._render_static_file_result(ok_result)
        await _settle(pilot)
        scroll.scroll_to(y=300, animate=False, immediate=True)
        await pilot.pause()
        assert int(scroll.scroll_y) == 300

        empty_result = StaticReadResult(
            request_id=0,
            mode="file",
            path=path,
            expanded_path=path,
            status="empty",
        )
        panel._render_static_file_result(empty_result)
        await _settle(pilot)
        assert int(scroll.scroll_y) < 300

        panel._render_static_file_result(ok_result)
        await _settle(pilot)
        assert int(scroll.scroll_y) == 300


async def test_content_inserted_above_keeps_reader_on_same_text() -> None:
    """Root cause C: inserted lines must not slide the text under the reader."""
    lines_before = [f"+line {i:04d} content here" for i in range(400)]
    diff_before = "\n".join(lines_before) + "\n"

    async with _FilePanelTestApp().run_test(size=(100, 30)) as pilot:
        panel = pilot.app.query_one(AgentFilePanel)
        scroll = pilot.app.query_one("#agent-file-scroll", VerticalScroll)
        _seed_slot(panel, agent_identity="agent-1", file_list=[_LIVE_DIFF_SENTINEL])

        panel._display_file_with_timestamp(diff_before, local_now())
        await _settle(pilot)
        scroll.scroll_to(y=150, animate=False, immediate=True)
        await pilot.pause()
        top_row = int(scroll.scroll_y)
        before_text = _normalize_row(panel.render_line(top_row).text)

        lines_after = [f"+prepended {i:04d}" for i in range(40)] + lines_before
        diff_after = "\n".join(lines_after) + "\n"
        panel._display_file_with_timestamp(diff_after, local_now())
        await _settle(pilot)

        assert int(scroll.scroll_y) == top_row + 40
        after_text = _normalize_row(panel.render_line(int(scroll.scroll_y)).text)
        assert after_text == before_text


async def test_reader_movement_wins_over_stale_anchor() -> None:
    """A manual scroll after settling must not be yanked back by the next render."""
    diff_full = _numbered_lines(400)

    async with _FilePanelTestApp().run_test(size=(100, 30)) as pilot:
        panel = pilot.app.query_one(AgentFilePanel)
        scroll = pilot.app.query_one("#agent-file-scroll", VerticalScroll)
        _seed_slot(panel, agent_identity="agent-1", file_list=[_LIVE_DIFF_SENTINEL])

        panel._display_file_with_timestamp(diff_full, local_now())
        await _settle(pilot)
        scroll.scroll_to(y=300, animate=False, immediate=True)
        await pilot.pause()

        # Settle the anchor at 300 (an unchanged-content refresh restores it).
        panel._display_file_with_timestamp(diff_full, local_now())
        await _settle(pilot)
        assert int(scroll.scroll_y) == 300

        # The reader scrolls elsewhere before the next refresh tick.
        scroll.scroll_to(y=120, animate=False, immediate=True)
        await pilot.pause()

        # A periodic refresh with unchanged content must adopt the reader's
        # new position rather than reverting to the stale 300 anchor.
        panel._display_file_with_timestamp(diff_full, local_now())
        await _settle(pilot)
        assert int(scroll.scroll_y) == 120


async def test_per_page_anchors_survive_navigation(tmp_path: Any) -> None:
    """Each page slot remembers its own position, independent of the others."""
    content_a = "\n".join(f"a-line {i:04d}" for i in range(400)) + "\n"
    content_b = "\n".join(f"b-line {i:04d}" for i in range(400)) + "\n"
    path_a = tmp_path / "a.txt"
    path_a.write_text(content_a, encoding="utf-8")
    path_b = tmp_path / "b.txt"
    path_b.write_text(content_b, encoding="utf-8")

    async with _FilePanelTestApp().run_test(size=(100, 30)) as pilot:
        panel = pilot.app.query_one(AgentFilePanel)
        scroll = pilot.app.query_one("#agent-file-scroll", VerticalScroll)
        _seed_slot(
            panel,
            agent_identity="agent-1",
            file_list=[str(path_a), str(path_b)],
        )

        panel.display_static_file(str(path_a))
        await _settle_static_worker(pilot, panel)
        scroll.scroll_to(y=150, animate=False, immediate=True)
        await pilot.pause()
        assert int(scroll.scroll_y) == 150

        panel.next_file()
        await _settle_static_worker(pilot, panel)
        assert int(scroll.scroll_y) == 0  # page B has never been opened

        panel.prev_file()
        await _settle_static_worker(pilot, panel)
        assert int(scroll.scroll_y) == 150  # back to A's remembered position


async def test_placeholder_no_changes_does_not_destroy_anchor() -> None:
    """The "No changes detected." placeholder must not clobber the anchor."""
    diff_full = _numbered_lines(400)

    async with _FilePanelTestApp().run_test(size=(100, 30)) as pilot:
        panel = pilot.app.query_one(AgentFilePanel)
        scroll = pilot.app.query_one("#agent-file-scroll", VerticalScroll)
        _seed_slot(panel, agent_identity="agent-1", file_list=[_LIVE_DIFF_SENTINEL])

        panel._display_file_with_timestamp(diff_full, local_now())
        await _settle(pilot)
        scroll.scroll_to(y=300, animate=False, immediate=True)
        await pilot.pause()
        assert int(scroll.scroll_y) == 300

        panel._display_file_with_timestamp(None, local_now())
        await _settle(pilot)
        assert int(scroll.scroll_y) == 0

        panel._display_file_with_timestamp(diff_full, local_now())
        await _settle(pilot)
        assert int(scroll.scroll_y) == 300
