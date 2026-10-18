"""CORE_CI_RED verdict, core-cut dispatch, and rendering tests for the watcher.

Shared builders live in ``tests._release_watch_helpers``.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from tests.test_release_watch_lifecycle import FakeSignals
from tests._release_watch_helpers import (
    CORE_SHA,
    NOW,
    FakeClock,
    Reader,
    core_check,
    core_pr,
    core_state,
    fake_process,
    options,
    pr,
    run,
    signal_values,
    snapshot,
    watch,
)

__all__ = [
    "test_core_ci_red_clock_restarts_on_new_head_and_when_checks_restart",
    "test_core_ci_red_needs_every_check_complete_and_awaiting_core",
    "test_core_ci_red_stops_after_the_grace_and_names_failing_checks",
    "test_core_cut_cap_and_cooldown",
    "test_core_cut_dispatch_command",
    "test_core_cut_gating",
    "test_core_cut_honors_no_dispatch_dry_run_and_once",
    "test_core_cut_failed_dispatch_is_not_counted",
    "test_core_pr_failed_read_is_watcher_broken_after_three",
    "test_core_pr_state_line_and_evidence",
    "test_run_loop_core_ci_red_closes_canceled",
    "test_once_preflight_reports_core_pr_and_would_dispatch_core_cut",
]

GRACE = 45 * 60
RED = (
    core_check("cargo fmt + clippy + test (ubuntu-latest)", "success"),
    core_check("cargo fmt + clippy + test (macos-latest)", "failure"),
)
GREEN = (core_check("fmt", "success"), core_check("macos", "success"))
PENDING = (core_check("fmt", "success"), core_check("macos", "pending"))


def awaiting(tmp_path: Path, **overrides: object) -> watch.WatchOptions:
    return options(tmp_path, await_core_version="0.42.0", **overrides)


def red_snapshot(*checks: watch.CoreCheck, head: str = CORE_SHA) -> watch.Snapshot:
    return snapshot(
        release_pr=pr(), core_release=core_state(core_pr(*checks, head_sha=head))
    )


def test_core_ci_red_stops_after_the_grace_and_names_failing_checks(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    watcher = watch.ReleaseWatcher(
        awaiting(tmp_path), Reader(), monotonic=clock.monotonic
    )
    snap = red_snapshot(*RED)

    assert watcher.evaluate(snap) is None  # the clock starts here
    clock.value = GRACE - 1
    assert watcher.evaluate(snap) is None
    clock.value = GRACE
    verdict = watcher.evaluate(snap)

    assert verdict is not None and verdict[0] == "CORE_CI_RED"
    detail = verdict[1]
    assert "#331" in detail and "pull/331" in detail and CORE_SHA in detail
    assert "45.0 minutes" in detail
    assert (
        "FAILED check: cargo fmt + clippy + test (macos-latest) "
        "https://github.com/sase-org/sase-core/actions/job/"
        "cargo-fmt-+-clippy-+-test-(macos-latest)"
    ) in detail
    assert "ubuntu" not in detail


def test_core_ci_red_clock_restarts_on_new_head_and_when_checks_restart(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    watcher = watch.ReleaseWatcher(
        awaiting(tmp_path), Reader(), monotonic=clock.monotonic
    )

    assert watcher.evaluate(red_snapshot(*RED)) is None
    clock.value = GRACE - 60
    # A new push restarts the clock even though the new head is red too.
    assert watcher.evaluate(red_snapshot(*RED, head="d" * 40)) is None
    clock.value = GRACE + 60
    assert watcher.evaluate(red_snapshot(*RED, head="d" * 40)) is None
    # A check starting again ends the all-completed condition and resets it.
    clock.value = GRACE + 120
    failing = (*RED, core_check("rerun", "pending"))
    assert watcher.evaluate(red_snapshot(*failing, head="d" * 40)) is None
    clock.value = 2 * GRACE + 60
    assert watcher.evaluate(red_snapshot(*RED, head="d" * 40)) is None
    clock.value = 3 * GRACE + 60
    result = watcher.evaluate(red_snapshot(*RED, head="d" * 40))
    assert result is not None and result[0] == "CORE_CI_RED"


@pytest.mark.parametrize(
    "case",
    ["pending", "failing", "green", "no_checks", "no_pr", "inactive", "core_arrived"],
)
def test_core_ci_red_needs_every_check_complete_and_awaiting_core(
    tmp_path: Path, case: str
) -> None:
    clock = FakeClock()
    watcher = watch.ReleaseWatcher(
        awaiting(tmp_path), Reader(), monotonic=clock.monotonic
    )
    core_version = "0.40.0"
    if case == "pending":
        core_release = core_state(core_pr(*PENDING))
    elif case == "failing":
        core_release = core_state(core_pr(*RED, core_check("late", "pending")))
    elif case == "green":
        core_release = core_state(core_pr(*GREEN))
    elif case == "no_checks":
        core_release = core_state(core_pr())
    elif case == "no_pr":
        core_release = core_state(None)
    elif case == "inactive":
        core_release = core_state(core_pr(*RED), active=False)
    else:
        core_release = core_state(core_pr(*RED))
        core_version = "0.42.0"
    snap = snapshot(
        release_pr=pr(), core_release=core_release, core_version=core_version
    )

    for seconds in (0, GRACE, 3 * GRACE):
        clock.value = seconds
        assert watcher.evaluate(snap) is None


def test_run_loop_core_ci_red_closes_canceled(tmp_path: Path) -> None:
    clock = FakeClock()
    output: list[str] = []
    process, calls = fake_process()
    reader = Reader(signal_values(release=pr(), core_release=core_state(core_pr(*RED))))
    watcher = watch.ReleaseWatcher(
        awaiting(tmp_path, close_bead="sase-1mk.8", deadline=6 * 3600),
        reader,
        process=process,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        output=output.append,
    )

    code = watcher.run()

    assert code == 19 == watch.EXIT_CODES["CORE_CI_RED"]
    assert watcher.final_verdict == "CORE_CI_RED"
    assert clock.value >= GRACE
    state_lines = [
        line for line in output if "stage=watch" in line and "\n" not in line
    ]
    assert f"core_pr=#331:v0.42.0:{CORE_SHA[:12]}:red" in state_lines[0]
    assert state_lines[-1].endswith("action=verdict:CORE_CI_RED")
    close = next(call[0] for call in calls if call[0][:3] == ["sase", "bead", "close"])
    assert close[3:5] == ["sase-1mk.8", "-R"]
    assert "release not confirmed: CORE_CI_RED" in close
    verdict = (tmp_path / "release_verdict.md").read_text()
    assert verdict.startswith("RELEASE NOT CONFIRMED: CORE_CI_RED")
    assert "- verdict: CORE_CI_RED (exit 19)" in verdict
    assert "  failing: cargo fmt + clippy + test (macos-latest) https://" in verdict
    assert (
        "- sase-core release PR: #331 https://github.com/sase-org/sase-core/pull/331"
        in verdict
    )


def test_core_pr_failed_read_is_watcher_broken_after_three(tmp_path: Path) -> None:
    clock = FakeClock()
    values = signal_values(release=pr())
    values["core_pr"] = watch.SignalFailure("core_pr", "found 2 open core release PRs")
    watcher = watch.ReleaseWatcher(
        awaiting(tmp_path),
        Reader(values),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        output=lambda _line: None,
    )

    code = watcher.run()

    assert code == watch.EXIT_CODES["WATCHER_BROKEN"]
    assert watcher.reader.reads == 3
    assert "core_pr: found 2 open core release PRs" in watcher.final_detail


def test_once_preflight_reports_core_pr_and_would_dispatch_core_cut(
    tmp_path: Path,
) -> None:
    output: list[str] = []
    process, calls = fake_process()
    reader = Reader(
        signal_values(release=pr(), core_release=core_state(core_pr(*PENDING)))
    )
    watcher = watch.ReleaseWatcher(
        awaiting(tmp_path, once=True, dry_run=True, dispatch_core_cut=True),
        reader,
        process=process,
        output=output.append,
        signal_module=FakeSignals(),
    )

    code = watcher.run()

    state_lines = [line for line in output if "stage=watch" in line]
    assert code == 0 and len(state_lines) == 1
    assert f"core_pr=#331:v0.42.0:{CORE_SHA[:12]}:pending" in state_lines[0]
    assert "awaiting_core" in state_lines[0]
    assert "would dispatch:core_cut" in state_lines[0]
    assert calls == []

    broken = Reader(
        signal_values(release=pr()) | {"core_pr": watch.SignalFailure("core_pr", "bad")}
    )
    failed = watch.ReleaseWatcher(
        awaiting(tmp_path, once=True, dry_run=True),
        broken,
        output=output.append,
    )
    assert failed.run() == watch.EXIT_CODES["WATCHER_BROKEN"]
    assert "core_pr (bad)" in failed.final_detail


def dispatch_watcher(
    tmp_path: Path, *, clock: FakeClock | None = None, **overrides: object
) -> tuple[watch.ReleaseWatcher, list[tuple[list[str], dict[str, object]]]]:
    process, calls = fake_process()
    clock = clock or FakeClock()
    watcher = watch.ReleaseWatcher(
        awaiting(tmp_path, dispatch_core_cut=True, **overrides),
        Reader(),
        process=process,
        monotonic=clock.monotonic,
        now=lambda: NOW,
    )
    return watcher, calls


def cut_snapshot(
    *checks: watch.CoreCheck, runs: tuple[watch.WorkflowRun, ...] = ()
) -> watch.Snapshot:
    fresh_full = run(5, updated=NOW)
    return snapshot(
        release_pr=pr(),
        full=(fresh_full,),
        core_release=core_state(core_pr(*checks), *runs),
    )


def test_core_cut_dispatch_command(tmp_path: Path) -> None:
    watcher, calls = dispatch_watcher(tmp_path)

    actions = watcher.dispatch_due(cut_snapshot(*GREEN))

    assert actions == ["dispatched:core_cut"]
    assert [call[0] for call in calls] == [
        [
            "gh",
            "workflow",
            "run",
            "release-plz.yml",
            "-R",
            "sase-org/sase-core",
            "--ref",
            "master",
            "-f",
            "dry_run=false",
        ]
    ]
    assert watcher.actions == ["dispatched:core_cut"]


def test_core_cut_gating(tmp_path: Path) -> None:
    window = timedelta(minutes=90)
    in_flight = run(7, status="in_progress", conclusion=None, event="push")
    recent_cut = run(
        8, created=NOW - window + timedelta(minutes=1), event="workflow_dispatch"
    )
    old_cut = run(
        9, created=NOW - window - timedelta(minutes=1), event="workflow_dispatch"
    )
    recent_schedule = run(10, created=NOW - timedelta(minutes=5), event="schedule")
    cases: list[tuple[str, watch.Snapshot, list[str]]] = [
        ("green", cut_snapshot(*GREEN), ["dispatched:core_cut"]),
        ("pending", cut_snapshot(*PENDING), ["dispatched:core_cut"]),
        (
            "old dispatch",
            cut_snapshot(*GREEN, runs=(old_cut,)),
            ["dispatched:core_cut"],
        ),
        (
            "scheduled run",
            cut_snapshot(*GREEN, runs=(recent_schedule,)),
            ["dispatched:core_cut"],
        ),
        ("failed check", cut_snapshot(*PENDING, core_check("x", "failure")), []),
        ("red", cut_snapshot(*RED), []),
        ("no checks", cut_snapshot(), []),
        ("release-plz in flight", cut_snapshot(*GREEN, runs=(in_flight,)), []),
        ("recent dispatch", cut_snapshot(*GREEN, runs=(recent_cut,)), []),
        (
            "no pr",
            snapshot(
                release_pr=pr(),
                full=(run(5, updated=NOW),),
                core_release=core_state(None),
            ),
            [],
        ),
        (
            "inactive",
            snapshot(
                release_pr=pr(),
                full=(run(5, updated=NOW),),
                core_release=core_state(core_pr(*GREEN), active=False),
            ),
            [],
        ),
        (
            "core published",
            snapshot(
                release_pr=pr(),
                full=(run(5, updated=NOW),),
                core_version="0.42.0",
                core_release=core_state(core_pr(*GREEN)),
            ),
            [],
        ),
        ("missing state", snapshot(release_pr=pr(), full=(run(5, updated=NOW),)), []),
    ]
    for name, snap, expected in cases:
        watcher, calls = dispatch_watcher(tmp_path)
        assert watcher.dispatch_due(snap) == expected, name
        assert len(calls) == len(expected), name

    opted_out = watch.ReleaseWatcher(
        awaiting(tmp_path), Reader(), process=fake_process()[0], now=lambda: NOW
    )
    assert opted_out.dispatch_due(cut_snapshot(*GREEN)) == []


def test_core_cut_cap_and_cooldown(tmp_path: Path) -> None:
    clock = FakeClock()
    watcher, calls = dispatch_watcher(tmp_path, clock=clock)
    snap = cut_snapshot(*GREEN)

    assert watcher.dispatch_due(snap) == ["dispatched:core_cut"]
    clock.value = 90 * 60 - 1
    assert watcher.dispatch_due(snap) == ["cooldown:core_cut"]
    assert len(calls) == 1
    for attempt in (2, 3):
        clock.value += 90 * 60
        assert watcher.dispatch_due(snap) == ["dispatched:core_cut"]
        assert len(calls) == attempt
    clock.value += 90 * 60
    assert watcher.dispatch_due(snap) == ["cap:core_cut"]
    assert len(calls) == 3
    assert watcher.actions.count("dispatched:core_cut") == 3
    assert watcher.actions[-1] == "cap:core_cut"


def test_core_cut_failed_dispatch_is_not_counted(tmp_path: Path) -> None:
    process, calls = fake_process(returncodes=[1, 1, 1, 0])
    clock = FakeClock()
    watcher = watch.ReleaseWatcher(
        awaiting(tmp_path, dispatch_core_cut=True),
        Reader(),
        process=process,
        monotonic=clock.monotonic,
        now=lambda: NOW,
    )
    snap = cut_snapshot(*GREEN)

    for _ in range(3):
        assert watcher.dispatch_due(snap) == ["dispatch_failed:core_cut:exit_1"]
    assert watcher.dispatch_due(snap) == ["dispatched:core_cut"]
    assert len(calls) == 4


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"no_dispatch": True}, []),
        ({"dry_run": True}, ["would dispatch:core_cut"]),
        ({"once": True}, ["would dispatch:core_cut"]),
    ],
)
def test_core_cut_honors_no_dispatch_dry_run_and_once(
    tmp_path: Path, overrides: dict[str, bool], expected: list[str]
) -> None:
    watcher, calls = dispatch_watcher(tmp_path, **overrides)

    assert watcher.dispatch_due(cut_snapshot(*GREEN)) == expected
    assert calls == []
    assert watcher._core_cut_dispatches == 0


def test_core_pr_state_line_and_evidence(tmp_path: Path) -> None:
    watcher = watch.ReleaseWatcher(awaiting(tmp_path), Reader())
    base = signal_values(release=pr())
    head = CORE_SHA[:12]
    cut = run(7, status="in_progress", conclusion=None, event="push")
    cases = [
        (None, "core_pr=off "),
        (core_state(None, active=False), "core_pr=off "),
        (core_state(None), "core_pr=none "),
        (core_state(core_pr(*GREEN)), f"core_pr=#331:v0.42.0:{head}:green "),
        (core_state(core_pr()), f"core_pr=#331:v0.42.0:{head}:no_checks "),
        (
            core_state(core_pr(*PENDING), cut),
            f"core_pr=#331:v0.42.0:{head}:pending:cut_in_flight ",
        ),
        (watch.SignalFailure("core_pr", "bad read"), "core_pr=ERROR:bad_read "),
    ]
    for value, fragment in cases:
        values = dict(base)
        if value is not None:
            values["core_pr"] = value
        assert fragment in watcher._render_state(values, "x"), fragment

    snap = cut_snapshot(*RED, runs=(cut,))
    watcher.last_snapshot = snap
    watcher.set_verdict("DEADLINE", "slow")
    block = watcher._evidence_block()
    assert (
        "- sase-core release PR: #331 https://github.com/sase-org/sase-core/pull/331"
        in block
    )
    assert "title='chore: release v0.42.0'" in block and "checks=red" in block
    assert "rollup: cargo fmt + clippy + test (macos-latest)=failure" in block
    assert "failing: cargo fmt + clippy + test (macos-latest) https://" in block
    assert "- sase-core Release-plz runs:" in block and "id=7 " in block
    assert snap.state_values("0.18.0")["core_pr"].endswith(":red:cut_in_flight")

    watcher.last_snapshot = snapshot(release_pr=pr())
    quiet = watcher._evidence_block()
    assert "sase-core release PR" not in quiet and "Release-plz" not in quiet
