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
    "test_full_ci_in_flight_status_suppresses_dispatch",
    "test_full_ci_red_budget_and_cooldown",
    "test_post_merge_publish_dispatch_is_deduplicated_by_run_creation",
    "test_prerelease_core_still_awaits",
    "test_reached_or_newer_core_restores_floor_blocked",
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
