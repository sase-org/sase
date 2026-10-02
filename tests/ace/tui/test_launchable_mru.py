"""Tests for the app-owned launchable-MRU snapshot (epic sase-1ex, mru-snapshot).

Covers the phase contract: parity with the loader, single-flight builds,
stale-generation drops, freshness triggers, per-session ring pinning, cold
behavior, and zero main-thread I/O on warm cycle keys.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from textual.app import App, ComposeResult

from sase.ace.tui.actions._launchable_mru import (
    LaunchableMruMixin,
    init_launchable_mru_state,
)
from sase.ace.tui.launchable_mru import (
    COLD_LAUNCHABLE_MRU_SNAPSHOT,
    LaunchableMruSnapshot,
    build_launchable_mru_data,
)
from sase.history.vcs_xprompt_mru import load_launchable_vcs_xprompt_mru
from tests._vcs_xprompt_mru_helpers import patched_mru_file
from tests.ace.tui._prompt_key_io_probes import prompt_key_io_probe
from tests.conftest import redirect_sase_home


@pytest.fixture(autouse=True)
def _reset_vcs_tag_pattern_cache() -> object:
    """Rebuild the lazily-cached VCS tag pattern from the real providers."""
    import sase.xprompt._parsing as parsing
    import sase.xprompt._parsing_vcs_tags as vcs_tags

    parsing._VCS_TAG_PATTERN = None
    parsing._VCS_TAG_EMBEDDED_PATTERN = None
    vcs_tags._VCS_TAG_PATTERN = None
    vcs_tags._VCS_TAG_EMBEDDED_PATTERN = None
    yield
    parsing._VCS_TAG_PATTERN = None
    parsing._VCS_TAG_EMBEDDED_PATTERN = None
    vcs_tags._VCS_TAG_PATTERN = None
    vcs_tags._VCS_TAG_EMBEDDED_PATTERN = None


def _seed_mru(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entries: list[str]
) -> Path:
    sase_home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    workspace = tmp_path / "ws"
    workspace.mkdir(exist_ok=True)
    mru_file = sase_home / "vcs_xprompt_mru.json"
    mru_file.write_text(json.dumps({"entries": entries}))
    monkeypatch.setattr(
        "sase.xprompt.loader.get_known_project_workspaces",
        lambda *a, **k: {"foo": workspace, "bar": workspace},
    )
    monkeypatch.setattr(
        "sase.ace.patch.cache.find_all_patches_cached",
        lambda *a, **k: [],
    )
    return mru_file


def test_snapshot_ring_matches_loader_displays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The snapshot ring equals the loader's displays across prune classes."""
    mru_file = _seed_mru(
        tmp_path,
        monkeypatch,
        ["#git:foo", "#git:home", "#git:bar", "#git:gone-proj", "#gh:stale-patch"],
    )
    before = mru_file.read_bytes()
    built = build_launchable_mru_data(force=True)
    assert built is not None
    _signature, pairs, _token = built
    assert [display for _, display in pairs] == load_launchable_vcs_xprompt_mru(
        prune=False
    )
    # The build never writes: key paths must not prune the MRU file.
    assert mru_file.read_bytes() == before


def test_worker_fast_path_skips_unchanged_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A matching signature publishes nothing unless forced."""
    _seed_mru(tmp_path, monkeypatch, ["#git:foo"])
    first = build_launchable_mru_data(force=True)
    assert first is not None
    signature, _pairs, _token = first
    assert build_launchable_mru_data(force=False, last_signature=signature) is None
    assert build_launchable_mru_data(force=True, last_signature=signature) is not None


def test_build_failure_raises_for_error_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Loader failure raises so the caller publishes ``error``, not stale data."""
    _seed_mru(tmp_path, monkeypatch, ["#git:foo"])
    with patch(
        "sase.history.vcs_xprompt_mru.load_launchable_vcs_xprompt_mru_pairs",
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(RuntimeError):
            build_launchable_mru_data(force=True)


class _StubHost(LaunchableMruMixin):
    """Minimal mixin host: immediate publish, no timers."""

    def __init__(self) -> None:
        init_launchable_mru_state(self)
        self._launchable_mru_tick_timer = object()
        self.build_calls = 0

    def call_from_thread(self, callback: Any, *args: Any) -> Any:
        return callback(*args)

    def set_interval(self, *args: Any, **kwargs: Any) -> object:
        raise AssertionError("ticks are armed once in startup, not in unit tests")


async def _wait_for(
    predicate: Any, *, timeout: float = 10.0, step: float = 0.01
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        assert asyncio.get_running_loop().time() < deadline, "timed out"
        await asyncio.sleep(step)


async def test_single_flight_coalesces_to_one_follow_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """N requests during a build produce exactly one follow-up build."""
    import threading

    import sase.ace.tui.actions._launchable_mru as mixin_module

    release = threading.Event()
    calls = 0

    def fake_build(
        *, force: bool = False, last_signature: Any = None
    ) -> tuple[Any, list[tuple[str, str]], Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            # Hold the first build open on a thread so the follow-up
            # requests land while it is still in flight.
            assert release.wait(timeout=10.0)
        return (("sig", calls), [("#git:foo", "#git:foo")], ("tok", calls))

    monkeypatch.setattr(mixin_module, "build_launchable_mru_data", fake_build)
    host = _StubHost()
    host.request_launchable_mru_refresh(reason="first")
    await _wait_for(lambda: calls >= 1)
    assert host._launchable_mru_build_in_flight
    for _ in range(5):
        host.request_launchable_mru_refresh(reason="burst")
    release.set()
    await _wait_for(lambda: calls == 2 and not host._launchable_mru_build_in_flight)
    assert calls == 2
    assert host._launchable_mru_snapshot.state == "ready"


async def test_stale_generation_never_publishes() -> None:
    """A late result for an old generation is dropped, not published."""
    host = _StubHost()
    host._finish_launchable_mru_build(
        5, ("sig5",), (("#git:new", "#git:new"),), ("tok5",)
    )
    assert host._launchable_mru_snapshot.display_ring == ("#git:new",)
    host._finish_launchable_mru_build(
        3, ("sig3",), (("#git:stale", "#git:stale"),), ("tok3",)
    )
    assert host._launchable_mru_snapshot.display_ring == ("#git:new",)
    assert host._launchable_mru_generation == 5


async def test_token_drift_requests_one_rebuild(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tick rebuilds once when the peek token drifts."""
    import sase.ace.tui.actions._launchable_mru as mixin_module

    monkeypatch.setattr(mixin_module, "build_launchable_mru_data", lambda **k: None)
    import sase.current_project as current_project_module

    monkeypatch.setattr(
        current_project_module,
        "peek_current_project_change_token",
        lambda: ("drifted",),
    )
    host = _StubHost()
    host._launchable_mru_snapshot = LaunchableMruSnapshot(
        state="ready",
        pairs=(("#git:foo", "#git:foo"),),
        generation=1,
        token=("old",),
    )
    host._launchable_mru_generation = 1
    host._launchable_mru_token = ("old",)
    host._launchable_mru_tick()
    # The skipped (fast-path) build still drains the in-flight flag.
    await _wait_for(lambda: not host._launchable_mru_build_in_flight)


async def test_launch_marks_pending_synchronously(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Submit flags the snapshot stale on the submit path, before the build."""
    from sase.ace.tui.actions.agent_workflow import _launch_submit_helpers

    _seed_mru(tmp_path, monkeypatch, ["#git:foo"])
    monkeypatch.setattr(
        _launch_submit_helpers,
        "spawn_pump_free_task",
        lambda *a, **k: None,
    )
    host = _StubHost()
    assert not host.peek_launchable_mru_snapshot().refresh_pending
    _launch_submit_helpers.schedule_submit_time_vcs_replay(host, ["hello"])
    assert host.peek_launchable_mru_snapshot().refresh_pending


class _SnapshotApp(App):
    """Bare host app serving a canned snapshot like ``AceApp`` does."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(self, snapshot: LaunchableMruSnapshot) -> None:
        super().__init__()
        self._snapshot = snapshot
        self.refresh_requests: list[str] = []

    def compose(self) -> ComposeResult:
        from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

        yield PromptTextArea()

    def peek_launchable_mru_snapshot(self) -> LaunchableMruSnapshot:
        return self._snapshot

    def request_launchable_mru_refresh(
        self, *, reason: str, force: bool = False
    ) -> bool:
        self.refresh_requests.append(reason)
        return True


def _ready_snapshot(rings: list[str], generation: int = 1) -> LaunchableMruSnapshot:
    return LaunchableMruSnapshot(
        state="ready",
        pairs=tuple((entry, entry) for entry in rings),
        generation=generation,
    )


async def _cycle_press(app: _SnapshotApp, start_text: str, key: str) -> tuple[str, int]:
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

    app = _SnapshotApp(_ready_snapshot(["#git:aaa", "#git:bbb"], generation=1))
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("")
        ta.focus()
        await pilot.press("ctrl+p")
        assert ta.text == "#git:aaa "
        assert ta._vcs_mru_ring == ("#git:aaa", "#git:bbb")
        assert ta._vcs_mru_ring_generation == 1
        # Publish a new snapshot mid-burst: the ring and index hold.
        app._snapshot = _ready_snapshot(["#git:zzz"], generation=2)
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
    app = _SnapshotApp(COLD_LAUNCHABLE_MRU_SNAPSHOT)
    text, _cursor = await _cycle_press(app, "", "ctrl+p")
    assert text == ""
    assert app.refresh_requests == ["cycle-cold"]


async def test_error_snapshot_behaves_like_cold() -> None:
    """An error snapshot also leaves the text untouched and retries."""
    app = _SnapshotApp(LaunchableMruSnapshot(state="error", generation=3))
    text, _cursor = await _cycle_press(app, "", "ctrl+p")
    assert text == ""
    assert app.refresh_requests == ["cycle-cold"]


async def test_warm_cycle_performs_zero_main_thread_io() -> None:
    """A warm snapshot ``ctrl+p`` reads no MRU, lists nothing, spawns nothing."""
    from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

    app = _SnapshotApp(_ready_snapshot(["#git:aaa", "#git:bbb"]))
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("")
        ta.focus()
        with prompt_key_io_probe() as counts:
            await pilot.press("ctrl+p")
        counts.assert_quiet()
        assert ta.text == "#git:aaa "


async def test_snapshot_cycle_matches_loader_cycle_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cycling from a seeded snapshot reproduces the fallback loader results."""
    from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
    from unittest.mock import patch as mock_patch

    entries = ["#git:foo", "#git:bar"]
    _seed_mru(tmp_path, monkeypatch, entries)
    expected_ring = load_launchable_vcs_xprompt_mru(prune=False)

    app = _SnapshotApp(_ready_snapshot(expected_ring))
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("")
        ta.focus()
        with mock_patch(
            "sase.history.vcs_xprompt_mru.load_launchable_vcs_xprompt_mru",
            side_effect=AssertionError("snapshot path must not load"),
        ):
            await pilot.press("ctrl+p")
            first = ta.text
            await pilot.press("ctrl+p")
            second = ta.text
    assert first == f"{expected_ring[0]} "
    assert second == f"{expected_ring[1]} "


__all__ = ["_SnapshotApp"]
