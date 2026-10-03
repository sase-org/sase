"""Changes-lens mixin behaviors that do not need git."""

from __future__ import annotations

from sase.ace.tui.modals.memory_pane_changes_lens import MemoryPaneChangesLensMixin
from tests.ace.tui.modals._memory_pane_changes_lens_helpers import (
    DAY_ONE,
    make_changeset,
    make_feed,
    prepare_changes_panel,
    rail_texts,
)


async def test_changes_lens_opens_and_esc_restores_notes(monkeypatch) -> None:
    """``C`` turns the rail into changesets; ``Esc`` restores Notes."""
    from textual.widgets import Static

    from sase.ace.testing import wait_for

    panel, app, _pushed = prepare_changes_panel(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        before = panel._current_note
        await pilot.press("C")
        await wait_for(pilot, lambda: panel._lens == "changes")
        await wait_for(pilot, lambda: panel._changes_feed is not None)
        await pilot.pause()
        texts = rail_texts(panel)
        assert any("Today" in text or "━" in text for text in texts)
        assert any("artifact" in text for text in texts)
        header = panel.query_one("#memory-panel-header", Static)
        assert "changes" in str(header.content.plain)
        await pilot.press("escape")
        await wait_for(pilot, lambda: panel._lens == "notes")
        assert panel._current_note == before
        restored = rail_texts(panel)
        assert any("gotchas" in text for text in restored)


async def test_timeline_key_is_inert_in_changes(monkeypatch) -> None:
    """``@`` does nothing inside the Changes lens."""
    from sase.ace.testing import wait_for

    panel, app, _pushed = prepare_changes_panel(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("C")
        await wait_for(pilot, lambda: panel._lens == "changes")
        await pilot.press("@")
        await pilot.pause()
        assert panel._lens == "changes"


async def test_changes_key_is_inert_in_timeline(monkeypatch) -> None:
    """``C`` stays inert inside the Timeline lens (D3)."""
    from sase.ace.testing import wait_for

    panel, app, _pushed = prepare_changes_panel(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        panel._lens = "timeline"
        await pilot.press("C")
        await pilot.pause()
        assert panel._lens == "timeline"


async def test_pager_handoff_uses_diff_view_at_changeset_version(monkeypatch) -> None:
    """``H`` in the lens opens the pager in diff view at the right version."""
    from sase.ace.testing import wait_for

    panel, app, pushed = prepare_changes_panel(monkeypatch)
    import sase.memory.history.pager_provider as pager_provider_module

    seen: dict = {}
    sentinel = object()
    monkeypatch.setattr(
        pager_provider_module,
        "build_history_document",
        lambda **kwargs: (seen.update(kwargs), sentinel)[1],
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("C")
        await wait_for(pilot, lambda: panel._changes_feed is not None)
        await pilot.pause()
        # Move onto the first changeset row (past the day header).
        await pilot.press("j")
        await pilot.pause()
        await pilot.press("H")
        await wait_for(pilot, lambda: len(pushed) == 1)
        assert seen["initial_revision"] == "v3"
        assert seen["view"] == "diff"
        assert seen["subject"] == "sase/memory/glossary/artifact.md"
        assert pushed[0].document is sentinel


async def test_window_extends_at_more_row(monkeypatch) -> None:
    """Reaching the trailing row grows the window by 100."""
    from sase.ace.testing import wait_for

    big = make_feed(
        *[
            make_changeset(commit=f"{index:040d}", committer_time=DAY_ONE + index)
            for index in range(150)
        ]
    )
    panel, app, _pushed = prepare_changes_panel(monkeypatch, feed=big)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("C")
        await wait_for(pilot, lambda: panel._changes_feed is not None)
        await pilot.pause()
        assert panel._changes_limit == 100
        assert panel._changes_older == 50
        panel._changes_extend_window()
        assert panel._changes_limit == 200
        assert panel._changes_older == 0


async def test_changes_filter_routes_to_lens_rows(monkeypatch) -> None:
    """``/`` in the lens filters changesets, leaving the Notes filter alone."""
    from sase.ace.testing import wait_for

    panel, app, _pushed = prepare_changes_panel(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("C")
        await wait_for(pilot, lambda: panel._changes_feed is not None)
        await pilot.pause()
        await pilot.press("/")
        await pilot.pause()
        await pilot.press("g")
        await pilot.press("l")
        await pilot.press("o")
        await pilot.pause()
        texts = rail_texts(panel)
        assert any("artifact" in text for text in texts)
        assert panel._filter_text == ""
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert panel._lens == "notes"


async def test_stale_feed_load_is_dropped(monkeypatch) -> None:
    """A feed that lands after a refetch never paints (last wins)."""
    import threading

    from sase.ace.testing import wait_for

    panel, app, _pushed = prepare_changes_panel(monkeypatch)
    started = threading.Event()
    release = threading.Event()
    history = panel._ace_history()
    real_feed = history.feed

    def _slow_feed(scopes):  # noqa: ANN001, ANN202
        started.set()
        assert release.wait(timeout=10)
        return real_feed(scopes)

    history.feed = _slow_feed
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("C")
        await wait_for(pilot, lambda: panel._lens == "changes")
        await wait_for(pilot, lambda: started.is_set())
        panel._changes_generation += 1  # A refetch won before the load landed.
        release.set()
        await wait_for(pilot, lambda: panel._changes_worker.is_finished)
        await pilot.pause()
        assert panel._changes_feed is None


def test_preview_fire_drops_superseded_motion() -> None:
    """A scheduled preview older than the cursor never renders."""
    panel = MemoryPaneChangesLensMixin.__new__(MemoryPaneChangesLensMixin)
    panel._lens = "changes"  # type: ignore[attr-defined]
    panel._changes_cursor = 2  # type: ignore[attr-defined]
    panel._changes_scheduled = 1  # type: ignore[attr-defined]
    rendered: list = []
    panel._render_note_card = lambda: rendered.append(True)  # type: ignore[method-assign]
    panel._changes_preview_fire()
    assert rendered == []
