"""Tests for launchable MRU prompt cycling behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.launchable_mru import (
    COLD_LAUNCHABLE_MRU_SNAPSHOT,
    LaunchableMruSnapshot,
)
from sase.history.vcs_macro_mru import load_launchable_vcs_macro_mru
from tests.ace.tui._launchable_mru_test_helpers import (
    SnapshotApp,
    ready_snapshot,
    seed_mru,
)
from tests.ace.tui._prompt_key_io_probes import prompt_key_io_probe


async def _cycle_press(app: SnapshotApp, start_text: str, key: str) -> tuple[str, int]:
    from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text(start_text)
        ta.move_cursor(ta._location_from_absolute(len(start_text)))
        ta.focus()
        await pilot.press(key)
        return ta.text, ta._absolute_offset(ta.cursor_location)


async def test_burst_pins_ring_and_next_session_sees_new_generation() -> None:
    """A mid-burst publish cannot reorder the ring; a new session re-peeks."""
    from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

    app = SnapshotApp(ready_snapshot(["#git:aaa", "#git:bbb"], generation=1))
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("")
        ta.focus()
        await pilot.press("ctrl+p")
        assert ta.text == "#git:aaa "
        assert ta._vcs_mru_ring == ("#git:aaa", "#git:bbb")
        assert ta._vcs_mru_ring_generation == 1
        # Publish a new snapshot mid-burst: the ring and index hold.
        app._snapshot = ready_snapshot(["#git:zzz"], generation=2)
        await pilot.press("ctrl+p")
        assert ta.text == "#git:bbb "
        assert ta._vcs_mru_ring == ("#git:aaa", "#git:bbb")
        # A new session (ring reset) picks up the new generation.
        ta._reset_vcs_mru_cycle_state()
        ta.load_text("")
        await pilot.press("ctrl+p")
        assert ta.text == "#git:zzz "
        assert ta._vcs_mru_ring_generation == 2


async def test_cold_snapshot_leaves_text_and_requests_build() -> None:
    """Cold ``ctrl+p`` changes nothing, hints, and schedules one build."""
    app = SnapshotApp(COLD_LAUNCHABLE_MRU_SNAPSHOT)
    text, _cursor = await _cycle_press(app, "", "ctrl+p")
    assert text == ""
    assert app.refresh_requests == ["cycle-cold"]


async def test_error_snapshot_behaves_like_cold() -> None:
    """An error snapshot also leaves the text untouched and retries."""
    app = SnapshotApp(LaunchableMruSnapshot(state="error", generation=3))
    text, _cursor = await _cycle_press(app, "", "ctrl+p")
    assert text == ""
    assert app.refresh_requests == ["cycle-cold"]


async def test_warm_cycle_performs_zero_main_thread_io() -> None:
    """A warm snapshot ``ctrl+p`` reads no MRU, lists nothing, spawns nothing.

    The press runs with a cold macro-identity registry so the probe covers
    the landing's zero-I/O guarantee, not a process-warmed cache.
    """
    from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
    from sase.macro.project_identity import invalidate_macro_project_identity

    invalidate_macro_project_identity()
    app = SnapshotApp(ready_snapshot(["#git:aaa", "#git:bbb"]))
    try:
        async with app.run_test() as pilot:
            ta = app.query_one(PromptTextArea)
            ta.load_text("")
            ta.focus()
            invalidate_macro_project_identity()
            with prompt_key_io_probe() as counts:
                await pilot.press("ctrl+p")
            counts.assert_quiet()
            assert ta.text == "#git:aaa "
            assert app.identity_warm_requests, "cold press must request one warm"
    finally:
        invalidate_macro_project_identity()


async def test_warm_cycle_ctrl_n_performs_zero_main_thread_io() -> None:
    """A warm snapshot ``ctrl+n`` reads no MRU, lists nothing, spawns nothing.

    The press runs with a cold macro-identity registry so the probe covers
    the landing's zero-I/O guarantee, not a process-warmed cache.
    """
    from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
    from sase.macro.project_identity import invalidate_macro_project_identity

    invalidate_macro_project_identity()
    app = SnapshotApp(ready_snapshot(["#git:aaa", "#git:bbb"]))
    try:
        async with app.run_test() as pilot:
            ta = app.query_one(PromptTextArea)
            ta.load_text("")
            ta.focus()
            invalidate_macro_project_identity()
            with prompt_key_io_probe() as counts:
                await pilot.press("ctrl+n")
            counts.assert_quiet()
            assert ta.text == "#git:bbb "
            assert app.identity_warm_requests, "cold press must request one warm"
    finally:
        invalidate_macro_project_identity()


async def test_snapshot_cycle_matches_loader_cycle_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cycling from a seeded snapshot reproduces the fallback loader results."""
    from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
    from unittest.mock import patch as mock_patch

    entries = ["#git:foo", "#git:bar"]
    seed_mru(tmp_path, monkeypatch, entries)
    expected_ring = load_launchable_vcs_macro_mru(prune=False)

    app = SnapshotApp(ready_snapshot(expected_ring))
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("")
        ta.focus()
        with mock_patch(
            "sase.history.vcs_macro_mru.load_launchable_vcs_macro_mru",
            side_effect=AssertionError("snapshot path must not load"),
        ):
            await pilot.press("ctrl+p")
            first = ta.text
            await pilot.press("ctrl+p")
            second = ta.text
    assert first == f"{expected_ring[0]} "
    assert second == f"{expected_ring[1]} "
