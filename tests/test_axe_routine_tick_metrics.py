"""Routine-tick metric guards: an honest spawn rate and bounded skip records.

``spawn_rate_per_minute`` used to extrapolate the last tick x60 on lanes of 60 s
or longer, and every scheduled skip wrote a run-history entry, rewrote the index,
and pruned. These tests pin the rolling-window rate (correct per lane, decaying
between ticks) and the coalesced skip record with simulated clocks.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.axe import _state_chops
from sase.axe.chop_policy import ChopPreflight
from sase.axe.chop_runner_policy import record_preflight_outcome
from sase.axe.config import AxeConfig, LumberjackConfig, load_axe_config
from sase.axe.lumberjack import Lumberjack
from sase.axe.spawn_rate import spawn_rate_window_seconds
from sase.axe.state import (
    SKIP_COALESCE_SECONDS,
    ChopRunEntry,
    chop_runs_dir,
    coalesce_scheduled_skip,
    read_chop_run,
    read_chop_run_index,
    read_lumberjack_metrics,
    write_chop_run,
    write_lumberjack_metrics,
)
from sase.core.time import get_timezone

pytest_plugins = ("tests._axe_lumberjack_fixtures",)

_REASON = "watched paths unchanged and within max_quiet"


@pytest.fixture(autouse=True)
def _isolate_skip_streaks() -> Iterator[None]:
    """Keep the in-memory skip coalescer scoped to each test."""
    with _state_chops._SKIP_STREAKS_LOCK:
        _state_chops._SKIP_STREAKS.clear()
    yield
    with _state_chops._SKIP_STREAKS_LOCK:
        _state_chops._SKIP_STREAKS.clear()


def _routine(name: str, interval: int) -> Lumberjack:
    config = LumberjackConfig(
        name=name, description="Spawn-rate fixture", interval=interval, chops=[]
    )
    return Lumberjack(name, config, AxeConfig(query=""))


def _simulate(routine: Lumberjack, interval: int, spawns: int, ticks: int) -> float:
    """Tick on schedule from the routine's start; return the last tick time."""
    assert routine._metrics.spawn_rate_since is not None
    start = routine._metrics.spawn_rate_since + interval
    now = start
    for tick in range(ticks):
        now = start + tick * interval
        routine._record_tick_load(spawns=spawns, skipped=0, no_ops=0, now=now)
    return now


@pytest.mark.parametrize(
    ("interval", "spawns"),
    [(2, 1), (60, 1), (900, 20), (3600, 13)],
)
def test_spawn_rate_is_the_true_rate_for_every_lane_length(
    temp_state_dir: Path, interval: int, spawns: int
) -> None:
    del temp_state_dir
    routine = _routine(f"lane{interval}", interval)
    expected = spawns * 60.0 / interval

    # Honest from the first tick: no last-tick x60 extrapolation.
    since = routine._metrics.spawn_rate_since
    assert since is not None
    routine._record_tick_load(spawns=spawns, skipped=0, no_ops=0, now=since + interval)
    assert routine._metrics.spawn_rate_per_minute == pytest.approx(expected)

    window = spawn_rate_window_seconds(interval)
    ticks = int(window // interval) + 3
    routine = _routine(f"steady{interval}", interval)
    last = _simulate(routine, interval, spawns, ticks)
    write_lumberjack_metrics(routine.name, routine._metrics)
    mid = read_lumberjack_metrics(routine.name, now=last + interval / 2)
    assert mid is not None
    assert mid.spawn_rate_per_minute == pytest.approx(expected, rel=0.05)
    assert mid.spawn_window_seconds == window >= 300


def test_spawn_rate_decays_between_ticks_wherever_it_is_read(
    temp_state_dir: Path,
) -> None:
    del temp_state_dir
    routine = _routine("checks", 60)
    last = _simulate(routine, 60, 2, 10)
    write_lumberjack_metrics("checks", routine._metrics)

    def rate_at(offset: float) -> float:
        metrics = read_lumberjack_metrics("checks", now=last + offset)
        assert metrics is not None
        return metrics.spawn_rate_per_minute

    assert rate_at(30) == pytest.approx(2.0)
    assert 0 < rate_at(150) < rate_at(30)
    assert rate_at(301) == 0.0


def test_quiet_ticks_record_no_samples_and_the_window_stays_bounded(
    temp_state_dir: Path,
) -> None:
    del temp_state_dir
    routine = _routine("agent_waits", 2)
    _simulate(routine, 2, 0, 1000)
    assert routine._metrics.spawn_samples == []
    assert routine._metrics.spawn_rate_per_minute == 0.0
    _simulate(routine, 2, 1, 1000)
    assert len(routine._metrics.spawn_samples) <= 300 / 2 + 1


def _skip(now: datetime, *, reason: str = _REASON) -> str | None:
    return coalesce_scheduled_skip("hooks", "hook_checks", reason=reason, now=now)


def _write_skip(run_id: str, at: datetime, *, source: str = "scheduled") -> None:
    write_chop_run(
        ChopRunEntry(
            run_id=run_id,
            lumberjack_name="hooks",
            chop_name="hook_checks",
            started_at=at.isoformat(),
            finished_at=at.isoformat(),
            duration_ms=3,
            status="skipped",
            source=source,  # type: ignore[arg-type]
            reason=_REASON,
        ),
        output=f"Job skipped: {_REASON}\n",
    )


def test_repeat_skips_fold_into_one_record_refreshed_once_a_window(
    temp_state_dir: Path,
) -> None:
    del temp_state_dir
    start = datetime(2026, 11, 21, 12, 0, tzinfo=get_timezone())
    _write_skip("first", start)

    for step in range(1, 12):  # every 5 s for 55 s: in memory only
        assert _skip(start + timedelta(seconds=5 * step)) == "first"
    entry = read_chop_run("hooks", "hook_checks", "first")
    assert entry is not None
    assert entry.skip_count is None
    assert entry.finished_at == start.isoformat()

    flush_at = start + timedelta(seconds=SKIP_COALESCE_SECONDS)
    assert _skip(flush_at) == "first"
    entry = read_chop_run("hooks", "hook_checks", "first")
    assert entry is not None
    assert entry.skip_count == 13
    assert entry.finished_at == flush_at.isoformat()
    assert read_chop_run_index("hooks", "hook_checks") == ["first"]
    runs = sorted(p.name for p in chop_runs_dir("hooks", "hook_checks").iterdir())
    assert runs == ["first.json", "first.log"]


def test_a_new_reason_or_a_real_run_starts_a_fresh_skip_record(
    temp_state_dir: Path,
) -> None:
    del temp_state_dir
    start = datetime(2026, 11, 21, 12, 0, tzinfo=get_timezone())
    _write_skip("first", start)
    assert _skip(start, reason="agent_runners at max") is None

    _write_skip("manual", start, source="manual")
    assert _skip(start) is None

    assert coalesce_scheduled_skip("hooks", "other", reason=_REASON, now=start) is None


def test_scheduled_preflight_skips_stay_bounded_and_manual_skips_do_not_fold(
    temp_state_dir: Path,
) -> None:
    del temp_state_dir
    preflight = ChopPreflight(
        outcome="skip", reason=_REASON, decision={"provider": "fs"}
    )
    outcomes = [
        record_preflight_outcome(
            lumberjack_name="hooks",
            chop_name="hook_checks",
            run_id=f"20261121T1200{index:02d}_000000",
            started_at=datetime.now(get_timezone()),
            source="scheduled",
            started_by=None,
            preflight=preflight,
            chop_verbose=False,
        )
        for index in range(40)
    ]
    assert not outcomes[0].skip_coalesced
    assert all(o.skip_coalesced for o in outcomes[1:])
    assert {o.run_id for o in outcomes} == {outcomes[0].run_id}
    assert all(o.status == "skipped" and o.skip_reason == "trigger" for o in outcomes)
    assert len(read_chop_run_index("hooks", "hook_checks")) == 1

    manual = record_preflight_outcome(
        lumberjack_name="hooks",
        chop_name="hook_checks",
        run_id="20261121T130000_000000",
        started_at=datetime.now(get_timezone()),
        source="manual",
        started_by=None,
        preflight=preflight,
        chop_verbose=False,
    )
    assert not manual.skip_coalesced
    assert len(read_chop_run_index("hooks", "hook_checks")) == 2


@patch("sase.axe.chop_runner.stream_chop_script")
@patch("sase.axe.chop_runner.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_patches", return_value=[])
def test_idle_hooks_lane_counts_every_skip_but_keeps_history_bounded(
    _find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
) -> None:
    del temp_state_dir
    from tests._axe_lumberjack_fixtures import streamed_ok

    guarded = [
        chop
        for chop in load_axe_config().lumberjacks["hooks"].chops
        if chop.trigger.get("provider") == "fs" and chop.source == "builtin"
    ]
    config = LumberjackConfig(
        name="hooks", description="Idle fixture", interval=5, chops=guarded
    )
    mock_discover.return_value = Path("/fake/script")
    mock_run.side_effect = streamed_ok()
    routine = Lumberjack("hooks", config, AxeConfig(query=""))
    routine._run_tick()  # first tick fires every job
    for _ in range(6):
        routine._run_tick()

    assert routine._metrics.chops_skipped.get("trigger") == 6 * len(guarded)
    for chop in guarded:
        index = read_chop_run_index("hooks", chop.name)
        assert len(index) == 2  # the fire plus one folded skip record
