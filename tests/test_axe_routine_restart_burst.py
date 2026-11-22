"""Restart-burst guards: persisted routine cadence and a bounded tick.

A routine used to tick the moment its process started, so a service restart
or a code-swap restart re-ran all 13 housekeeping and all 20 external_mirror
jobs at once, and one tick ran every eligible job concurrently through an
unbounded thread pool. These tests pin the persisted cadence (a restarted
long-interval routine waits until it is due), the per-routine
``max_concurrent_jobs`` cap, longest-first dispatch, and the explicit
force-tick paths, using call counts and simulated clocks rather than wall time.
"""

from __future__ import annotations

import argparse
import threading
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.axe._config_targets import parse_lumberjacks
from sase.axe._config_types import (
    DEFAULT_ROUTINE_MAX_CONCURRENT_JOBS,
    AxeConfigDiagnostic,
    AxeConfigError,
)
from sase.axe.chop_runner_types import ChopRunOutcome
from sase.axe.config import AxeConfig, ChopConfig, LumberjackConfig
from sase.axe.lumberjack import Lumberjack
from sase.axe.routine_cadence import (
    PERSISTED_CADENCE_MIN_INTERVAL_SECONDS,
    first_tick_delay,
    read_last_tick_at,
    write_last_tick_at,
)
from sase.axe.state import ChopRunEntry, lumberjack_state_dir, write_chop_run
from sase.axe.tick_dispatch import dispatch_order
from sase.core.time import get_timezone

pytest_plugins = ("tests._axe_lumberjack_fixtures",)

_RUN_CHOP = "sase.axe._lumberjack_chop.run_configured_chop_once"
#: Hang guard only: no assertion depends on how long anything takes.
_HANG_GUARD_SECONDS = 10.0


def _routine(
    name: str,
    interval: int,
    jobs: int = 1,
    *,
    max_concurrent_jobs: int = DEFAULT_ROUTINE_MAX_CONCURRENT_JOBS,
) -> Lumberjack:
    config = LumberjackConfig(
        name=name,
        description="Restart-burst fixture",
        interval=interval,
        max_concurrent_jobs=max_concurrent_jobs,
        chops=[
            ChopConfig(name=f"job{index:02d}", description="") for index in range(jobs)
        ],
    )
    return Lumberjack(name, config, AxeConfig(query=""))


def _success(_routine_name: str, name: str) -> ChopRunOutcome:
    return ChopRunOutcome(
        lumberjack_name=_routine_name, chop_name=name, status="success"
    )


def _stub_success(**kwargs: Any) -> ChopRunOutcome:
    return _success(kwargs["lumberjack_name"], kwargs["chop"].name)


def _run_main_loop_once(routine: Lumberjack, *, tick_now: bool = False) -> MagicMock:
    """Drive ``Lumberjack.run`` through start-up and one loop pass.

    Returns the ``_run_tick`` mock so callers can see whether the start-up
    tick ran.
    """
    tick = MagicMock(name="_run_tick")

    def stop_after_first_pass(seconds: float) -> None:
        del seconds
        routine._running = False

    with (
        patch.object(routine, "_run_tick", tick),
        patch("sase.axe._lumberjack_core.os.chdir"),
        patch("sase.axe._lumberjack_core.signal.signal"),
        patch("sase.axe._lumberjack_core.init_telemetry"),
        patch("sase.axe._lumberjack_core.long_lived_swap_guard", return_value=None),
        patch(
            "sase.axe._lumberjack_core.time.sleep", side_effect=stop_after_first_pass
        ),
    ):
        assert routine.run(tick_now=tick_now) is True
    return tick


def _tick_job_next_run(routine: Lumberjack) -> datetime:
    jobs = [
        job
        for job in routine.scheduler.jobs
        if job.interval == routine.config.interval and job.next_run is not None
    ]
    assert jobs, "the routine tick job was not scheduled"
    return min(job.next_run for job in jobs if job.next_run is not None)


# --- persisted cadence -------------------------------------------------------


@pytest.mark.parametrize(
    ("interval", "last_tick_age", "expected"),
    [
        (3600, None, 0.0),  # nothing recorded: tick at once
        (3600, 10.0, 3590.0),  # restarted 10 s after a tick: wait until due
        (3600, 3600.0, 0.0),  # exactly due
        (3600, 7200.0, 0.0),  # overdue: tick at once
        (3600, -500.0, 3600.0),  # wall clock moved back: wait at most one interval
        (900, 300.0, 600.0),  # external_mirror
        (300, 299.0, 1.0),  # checks
        (60, 30.0, 30.0),  # the shortest persisted lane
        (30, 1.0, 0.0),  # short lanes keep ticking at start
        (5, 1.0, 0.0),
    ],
)
def test_first_tick_delay_waits_only_for_long_interval_routines_not_yet_due(
    interval: int, last_tick_age: float | None, expected: float
) -> None:
    now = 1_800_000_000.0
    last = None if last_tick_age is None else now - last_tick_age
    assert first_tick_delay(
        interval=interval, last_tick_at=last, now=now
    ) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("name", "interval", "jobs"),
    [("housekeeping", 3600, 13), ("external_mirror", 900, 20), ("checks", 300, 6)],
)
def test_a_restarted_routine_does_not_rerun_its_jobs_before_they_are_due(
    temp_state_dir: Path, name: str, interval: int, jobs: int
) -> None:
    del temp_state_dir
    before = _routine(name, interval, jobs)
    with patch(_RUN_CHOP, side_effect=_stub_success) as run_chop:
        before._run_tick()
    assert run_chop.call_count == jobs
    recorded = read_last_tick_at(name)
    assert recorded is not None

    # The service (or a code swap) restarts the routine shortly afterwards.
    restarted = _routine(name, interval, jobs)
    with patch(_RUN_CHOP, side_effect=_stub_success) as run_chop:
        tick = _run_main_loop_once(restarted)
    assert tick.call_count == 0
    assert run_chop.call_count == 0
    due = datetime.fromtimestamp(recorded + interval)
    assert abs((_tick_job_next_run(restarted) - due).total_seconds()) < 5


def test_a_routine_whose_last_tick_is_an_interval_old_ticks_at_start(
    temp_state_dir: Path,
) -> None:
    del temp_state_dir
    write_last_tick_at("housekeeping", started_at=time.time() - 3601, interval=3600)
    tick = _run_main_loop_once(_routine("housekeeping", 3600, 13))
    assert tick.call_count == 1


def test_tick_now_forces_the_start_up_tick_even_when_not_due(
    temp_state_dir: Path,
) -> None:
    del temp_state_dir
    write_last_tick_at("housekeeping", started_at=time.time(), interval=3600)
    tick = _run_main_loop_once(_routine("housekeeping", 3600, 13), tick_now=True)
    assert tick.call_count == 1


def test_an_explicit_tick_still_runs_every_job_when_the_cadence_is_not_due(
    temp_state_dir: Path,
) -> None:
    del temp_state_dir
    write_last_tick_at("housekeeping", started_at=time.time(), interval=3600)
    routine = _routine("housekeeping", 3600, 5)
    with patch(_RUN_CHOP, side_effect=_stub_success) as run_chop:
        routine._run_tick()
    assert run_chop.call_count == 5


def test_short_lanes_tick_at_start_and_write_no_cadence_file(
    temp_state_dir: Path,
) -> None:
    del temp_state_dir
    assert PERSISTED_CADENCE_MIN_INTERVAL_SECONDS == 60
    routine = _routine("hooks", 5, 2)
    with patch(_RUN_CHOP, side_effect=_stub_success):
        routine._run_tick()
    assert not (lumberjack_state_dir("hooks") / "cadence.json").exists()
    assert _run_main_loop_once(_routine("hooks", 5, 2)).call_count == 1


def test_a_corrupt_cadence_file_ticks_at_start(temp_state_dir: Path) -> None:
    del temp_state_dir
    path = lumberjack_state_dir("checks") / "cadence.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    for payload in ("{not json", '{"last_tick_at": "soon"}', '{"last_tick_at": -1}'):
        path.write_text(payload, encoding="utf-8")
        assert read_last_tick_at("checks") is None
        assert _run_main_loop_once(_routine("checks", 300, 2)).call_count == 1


def test_a_maintenance_skipped_tick_does_not_advance_the_cadence(
    temp_state_dir: Path,
) -> None:
    del temp_state_dir
    routine = _routine("housekeeping", 3600, 2)
    with (
        patch(
            "sase.axe._lumberjack_tick.read_maintenance",
            return_value={"reason": "upgrade", "pid": 1},
        ),
        patch(_RUN_CHOP, side_effect=_stub_success) as run_chop,
    ):
        routine._run_tick()
    assert run_chop.call_count == 0
    assert read_last_tick_at("housekeeping") is None


# --- bounded concurrency -----------------------------------------------------


class _ConcurrencyProbe:
    """Stub job runner that records the peak number of jobs running at once.

    The first ``cap`` callers wait until ``cap`` jobs run together, so the
    peak reaches the cap deterministically; the thread pool alone keeps it
    from going higher.
    """

    def __init__(self, cap: int) -> None:
        self._cap = cap
        self._lock = threading.Lock()
        self._full = threading.Event()
        self.active = 0
        self.peak = 0
        self.order: list[str] = []

    def __call__(self, **kwargs: Any) -> ChopRunOutcome:
        name = kwargs["chop"].name
        with self._lock:
            self.order.append(name)
            self.active += 1
            self.peak = max(self.peak, self.active)
            if self.active >= self._cap:
                self._full.set()
        self._full.wait(_HANG_GUARD_SECONDS)
        with self._lock:
            self.active -= 1
        return _success(kwargs["lumberjack_name"], name)


@pytest.mark.parametrize(("jobs", "cap"), [(13, 4), (20, 4), (6, 1), (3, 8)])
def test_one_tick_never_runs_more_jobs_at_once_than_the_cap(
    temp_state_dir: Path, jobs: int, cap: int
) -> None:
    del temp_state_dir
    routine = _routine("housekeeping", 3600, jobs, max_concurrent_jobs=cap)
    probe = _ConcurrencyProbe(min(cap, jobs))
    with patch(_RUN_CHOP, side_effect=probe):
        routine._run_tick()
    assert probe.peak == min(cap, jobs)
    assert sorted(probe.order) == [f"job{index:02d}" for index in range(jobs)]
    assert routine._metrics.chops_spawned == jobs


def test_routines_default_to_four_concurrent_jobs() -> None:
    raw = {
        "housekeeping": {"description": "Hourly", "interval": 3600},
        "external_mirror": {
            "description": "Mirrors",
            "interval": 900,
            "max_concurrent_jobs": 2,
        },
        "clamped": {"description": "Clamped", "max_concurrent_jobs": 0},
    }
    parsed = parse_lumberjacks(raw, project_target_rows=lambda: [])
    assert DEFAULT_ROUTINE_MAX_CONCURRENT_JOBS == 4
    assert parsed["housekeeping"].max_concurrent_jobs == 4
    assert parsed["external_mirror"].max_concurrent_jobs == 2
    assert parsed["clamped"].max_concurrent_jobs == 1


def test_the_bundled_config_sets_no_key_an_older_core_would_reject() -> None:
    # The cap's default lives in code: a sase_core_rs that predates the key
    # rejects it, and the bundled config must load on every supported core.
    bundled = Path(__file__).resolve().parents[1] / "src/sase/default_config.yml"
    assert "max_concurrent_jobs" not in bundled.read_text(encoding="utf-8")


def test_queued_jobs_never_start_after_a_shutdown_request(
    temp_state_dir: Path,
) -> None:
    del temp_state_dir
    routine = _routine("housekeeping", 3600, 5, max_concurrent_jobs=1)
    started: list[str] = []

    def first_job_requests_shutdown(**kwargs: Any) -> ChopRunOutcome:
        started.append(kwargs["chop"].name)
        routine._running = False
        return _success(kwargs["lumberjack_name"], kwargs["chop"].name)

    with patch(_RUN_CHOP, side_effect=first_job_requests_shutdown):
        routine._run_tick()
    # Jobs still queued for a slot return a shutdown skip instead of running.
    assert started == ["job00"]
    assert routine._metrics.chops_spawned == 1


# --- deterministic, longest-first dispatch ----------------------------------


def _chops(*names: str) -> list[ChopConfig]:
    return [ChopConfig(name=name, description="") for name in names]


def test_dispatch_order_is_longest_known_first_and_otherwise_config_order() -> None:
    chops = _chops("a", "b", "c", "d", "e")
    durations = {"c": 222.0, "e": 80.0, "a": 80.0, "b": -1.0}
    assert [chop.name for chop in dispatch_order(chops, durations)] == [
        "c",
        "a",
        "e",
        "b",
        "d",
    ]
    assert [chop.name for chop in dispatch_order(chops, {})] == list("abcde")


def _record_run(routine: str, job: str, *, seconds: float, status: str) -> None:
    now = datetime.now(get_timezone()).isoformat()
    write_chop_run(
        ChopRunEntry(
            run_id="20261121T000000_000001",
            lumberjack_name=routine,
            chop_name=job,
            started_at=now,
            finished_at=now,
            duration_ms=int(seconds * 1000),
            status=status,  # type: ignore[arg-type]
        )
    )


def test_a_restarted_tick_starts_its_longest_jobs_first_from_run_history(
    temp_state_dir: Path,
) -> None:
    del temp_state_dir
    _record_run("housekeeping", "job03", seconds=222.0, status="success")
    _record_run("housekeeping", "job01", seconds=80.0, status="failure")
    _record_run("housekeeping", "job04", seconds=999.0, status="skipped")
    routine = _routine("housekeeping", 3600, 5, max_concurrent_jobs=1)
    probe = _ConcurrencyProbe(1)
    with patch(_RUN_CHOP, side_effect=probe):
        routine._run_tick()
    assert probe.order == ["job03", "job01", "job00", "job02", "job04"]


def test_ticks_within_the_cap_never_read_run_history(temp_state_dir: Path) -> None:
    del temp_state_dir
    routine = _routine("checks", 300, 4, max_concurrent_jobs=4)
    with (
        patch("sase.axe._lumberjack_core.seed_durations") as seed,
        patch(_RUN_CHOP, side_effect=_stub_success),
    ):
        routine._run_tick()
        routine._run_tick()
    assert seed.call_count == 0


def test_run_history_is_read_once_per_routine_process(temp_state_dir: Path) -> None:
    del temp_state_dir
    routine = _routine("housekeeping", 3600, 6, max_concurrent_jobs=2)
    with (
        patch("sase.axe._lumberjack_core.seed_durations", return_value={}) as seed,
        patch(_RUN_CHOP, side_effect=_stub_success),
    ):
        routine._run_tick()
        routine._run_tick()
    assert seed.call_count == 1


# --- explicit force paths and diagnostics -----------------------------------


@pytest.fixture
def routine_cli() -> Iterator[MagicMock]:
    config = AxeConfig(
        lumberjacks={
            "housekeeping": LumberjackConfig(
                name="housekeeping",
                description="Hourly",
                interval=3600,
                chops=[ChopConfig(name="state_retention", description="Prune")],
            )
        }
    )
    routine = MagicMock()
    routine.run.return_value = True
    routine.swap_restart_requested = False
    with (
        patch("sase.axe.cli.load_axe_config", return_value=config),
        patch("sase.axe.lumberjack.Lumberjack", return_value=routine),
    ):
        yield routine


@pytest.mark.parametrize("tick_now", [False, True])
def test_routine_run_forwards_tick_now(routine_cli: MagicMock, tick_now: bool) -> None:
    from sase.axe.cli import handle_axe_lumberjack_run

    with pytest.raises(SystemExit):
        handle_axe_lumberjack_run(
            argparse.Namespace(lumberjack_name="housekeeping", tick_now=tick_now)
        )
    routine_cli.run.assert_called_once_with(tick_now=tick_now)


def test_routine_run_parser_accepts_tick_now() -> None:
    from sase.main.parser import create_parser

    args = create_parser().parse_args(["axe", "routine", "run", "housekeeping", "-t"])
    assert args.tick_now is True
    args = create_parser().parse_args(["axe", "routine", "run", "housekeeping"])
    assert args.tick_now is False


def test_a_stale_core_rejecting_the_routine_key_gets_a_rebuild_hint() -> None:
    diagnostic = AxeConfigDiagnostic(
        code="unknown_key",
        message="unknown config key `max_concurrent_jobs`",
        path="axe.routines.housekeeping.max_concurrent_jobs",
        layer="user",
    )
    message = str(AxeConfigError([diagnostic]))
    assert (
        "hint: this sase build advertises routine key 'max_concurrent_jobs'" in message
    )
    bogus = AxeConfigDiagnostic(
        code="unknown_key",
        message="unknown config key `max_concurrency`",
        path="axe.routines.housekeeping.max_concurrency",
    )
    assert "hint:" not in str(AxeConfigError([bogus]))
