"""Dispatch and evaluate tests for the release watcher.

Split from ``tests.test_release_watch``; shared builders live in
``tests._release_watch_helpers`` and the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from tests._release_watch_helpers import (
    NOW,
    SHA,
    FakeClock,
    Reader,
    fake_process,
    options,
    pr,
    run,
    snapshot,
    watch,
)

__all__ = [
    "test_all_signal_verdicts",
    "test_awaiting_core_skips_floor_ratchet_keeps_full_ci",
    "test_awaiting_core_suppresses_floor_blocked",
    "test_first_full_ci_dispatch_and_exact_command",
    "test_floor_blocked_requires_failed_floor_after_publish_after_core",
    "test_floor_ratchet_dispatch_and_post_upload_deduplication",
    "test_fresh_red_budget_ignores_runs_predating_the_watch",
    "test_full_ci_in_flight_status_suppresses_dispatch",
    "test_full_ci_red_budget_and_cooldown",
    "test_master_gate_green_resets_red_clock",
    "test_master_gate_in_flight_neither_counts_nor_resets",
    "test_master_gate_red_after_budget_without_green",
    "test_master_gate_rerun_fires_once_per_sha_for_test_shards_only",
    "test_master_gate_sha_change_restarts_red_clock",
    "test_no_dispatch_suppresses_dispatch_but_still_closes",
    "test_post_merge_publish_dispatch_is_deduplicated_by_run_creation",
    "test_prerelease_core_still_awaits",
    "test_reached_or_newer_core_restores_floor_blocked",
    "test_stale_green_full_ci_refresh_requires_unmerged_pr",
]


def red_gate(
    run_id: int = 80,
    *,
    status: str = "completed",
    conclusion: str | None = "failure",
    jobs: tuple[tuple[str, str | None], ...] = (("test (1, 8)", "failure"),),
) -> watch.WorkflowRun:
    return run(
        run_id,
        status=status,
        conclusion=conclusion,
        jobs=jobs,
        excerpt="FAILED: flaky shard",
    )


@pytest.mark.parametrize("status", sorted(watch.IN_FLIGHT))
def test_full_ci_in_flight_status_suppresses_dispatch(
    tmp_path: Path, status: str
) -> None:
    process, calls = fake_process()
    watcher = watch.ReleaseWatcher(
        options(tmp_path),
        Reader(),
        process=process,
        monotonic=lambda: 100,
    )

    actions = watcher.dispatch_due(
        snapshot(release_pr=pr(), full=(run(status=status, conclusion=None),))
    )

    assert actions == []
    assert calls == []


def test_first_full_ci_dispatch_and_exact_command(tmp_path: Path) -> None:
    process, calls = fake_process()
    watcher = watch.ReleaseWatcher(
        options(tmp_path),
        Reader(),
        process=process,
        monotonic=lambda: 100,
    )

    actions = watcher.dispatch_due(snapshot(release_pr=pr()))

    assert actions == ["dispatched:full_ci"]
    assert calls[0][0] == [
        "gh",
        "workflow",
        "run",
        "full.yml",
        "-R",
        "sase-org/sase",
        "--ref",
        "master",
    ]


def test_full_ci_red_budget_and_cooldown(tmp_path: Path) -> None:
    process, calls = fake_process()
    watcher = watch.ReleaseWatcher(
        options(tmp_path),
        Reader(),
        process=process,
        monotonic=lambda: 10,
    )
    one_red = run(
        20,
        conclusion="failure",
        jobs=(("tests", "failure"),),
        excerpt="FAILED: assertion",
    )

    assert watcher.dispatch_due(snapshot(release_pr=pr(), full=(one_red,))) == [
        "dispatched:full_ci"
    ]
    assert len(calls) == 1
    watcher.last_dispatch["full_ci"] = 10
    assert watcher.dispatch_due(snapshot(release_pr=pr(), full=(one_red,))) == [
        "cooldown:full_ci"
    ]
    assert len(calls) == 1
    two_red = (one_red, run(21, conclusion="failure", updated=NOW))
    assert watcher.dispatch_due(snapshot(release_pr=pr(), full=two_red)) == []


def test_stale_green_full_ci_refresh_requires_unmerged_pr(tmp_path: Path) -> None:
    process, calls = fake_process()
    watcher = watch.ReleaseWatcher(
        options(tmp_path),
        Reader(),
        process=process,
        monotonic=lambda: 100,
        now=lambda: NOW,
    )
    stale_green = run(30, updated=NOW - timedelta(hours=5))

    assert watcher.dispatch_due(snapshot(release_pr=pr(), full=(stale_green,))) == [
        "dispatched:full_ci"
    ]
    assert len(calls) == 1
    merged_at = NOW - timedelta(hours=1)
    after_merge = run(31, created=merged_at + timedelta(minutes=1), updated=NOW)
    assert (
        watcher.dispatch_due(
            snapshot(
                release_pr=pr(merged=merged_at),
                full=(stale_green,),
                publish=(after_merge,),
            )
        )
        == []
    )


def test_post_merge_publish_dispatch_is_deduplicated_by_run_creation(
    tmp_path: Path,
) -> None:
    process, calls = fake_process()
    watcher = watch.ReleaseWatcher(
        options(tmp_path),
        Reader(),
        process=process,
        monotonic=lambda: 100,
    )
    merged_at = NOW - timedelta(minutes=10)
    merged_pr = pr(merged=merged_at)

    in_flight = run(39, status="in_progress", conclusion=None)
    assert watcher.dispatch_due(snapshot(release_pr=merged_pr, full=(in_flight,))) == [
        "dispatched:release_publish"
    ]
    assert calls[0][0] == [
        "gh",
        "workflow",
        "run",
        "publish.yml",
        "-R",
        "sase-org/sase",
        "--ref",
        "master",
        "-f",
        "publish_existing=false",
    ]
    after_merge = run(40, created=NOW, updated=NOW)
    assert (
        watcher.dispatch_due(
            snapshot(release_pr=merged_pr, full=(in_flight,), publish=(after_merge,))
        )
        == []
    )


def test_floor_ratchet_dispatch_and_post_upload_deduplication(tmp_path: Path) -> None:
    process, calls = fake_process()
    watcher = watch.ReleaseWatcher(
        options(tmp_path),
        Reader(),
        process=process,
        monotonic=lambda: 100,
    )
    floor_pr = pr(floor="failure")

    in_flight = run(49, status="in_progress", conclusion=None)
    assert watcher.dispatch_due(snapshot(release_pr=floor_pr, full=(in_flight,))) == [
        "dispatched:floor_ratchet"
    ]
    assert len(calls) == 1
    after_core = run(50, created=NOW - timedelta(hours=2), updated=NOW)
    assert (
        watcher.dispatch_due(
            snapshot(release_pr=floor_pr, full=(in_flight,), publish=(after_core,))
        )
        == []
    )


def test_floor_blocked_requires_failed_floor_after_publish_after_core() -> None:
    publish_after_core = run(51, created=NOW - timedelta(hours=2), updated=NOW)
    blocked_pr = pr(floor="failure", head_created=NOW - timedelta(hours=1))
    watcher = watch.ReleaseWatcher(options(Path("/tmp")), Reader())

    result = watcher.evaluate(
        snapshot(release_pr=blocked_pr, publish=(publish_after_core,))
    )

    assert result is not None and result[0] == "CORE_FLOOR_BLOCKED"


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("released", "RELEASED"),
        ("install_failed", "INSTALL_FAILED"),
        ("gone", "RELEASE_PR_GONE"),
        ("publish_failed", "PUBLISH_FAILED"),
        ("core_floor", "CORE_FLOOR_BLOCKED"),
        ("full_ci_red", "FULL_CI_RED"),
    ],
)
def test_all_signal_verdicts(case: str, expected: str, tmp_path: Path) -> None:
    watcher = watch.ReleaseWatcher(options(tmp_path), Reader())
    if case in {"released", "install_failed"}:
        values = snapshot(pypi=("0.18.0",), release_pr=pr())
        watcher.install_proof = lambda: (case == "released", "proof detail")
    elif case == "gone":
        values = snapshot(release_pr=None)
    elif case == "publish_failed":
        merged = pr(merged=NOW - timedelta(hours=2))
        failed_pub = run(60, created=NOW - timedelta(hours=1), conclusion="failure")
        values = snapshot(release_pr=merged, publish=(failed_pub,))
    elif case == "core_floor":
        after_core = run(61, created=NOW - timedelta(hours=2), updated=NOW)
        values = snapshot(
            release_pr=pr(floor="failure", head_created=NOW - timedelta(hours=1)),
            publish=(after_core,),
        )
    else:
        red = run(
            62,
            conclusion="failure",
            jobs=(("lint", "failure"),),
            excerpt="FAILED: lint",
        )
        values = snapshot(release_pr=pr(), full=(red,))

    result = watcher.evaluate(values)

    assert result is not None and result[0] == expected


def test_awaiting_core_suppresses_floor_blocked(tmp_path: Path) -> None:
    watcher = watch.ReleaseWatcher(
        options(tmp_path, await_core_version="0.40.0"), Reader()
    )
    after_core = run(51, created=NOW - timedelta(hours=2), updated=NOW)
    blocked_pr = pr(floor="failure", head_created=NOW - timedelta(hours=1))

    result = watcher.evaluate(
        snapshot(
            release_pr=blocked_pr,
            publish=(after_core,),
            core_version="0.39.1",
        )
    )

    assert result is None


@pytest.mark.parametrize("core_version", ["0.40.0", "0.40.1"])
def test_reached_or_newer_core_restores_floor_blocked(
    tmp_path: Path, core_version: str
) -> None:
    watcher = watch.ReleaseWatcher(
        options(tmp_path, await_core_version="0.40.0"), Reader()
    )
    after_core = run(51, created=NOW - timedelta(hours=2), updated=NOW)
    blocked_pr = pr(floor="failure", head_created=NOW - timedelta(hours=1))

    result = watcher.evaluate(
        snapshot(
            release_pr=blocked_pr,
            publish=(after_core,),
            core_version=core_version,
        )
    )

    assert result is not None and result[0] == "CORE_FLOOR_BLOCKED"


def test_prerelease_core_still_awaits(tmp_path: Path) -> None:
    watcher = watch.ReleaseWatcher(
        options(tmp_path, await_core_version="0.40.0"), Reader()
    )
    after_core = run(51, created=NOW - timedelta(hours=2), updated=NOW)
    result = watcher.evaluate(
        snapshot(
            release_pr=pr(floor="failure", head_created=NOW - timedelta(hours=1)),
            publish=(after_core,),
            core_version="0.40.0rc1",
        )
    )
    assert result is None


def test_awaiting_core_skips_floor_ratchet_keeps_full_ci(tmp_path: Path) -> None:
    process, calls = fake_process()
    watcher = watch.ReleaseWatcher(
        options(tmp_path, await_core_version="0.40.0"),
        Reader(),
        process=process,
        monotonic=lambda: 100,
    )
    floor_pr = pr(floor="failure")
    in_flight = run(49, status="in_progress", conclusion=None)

    assert (
        watcher.dispatch_due(
            snapshot(
                release_pr=floor_pr,
                full=(in_flight,),
                core_version="0.39.1",
            )
        )
        == []
    )
    assert calls == []
    assert watcher.dispatch_due(
        snapshot(release_pr=floor_pr, core_version="0.39.1")
    ) == ["dispatched:full_ci"]
    assert len(calls) == 1
    assert calls[0][0] == [
        "gh",
        "workflow",
        "run",
        "full.yml",
        "-R",
        "sase-org/sase",
        "--ref",
        "master",
    ]


def gate_watcher(tmp_path: Path, clock: FakeClock) -> watch.ReleaseWatcher:
    return watch.ReleaseWatcher(
        options(tmp_path, max_red_gate_minutes=120.0),
        Reader(),
        process=fake_process()[0],
        monotonic=clock.monotonic,
        now=lambda: NOW,
    )


def test_master_gate_red_after_budget_without_green(tmp_path: Path) -> None:
    clock = FakeClock()
    watcher = gate_watcher(tmp_path, clock)
    red = snapshot(release_pr=pr(), gate=red_gate())

    assert watcher.evaluate(red) is None
    clock.value += 119 * 60
    assert watcher.evaluate(red) is None
    clock.value += 61
    result = watcher.evaluate(red)

    assert result is not None and result[0] == "MASTER_GATE_RED"
    assert "80" in result[1]


def test_master_gate_green_resets_red_clock(tmp_path: Path) -> None:
    clock = FakeClock()
    watcher = gate_watcher(tmp_path, clock)
    red = snapshot(release_pr=pr(), gate=red_gate())
    green = snapshot(release_pr=pr(), gate=run(81))

    assert watcher.evaluate(red) is None
    clock.value += 100 * 60
    assert watcher.evaluate(green) is None
    clock.value += 100 * 60
    assert watcher.evaluate(red) is None


def test_master_gate_in_flight_neither_counts_nor_resets(tmp_path: Path) -> None:
    clock = FakeClock()
    watcher = gate_watcher(tmp_path, clock)
    red = snapshot(release_pr=pr(), gate=red_gate())
    flying = snapshot(
        release_pr=pr(),
        gate=red_gate(82, status="in_progress", conclusion=None),
    )

    assert watcher.evaluate(red) is None
    clock.value += 100 * 60
    assert watcher.evaluate(flying) is None
    clock.value += 21 * 60
    result = watcher.evaluate(red)

    assert result is not None and result[0] == "MASTER_GATE_RED"


def test_master_gate_sha_change_restarts_red_clock(tmp_path: Path) -> None:
    clock = FakeClock()
    watcher = gate_watcher(tmp_path, clock)
    other_sha = "b" * 40

    assert watcher.evaluate(snapshot(release_pr=pr(), gate=red_gate())) is None
    clock.value += 100 * 60
    moved = snapshot(release_pr=pr(), gate=red_gate(), master_sha=other_sha)
    assert watcher.evaluate(moved) is None
    clock.value += 100 * 60
    assert watcher.evaluate(moved) is None


def test_master_gate_rerun_fires_once_per_sha_for_test_shards_only(
    tmp_path: Path,
) -> None:
    process, calls = fake_process()
    watcher = watch.ReleaseWatcher(
        options(tmp_path),
        Reader(),
        process=process,
        monotonic=lambda: 100,
    )
    gate_snapshot = snapshot(release_pr=pr(), gate=red_gate())

    assert watcher.dispatch_due(gate_snapshot) == [
        "dispatched:full_ci",
        "dispatched:master_gate_rerun",
    ]
    assert calls[1][0] == [
        "gh",
        "run",
        "rerun",
        "80",
        "--failed",
        "-R",
        "sase-org/sase",
    ]
    assert watcher.dispatch_due(gate_snapshot) == ["cooldown:full_ci"]

    lint_gate = snapshot(
        release_pr=pr(), gate=red_gate(83, jobs=(("lint", "failure"),))
    )
    fresh = watch.ReleaseWatcher(
        options(tmp_path),
        Reader(),
        process=fake_process()[0],
        monotonic=lambda: 100,
    )
    assert fresh.dispatch_due(lint_gate) == ["dispatched:full_ci"]


def test_fresh_red_budget_ignores_runs_predating_the_watch(tmp_path: Path) -> None:
    clock = FakeClock()
    watcher = watch.ReleaseWatcher(
        options(tmp_path, max_red_full_ci=1),
        Reader(),
        process=fake_process()[0],
        monotonic=clock.monotonic,
        now=lambda: NOW,
    )
    watcher._watch_started_at = NOW
    stale = run(
        90,
        conclusion="failure",
        created=NOW - timedelta(hours=1),
        updated=NOW - timedelta(minutes=30),
        jobs=(("tests", "failure"),),
        excerpt="FAILED: stale",
    )
    assert watcher.evaluate(snapshot(release_pr=pr(), full=(stale,))) is None
    fresh_red = run(
        91,
        conclusion="failure",
        created=NOW + timedelta(minutes=1),
        updated=NOW + timedelta(minutes=1),
        jobs=(("tests", "failure"),),
        excerpt="FAILED: fresh",
    )
    result = watcher.evaluate(snapshot(release_pr=pr(), full=(fresh_red,)))
    assert result is not None and result[0] == "FULL_CI_RED"


def test_no_dispatch_suppresses_dispatch_but_still_closes(tmp_path: Path) -> None:
    process, calls = fake_process()
    watcher = watch.ReleaseWatcher(
        options(tmp_path, no_dispatch=True, close_bead="sase-1lh.5"),
        Reader(),
        process=process,
        monotonic=lambda: 100,
        output=lambda _line: None,
    )

    assert watcher.dispatch_due(snapshot(release_pr=pr())) == []
    assert watcher.dispatch_due(snapshot(release_pr=pr(), gate=red_gate())) == []
    assert calls == []
    watcher.set_verdict("DEADLINE", "time elapsed")

    assert watcher.finalize() == watch.EXIT_CODES["DEADLINE"]
    assert watcher.close_outcome == "closed on attempt 1"
