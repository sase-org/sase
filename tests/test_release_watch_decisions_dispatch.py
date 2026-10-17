"""Full-CI, publish, and floor-ratchet dispatch tests for the release watcher.

Split from ``tests.test_release_watch_decisions``; shared builders live in
``tests._release_watch_helpers`` and the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from tests._release_watch_helpers import (
    NOW,
    FakeClock,
    Reader,
    fake_process,
    options,
    pr,
    red_gate,
    run,
    snapshot,
    watch,
)

__all__ = [
    "test_awaiting_core_skips_floor_ratchet_keeps_full_ci",
    "test_dispatch_fresh_red_budget_with_two_old_reds",
    "test_first_full_ci_dispatch_and_exact_command",
    "test_floor_ratchet_dispatch_and_post_upload_deduplication",
    "test_fresh_red_budget_ignores_runs_predating_the_watch",
    "test_full_ci_in_flight_status_suppresses_dispatch",
    "test_full_ci_red_budget_and_cooldown",
    "test_no_dispatch_suppresses_dispatch_but_still_closes",
    "test_post_merge_publish_dispatch_is_deduplicated_by_run_creation",
    "test_stale_green_full_ci_refresh_requires_unmerged_pr",
]


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


def test_dispatch_fresh_red_budget_with_two_old_reds(tmp_path: Path) -> None:
    clock = FakeClock()
    watcher = watch.ReleaseWatcher(
        options(tmp_path, max_red_full_ci=2),
        Reader(),
        process=fake_process()[0],
        monotonic=clock.monotonic,
        now=lambda: NOW,
    )
    watcher._watch_started_at = NOW
    old_one = run(
        92,
        conclusion="failure",
        created=NOW - timedelta(hours=2),
        updated=NOW - timedelta(hours=1),
        jobs=(("tests", "failure"),),
        excerpt="FAILED: old one",
    )
    old_two = run(
        93,
        conclusion="failure",
        created=NOW - timedelta(hours=1),
        updated=NOW - timedelta(minutes=30),
        jobs=(("tests", "failure"),),
        excerpt="FAILED: old two",
    )

    actions = watcher.dispatch_due(snapshot(release_pr=pr(), full=(old_one, old_two)))

    assert actions == ["dispatched:full_ci"]
