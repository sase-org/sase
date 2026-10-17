"""Stale-head, PR-refresh, and compare-base tests for the release watcher.

Split from ``tests.test_release_watch_decisions``; shared builders live in
``tests._release_watch_helpers`` and the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

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
    "test_current_head_with_red_floor_still_blocked",
    "test_no_dispatch_suppresses_pr_refresh",
    "test_parse_compare_base_payload",
    "test_parse_compare_base_rejects_malformed",
    "test_pr_refresh_noop_guard_after_post_dispatch_publish",
    "test_stale_head_gives_no_verdict",
    "test_stale_head_pr_refresh_once_per_head_sha",
    "test_stale_state_line_and_deadline_detail",
]


BASE_SHA = "b" * 40
NEW_MASTER_SHA = "c" * 40


def stale_pr(
    *,
    merge_base: str = BASE_SHA,
    behind_by: int = 5,
    base_gate: str | None = "failure",
    head_created: datetime = NOW - timedelta(hours=1),
) -> watch.ReleasePullRequest:
    return pr(
        floor="failure",
        head_created=head_created,
        merge_base=merge_base,
        behind_by=behind_by,
        base_gate=base_gate,
    )


def stale_snapshot(**overrides: Any) -> watch.Snapshot:
    after_core = run(51, created=NOW - timedelta(hours=2), updated=NOW)
    flying = run(49, status="in_progress", conclusion=None)
    green_gate = run(81, conclusion="success")
    values: dict[str, Any] = {
        "release_pr": stale_pr(),
        "full": (flying,),
        "publish": (after_core,),
        "gate": green_gate,
    }
    values.update(overrides)
    return snapshot(**values)


def test_stale_head_gives_no_verdict(tmp_path: Path) -> None:
    watcher = watch.ReleaseWatcher(options(tmp_path), Reader())

    result = watcher.evaluate(stale_snapshot())

    assert result is None


def test_stale_head_pr_refresh_once_per_head_sha(tmp_path: Path) -> None:
    clock = FakeClock()
    clock.value = 100.0
    process, calls = fake_process()
    watcher = watch.ReleaseWatcher(
        options(tmp_path),
        Reader(),
        process=process,
        monotonic=clock.monotonic,
        now=lambda: NOW,
    )

    first = watcher.dispatch_due(stale_snapshot())

    assert first == ["dispatched:pr_refresh"]
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
    assert watcher.dispatch_due(stale_snapshot()) == []
    assert len(calls) == 1
    clock.value += 31 * 60
    moved = stale_snapshot(master_sha=NEW_MASTER_SHA)
    assert watcher.dispatch_due(moved) == ["dispatched:pr_refresh"]
    assert len(calls) == 2


def test_no_dispatch_suppresses_pr_refresh(tmp_path: Path) -> None:
    process, calls = fake_process()
    watcher = watch.ReleaseWatcher(
        options(tmp_path, no_dispatch=True),
        Reader(),
        process=process,
        monotonic=lambda: 100,
        now=lambda: NOW,
    )

    assert watcher.dispatch_due(stale_snapshot()) == []
    assert calls == []


def test_pr_refresh_noop_guard_after_post_dispatch_publish(tmp_path: Path) -> None:
    process, calls = fake_process()
    watcher = watch.ReleaseWatcher(
        options(tmp_path),
        Reader(),
        process=process,
        monotonic=lambda: 100,
        now=lambda: NOW,
    )

    assert watcher.dispatch_due(stale_snapshot()) == ["dispatched:pr_refresh"]
    assert len(calls) == 1
    finished_after = run(
        52, created=NOW + timedelta(minutes=1), updated=NOW + timedelta(minutes=2)
    )
    old_after_core = run(51, created=NOW - timedelta(hours=2), updated=NOW)
    guarded = stale_snapshot(publish=(finished_after, old_after_core))
    assert watcher.dispatch_due(guarded) == []
    assert len(calls) == 1


def test_current_head_with_red_floor_still_blocked(tmp_path: Path) -> None:
    watcher = watch.ReleaseWatcher(options(tmp_path), Reader())
    after_core = run(61, created=NOW - timedelta(hours=2), updated=NOW)
    current = pr(
        floor="failure",
        head_created=NOW - timedelta(hours=1),
        merge_base=SHA,
        behind_by=0,
        base_gate="failure",
    )

    result = watcher.evaluate(snapshot(release_pr=current, publish=(after_core,)))

    assert result is not None and result[0] == "CORE_FLOOR_BLOCKED"
    base_green = pr(
        floor="failure",
        head_created=NOW - timedelta(hours=1),
        merge_base=BASE_SHA,
        behind_by=3,
        base_gate="success",
    )
    green_result = watcher.evaluate(
        snapshot(release_pr=base_green, publish=(after_core,))
    )

    assert green_result is not None and green_result[0] == "CORE_FLOOR_BLOCKED"


def test_parse_compare_base_payload() -> None:
    merge_base, behind = watch.parse_compare_base(
        {
            "status": "behind",
            "behind_by": 7,
            "merge_base_commit": {"sha": BASE_SHA.upper()},
        },
        "compare test",
    )

    assert merge_base == BASE_SHA
    assert behind == 7
    with_diff = watch.parse_compare_base(
        {
            "status": "identical",
            "behind_by": 0,
            "merge_base_commit": {"sha": SHA},
        },
        "compare identical",
    )

    assert with_diff == (SHA, 0)


def test_parse_compare_base_rejects_malformed() -> None:
    with pytest.raises(ValueError, match="status"):
        watch.parse_compare_base({"status": "unknown"}, "compare bad")
    with pytest.raises(ValueError, match="behind_by"):
        watch.parse_compare_base(
            {
                "status": "behind",
                "behind_by": "7",
                "merge_base_commit": {"sha": SHA},
            },
            "compare bad",
        )
    with pytest.raises(ValueError, match="merge_base_commit"):
        watch.parse_compare_base({"status": "behind", "behind_by": 1}, "compare bad")


def test_stale_state_line_and_deadline_detail(tmp_path: Path) -> None:
    watcher = watch.ReleaseWatcher(options(tmp_path), Reader())
    values = {
        "pypi": (),
        "release_pr": stale_pr(),
        "full_ci": (),
        "master_gate": (SHA, run(81, conclusion="success")),
        "publish": (),
        "core_pypi": ("0.40.0", NOW - timedelta(hours=3)),
    }

    line = watcher._render_state(values, "reading")

    assert "release_pr=#299:open:stale" in line
    snap = stale_snapshot()
    detail = watcher._deadline_detail(snap)

    assert stale_pr().head_sha in detail
    assert BASE_SHA in detail
    assert "failure" in detail
