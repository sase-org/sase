"""Live inotify freshness: mutation → UI callback → visible apply."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from sase.ace.tui.util.fs_watcher import (
    DEFAULT_COALESCE_S,
    DEFAULT_DISPATCH_DEADLINE_S,
)
from sase.ace.tui.util.nav_gate import DEFAULT_NAVIGATE_WINDOW_S
from tests.ace.tui._freshness_fixtures import (
    FreshnessApp,
    LatencySample,
    PROMPT_SOURCE_DEBOUNCE_S,
    arm_live_agent_dir,
    isolate_freshness_home,
    saw_callback_path,
    start_artifact_watcher,
    wait,
)
from tests.ace.tui._fs_watcher_helpers import LINUX_ONLY

__all__ = [
    "test_agent_marker_write_reaches_delta_and_agents_stamp",
    "test_bead_store_write_schedules_patches",
    "test_continuous_relevant_writes_dispatch_within_one_second",
    "test_event_to_callback_and_visible_latencies_are_distinct",
    "test_ignored_only_burst_dispatches_nothing",
    "test_live_reply_write_reaches_detail_handler",
    "test_mixed_noise_and_relevant_write_keeps_real_path",
    "test_nav_gate_defers_callback_apply_by_window",
    "test_notification_arrival_schedules_immediate_poll",
    "test_prompt_source_edit_rebuilds_after_debounce",
    "test_quiescent_dispatch_meets_one_second_deadline",
    "test_watcher_startup_failure_leaves_polling_fallback",
]


def _sample(
    case: str,
    mutation: float,
    app: FreshnessApp,
    *,
    cadence: float,
    gate: float = 0.0,
) -> LatencySample:
    return LatencySample(
        case=case,
        mutation_mono=mutation,
        callback_mono=app.last_callback_mono(),
        visible_mono=app.last_visible_mono(),
        cadence_s=cadence,
        activity_gate_s=gate,
        work=app.watcher_work(),
    )


def _stop(app: FreshnessApp) -> None:
    app._stop_artifact_watcher()
    app._stop_prompt_source_watcher()


@LINUX_ONLY
@pytest.mark.asyncio
async def test_agent_marker_write_reaches_delta_and_agents_stamp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = isolate_freshness_home(tmp_path, monkeypatch)
    app = FreshnessApp(sdd_beads_dir=home.beads_dir)
    start_artifact_watcher(app, home)
    arm_live_agent_dir(app, home)
    marker = home.agent_dir / "agent_meta.json"
    try:
        mutation = time.monotonic()
        marker.write_text("{}")
        assert wait(lambda: saw_callback_path(app, marker), timeout=3.0)
        await app._run_auto_refresh()
        sample = _sample("agent_store", mutation, app, cadence=DEFAULT_COALESCE_S)
        assert sample.event_to_callback_s is not None
        assert sample.event_to_callback_s <= DEFAULT_DISPATCH_DEADLINE_S + 0.4
        assert any(call.startswith("delta:") for call in app.refresh_calls)
        assert app._dirty_agents is False
        assert sample.event_to_visible_s is not None
        assert sample.event_to_visible_s >= sample.event_to_callback_s
        assert app.watcher_work()["ui_dispatches"] >= 1
        assert app.watcher_work()["accepted_events"] >= 1
    finally:
        _stop(app)


@LINUX_ONLY
@pytest.mark.asyncio
async def test_bead_store_write_schedules_patches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = isolate_freshness_home(tmp_path, monkeypatch)
    app = FreshnessApp(sdd_beads_dir=home.beads_dir)
    start_artifact_watcher(app, home)
    try:
        mutation = time.monotonic()
        (home.beads_dir / "issues.jsonl").write_text("{}\n")
        assert wait(lambda: "schedule_patches" in app.refresh_calls, timeout=3.0)
        sample = _sample("bead_store", mutation, app, cadence=DEFAULT_COALESCE_S)
        assert app._dirty_patches is True
        assert app._dirty_agents is False
        assert sample.event_to_callback_s is not None
        assert sample.event_to_visible_s is not None
        assert sample.event_to_visible_s <= DEFAULT_DISPATCH_DEADLINE_S + 0.4
    finally:
        _stop(app)


@LINUX_ONLY
def test_notification_arrival_schedules_immediate_poll(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = isolate_freshness_home(tmp_path, monkeypatch)
    app = FreshnessApp(sdd_beads_dir=home.beads_dir)
    start_artifact_watcher(app, home)
    try:
        mutation = time.monotonic()
        (home.notifications_dir / "note.json").write_text("{}")
        assert wait(lambda: app.notification_polls == ["watcher"], timeout=3.0)
        sample = _sample("notification", mutation, app, cadence=DEFAULT_COALESCE_S)
        assert app._dirty_notifications is True
        assert app._dirty_agents is False
        assert sample.event_to_callback_s is not None
        assert sample.event_to_visible_s is not None
        assert abs(sample.event_to_visible_s - sample.event_to_callback_s) < 0.05
    finally:
        _stop(app)


@LINUX_ONLY
def test_live_reply_write_reaches_detail_handler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = isolate_freshness_home(tmp_path, monkeypatch)
    app = FreshnessApp(sdd_beads_dir=home.beads_dir)
    start_artifact_watcher(app, home)
    arm_live_agent_dir(app, home)
    reply = home.agent_dir / "live_reply.md"
    try:
        mutation = time.monotonic()
        reply.write_text("hello")
        assert wait(lambda: bool(app.live_reply_paths), timeout=3.0)
        sample = _sample("live_reply", mutation, app, cadence=DEFAULT_COALESCE_S)
        assert any(reply in paths for paths in app.live_reply_paths)
        assert sample.event_to_visible_s is not None
        assert sample.event_to_visible_s <= DEFAULT_DISPATCH_DEADLINE_S + 0.4
    finally:
        _stop(app)


@LINUX_ONLY
def test_prompt_source_edit_rebuilds_after_debounce(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = isolate_freshness_home(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "sase.ace.tui.prompt_catalog.prompt_source_watch_paths",
        lambda _projects: [home.prompt_dir],
    )
    app = FreshnessApp(sdd_beads_dir=home.beads_dir)
    app._start_prompt_source_watcher()
    assert app._prompt_source_watcher_active is True
    try:
        mutation = time.monotonic()
        (home.prompt_dir / "macro.md").write_text("# hi\n")
        assert wait(lambda: bool(app.callback_times), timeout=3.0)
        assert app.deferred_calls
        delay, callback = app.deferred_calls[-1]
        assert delay == pytest.approx(PROMPT_SOURCE_DEBOUNCE_S)
        callback()
        sample = _sample(
            "prompt_source",
            mutation,
            app,
            cadence=DEFAULT_COALESCE_S,
            gate=PROMPT_SOURCE_DEBOUNCE_S,
        )
        assert app.prompt_rebuilds == [
            {"reason": "prompt_source_change", "config_dirty": False}
        ]
        assert sample.event_to_callback_s is not None
        assert sample.event_to_visible_s is not None
        assert sample.event_to_visible_s >= sample.event_to_callback_s
    finally:
        _stop(app)


@LINUX_ONLY
def test_mixed_noise_and_relevant_write_keeps_real_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = isolate_freshness_home(tmp_path, monkeypatch)
    app = FreshnessApp(sdd_beads_dir=home.beads_dir)
    start_artifact_watcher(app, home)
    arm_live_agent_dir(app, home)
    real = home.agent_dir / "agent_meta.json"
    try:
        mutation = time.monotonic()
        (home.agent_dir / ".noise.swp").write_text("x")
        (home.agent_dir / "output.log").write_text("log")
        real.write_text("{}")
        assert wait(lambda: app._dirty_agents is True, timeout=3.0)
        sample = _sample("mixed_noise", mutation, app, cadence=DEFAULT_COALESCE_S)
        assert sample.event_to_callback_s is not None
        assert home.agent_dir in app._dirty_agent_artifact_dirs
        stats = app.watcher_work()
        assert stats["ignored_events"] >= 1
        assert stats["accepted_events"] >= 1
        assert stats["ui_dispatches"] >= 1
    finally:
        _stop(app)


@LINUX_ONLY
def test_ignored_only_burst_dispatches_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = isolate_freshness_home(tmp_path, monkeypatch)
    app = FreshnessApp(sdd_beads_dir=home.beads_dir)
    start_artifact_watcher(app, home)
    arm_live_agent_dir(app, home)
    try:
        stats_before = app.watcher_work()
        for index in range(8):
            (home.agent_dir / f".noise{index}.swp").write_text("x")
        time.sleep(0.45)  # sase-test-wait: ignored-only coalesce + deadline
        assert app.callback_times == []
        assert app.refresh_calls == []
        stats = app.watcher_work()
        assert stats["ui_dispatches"] == stats_before["ui_dispatches"]
        assert stats["queued_dispatches"] == stats_before["queued_dispatches"]
        assert stats["ignored_events"] >= stats_before.get("ignored_events", 0) + 1
    finally:
        _stop(app)


@LINUX_ONLY
def test_continuous_relevant_writes_dispatch_within_one_second(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = isolate_freshness_home(tmp_path, monkeypatch)
    app = FreshnessApp(sdd_beads_dir=home.beads_dir)
    start_artifact_watcher(app, home)
    arm_live_agent_dir(app, home)
    stop_writes = threading.Event()
    marker = home.agent_dir / "agent_meta.json"

    def writer() -> None:
        count = 0
        while not stop_writes.is_set():
            marker.write_text(str(count))
            count += 1
            time.sleep(0.05)  # sase-test-wait: sustained writer cadence

    thread = threading.Thread(target=writer, daemon=True)
    try:
        mutation = time.monotonic()
        thread.start()
        assert wait(lambda: saw_callback_path(app, marker), timeout=2.5)
        sample = _sample(
            "continuous_writes",
            mutation,
            app,
            cadence=DEFAULT_DISPATCH_DEADLINE_S,
        )
        assert sample.event_to_callback_s is not None
        assert sample.event_to_callback_s <= DEFAULT_DISPATCH_DEADLINE_S + 0.5
        assert app.watcher_work()["ui_dispatches"] >= 1
    finally:
        stop_writes.set()
        thread.join(timeout=1.0)
        _stop(app)


@LINUX_ONLY
def test_quiescent_dispatch_meets_one_second_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = isolate_freshness_home(tmp_path, monkeypatch)
    app = FreshnessApp(sdd_beads_dir=home.beads_dir)
    start_artifact_watcher(app, home)
    arm_live_agent_dir(app, home)
    marker = home.agent_dir / "done.json"
    try:
        mutation = time.monotonic()
        marker.write_text("{}")
        assert wait(lambda: saw_callback_path(app, marker), timeout=3.0)
        sample = _sample(
            "quiescent_1s", mutation, app, cadence=DEFAULT_DISPATCH_DEADLINE_S
        )
        assert sample.event_to_callback_s is not None
        assert sample.event_to_callback_s <= DEFAULT_DISPATCH_DEADLINE_S + 0.4
        assert sample.event_to_callback_s >= 0.0
    finally:
        _stop(app)


@LINUX_ONLY
@pytest.mark.asyncio
async def test_event_to_callback_and_visible_latencies_are_distinct(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = isolate_freshness_home(tmp_path, monkeypatch)
    app = FreshnessApp(sdd_beads_dir=home.beads_dir)
    app.current_tab = "agents"
    start_artifact_watcher(app, home)
    arm_live_agent_dir(app, home)
    marker = home.agent_dir / "agent_meta.json"
    try:
        mutation = time.monotonic()
        marker.write_text("{}")
        assert wait(lambda: saw_callback_path(app, marker), timeout=3.0)
        callback = app.last_callback_mono()
        assert callback is not None
        await app._run_auto_refresh()
        visible = app.last_visible_mono()
        assert visible is not None
        assert visible >= callback
        assert callback - mutation != visible - mutation or visible == callback
        assert app.refresh_calls
    finally:
        _stop(app)


def test_watcher_startup_failure_leaves_polling_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = isolate_freshness_home(tmp_path, monkeypatch)

    class _FailingWatcher:
        def __init__(self, watch_paths: list[Path], **kwargs: object) -> None:
            del watch_paths, kwargs

        def start(self) -> bool:
            return False

    monkeypatch.setattr(
        "sase.ace.tui.actions._startup_watchers.ArtifactWatcher",
        _FailingWatcher,
    )
    app = FreshnessApp(sdd_beads_dir=home.beads_dir)
    app._start_artifact_watcher()
    assert app._fs_watcher is None
    assert app._watcher_active() is False


def test_nav_gate_defers_callback_apply_by_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolate_freshness_home(tmp_path, monkeypatch)
    app = FreshnessApp()
    app._record_jk_navigation()
    mutation = time.monotonic()
    app._on_artifact_change((tmp_path / "agent_meta.json",))
    assert app.refresh_calls == []
    assert app.deferred_calls
    delay, callback = app.deferred_calls[0]
    assert 0.05 <= delay <= DEFAULT_NAVIGATE_WINDOW_S + 0.1
    assert callback is not None
    sample = LatencySample(
        case="nav_gate",
        mutation_mono=mutation,
        callback_mono=app.last_callback_mono(),
        visible_mono=None,
        cadence_s=DEFAULT_COALESCE_S,
        activity_gate_s=delay,
    )
    assert sample.event_to_callback_s is not None
    assert sample.event_to_visible_s is None
