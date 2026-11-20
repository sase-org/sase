"""Tests for launchable MRU background refresh behavior."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.tui.launchable_mru import LaunchableMruSnapshot
from tests.ace.tui._launchable_mru_test_helpers import StubHost, seed_mru, wait_for


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
    host = StubHost()
    host.request_launchable_mru_refresh(reason="first")
    await wait_for(lambda: calls >= 1)
    assert host._launchable_mru_build_in_flight
    for _ in range(5):
        host.request_launchable_mru_refresh(reason="burst")
    release.set()
    await wait_for(lambda: calls == 2 and not host._launchable_mru_build_in_flight)
    assert calls == 2
    assert host._launchable_mru_snapshot.state == "ready"


def _ready_host(token: tuple[object, ...] = ("old",)) -> StubHost:
    host = StubHost()
    host._launchable_mru_snapshot = LaunchableMruSnapshot(
        state="ready",
        pairs=(("#git:foo", "#git:foo"),),
        generation=1,
        token=token,
    )
    host._launchable_mru_generation = 1
    host._launchable_mru_token = token
    return host


async def test_stale_generation_never_publishes() -> None:
    """A late result for an old generation is dropped, not published."""
    host = StubHost()
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

    builds: list[bool] = []

    def fake_build(**kwargs: Any) -> None:
        builds.append(bool(kwargs.get("force")))

    monkeypatch.setattr(mixin_module, "build_launchable_mru_data", fake_build)
    import sase.current_project as current_project_module

    monkeypatch.setattr(
        current_project_module,
        "peek_current_project_change_token",
        lambda: ("drifted",),
    )
    host = _ready_host()
    host._launchable_mru_tick()
    await wait_for(
        lambda: (
            builds
            and not host._launchable_mru_build_in_flight
            and not host._launchable_mru_peek_in_flight
        )
    )
    # The skipped (fast-path) build still drains the in-flight flag.
    assert builds == [False]


async def test_tick_peeks_the_change_token_off_the_main_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The timer callback never stats; the real peek runs on a worker thread."""
    import threading

    import sase.ace.tui.actions._launchable_mru as mixin_module
    import sase.current_project as current_project_module
    from tests._main_thread_fs_guard import main_thread_fs_guard

    seed_mru(tmp_path, monkeypatch, ["#git:foo"])
    builds: list[str] = []
    monkeypatch.setattr(
        mixin_module,
        "build_launchable_mru_data",
        lambda **_k: builds.append("build"),
    )
    # Expire the module-level 0.5 s peek cache so this peek really stats.
    monkeypatch.setattr(current_project_module, "_token_cache_deadline", 0.0)
    real_peek = current_project_module.peek_current_project_change_token
    peek_threads: list[int] = []

    def recording_peek() -> tuple[object, ...]:
        peek_threads.append(threading.get_ident())
        return real_peek()

    monkeypatch.setattr(
        current_project_module, "peek_current_project_change_token", recording_peek
    )
    host = _ready_host()
    with main_thread_fs_guard() as violations:
        host._launchable_mru_tick()
        assert host._launchable_mru_peek_in_flight
        await wait_for(
            lambda: (
                builds
                and not host._launchable_mru_build_in_flight
                and not host._launchable_mru_peek_in_flight
            )
        )
    assert violations == []
    assert peek_threads and threading.get_ident() not in peek_threads
    assert builds == ["build"], "a drifted real token must request one rebuild"


async def test_overlapping_ticks_share_one_in_flight_peek(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ticks landing while a peek runs are dropped, not queued."""
    import threading

    import sase.ace.tui.actions._launchable_mru as mixin_module
    import sase.current_project as current_project_module

    builds: list[str] = []
    monkeypatch.setattr(
        mixin_module,
        "build_launchable_mru_data",
        lambda **_k: builds.append("build"),
    )
    release = threading.Event()
    peeks = 0

    def blocking_peek() -> tuple[object, ...]:
        nonlocal peeks
        peeks += 1
        assert release.wait(timeout=10.0)
        return ("old",)

    monkeypatch.setattr(
        current_project_module, "peek_current_project_change_token", blocking_peek
    )
    host = _ready_host()
    for _ in range(4):
        host._launchable_mru_tick()
    await wait_for(lambda: peeks >= 1)
    for _ in range(3):
        host._launchable_mru_tick()
    release.set()
    await wait_for(lambda: not host._launchable_mru_peek_in_flight)
    assert peeks == 1
    # An unchanged token only advances the recompute counter.
    assert builds == []
    assert host._launchable_mru_tick_count == 1


async def test_launch_marks_pending_synchronously(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Submit flags the snapshot stale on the submit path, before the build."""
    from sase.ace.tui.actions.agent_workflow import _launch_submit_helpers

    seed_mru(tmp_path, monkeypatch, ["#git:foo"])
    monkeypatch.setattr(
        _launch_submit_helpers,
        "spawn_pump_free_task",
        lambda *a, **k: None,
    )
    host = StubHost()
    assert not host.peek_launchable_mru_snapshot().refresh_pending
    _launch_submit_helpers.schedule_submit_time_vcs_replay(host, ["hello"])
    assert host.peek_launchable_mru_snapshot().refresh_pending
