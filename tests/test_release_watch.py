from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone, UTC
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))

import _release_watch as watch  # noqa: E402
import _release_watch_engine as engine  # noqa: E402


UTC = UTC
NOW = datetime(2026, 10, 14, 12, tzinfo=UTC)
SHA = "a" * 40
OTHER_SHA = "b" * 40


def run(
    run_id: int = 1,
    *,
    sha: str = SHA,
    status: str = "completed",
    conclusion: str | None = "success",
    created: datetime = NOW - timedelta(hours=1),
    updated: datetime = NOW - timedelta(hours=1),
    jobs: tuple[tuple[str, str | None], ...] = (),
    excerpt: str = "",
    drift: bool = False,
) -> watch.WorkflowRun:
    return watch.WorkflowRun(
        run_id,
        sha,
        status,
        conclusion,
        created,
        updated,
        f"https://github.com/sase-org/sase/actions/runs/{run_id}",
        jobs,
        excerpt,
        drift,
    )


def pr(
    *,
    merged: datetime | None = None,
    floor: str = "success",
    head_created: datetime = NOW - timedelta(hours=2),
) -> watch.ReleasePullRequest:
    return watch.ReleasePullRequest(
        299,
        "chore: release 0.18.0",
        "MERGED" if merged else "OPEN",
        merged,
        "CLEAN",
        SHA,
        head_created,
        "https://github.com/sase-org/sase/pull/299",
        {"release-core-floor-smoke": floor},
    )


def snapshot(
    *,
    pypi: tuple[str, ...] = (),
    release_pr: watch.ReleasePullRequest | None = None,
    full: tuple[watch.WorkflowRun, ...] = (),
    publish: tuple[watch.WorkflowRun, ...] = (),
    core_upload: datetime = NOW - timedelta(hours=3),
) -> watch.Snapshot:
    return watch.Snapshot(
        pypi,
        release_pr,
        full,
        SHA,
        None,
        publish,
        "0.40.0",
        core_upload,
        "green",
    )


def options(tmp_path: Path, **overrides: Any) -> watch.WatchOptions:
    values: dict[str, Any] = {
        "repo": "sase-org/sase",
        "version": "0.18.0",
        "fixed_sha": SHA,
        "deadline": 3600,
        "poll": 60,
        "max_red_full_ci": 2,
        "verdict_file": str(tmp_path / "release_verdict.md"),
    }
    values.update(overrides)
    return watch.WatchOptions(**values)


def signal_values(
    *,
    release: watch.ReleasePullRequest | None = None,
    full: tuple[watch.WorkflowRun, ...] = (),
    publish: tuple[watch.WorkflowRun, ...] = (),
    pypi: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "pypi": pypi,
        "release_pr": release,
        "full_ci": full,
        "master_gate": (SHA, None),
        "publish": publish,
        "core_pypi": ("0.40.0", NOW - timedelta(hours=3)),
    }


class Reader:
    def __init__(self, values: dict[str, object] | None = None) -> None:
        self.values = values or signal_values(release=pr())
        self.reads = 0
        self.validation_error: Exception | None = None

    def validate(self) -> None:
        if self.validation_error:
            raise self.validation_error

    def read_signals(self) -> dict[str, object]:
        self.reads += 1
        return self.values


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


class FakeSignals:
    SIGTERM = 15
    SIGINT = 2
    SIGHUP = 1

    def __init__(self) -> None:
        self.handlers: dict[int, Any] = {}

    def getsignal(self, signum: int) -> Any:
        return self.handlers.get(signum)

    def signal(self, signum: int, handler: Any) -> None:
        self.handlers[signum] = handler


def fake_process(*, returncodes: list[int] | None = None):
    calls: list[tuple[list[str], dict[str, Any]]] = []
    codes = list(returncodes or [0])

    def process(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        code = codes.pop(0) if codes else 0
        return subprocess.CompletedProcess(argv, code, "", "failed" if code else "")

    return process, calls


def test_bad_run_shape_fails_closed_as_parse_error() -> None:
    with pytest.raises(ValueError, match="headSha"):
        watch.parse_run({"databaseId": 1, "status": "completed"}, "run")


def test_fixed_sha_containment_uses_compare_and_records_failed_jobs() -> None:
    class Gh:
        repo = "sase-org/sase"

        def json(self, *args: str) -> object:
            if args[:2] == ("run", "view"):
                return {"jobs": [{"name": "visual-test", "conclusion": "failure"}]}
            if args[0] == "api":
                sha = args[1].rsplit("...", 1)[-1]
                return {"status": "ahead" if sha == OTHER_SHA else "diverged"}
            raise AssertionError(args)

        def text(self, *args: str) -> str:
            return "PNG snapshot differs from the committed golden"

    reader = watch.GithubReader("sase-org/sase", "0.18.0", SHA, Gh())
    reader._run_list = lambda *_args, **_kwargs: [
        run(
            10, sha=OTHER_SHA, conclusion="failure", jobs=(("visual-test", "failure"),)
        ),
        run(11, sha="c" * 40, conclusion="failure"),
        run(12, sha=SHA, status="in_progress", conclusion=None),
    ]

    selected = reader.full_ci()

    assert {item.run_id for item in selected} == {10, 12}
    failed = next(item for item in selected if item.run_id == 10)
    assert failed.failed_jobs == ("visual-test",)
    assert failed.visual_golden_drift
    assert "PNG snapshot differs" in failed.failed_excerpt


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


def test_three_consecutive_malformed_reads_write_broken_verdict(tmp_path: Path) -> None:
    clock = FakeClock()
    values = signal_values(release=pr())
    values["pypi"] = watch.SignalFailure("pypi", "releases was not a list")

    class BrokenReader(Reader):
        def read_signals(self) -> dict[str, object]:
            self.reads += 1
            return values

    output: list[str] = []
    watcher = watch.ReleaseWatcher(
        options(tmp_path),
        BrokenReader(),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        output=output.append,
    )

    code = watcher.run()

    assert code == watch.EXIT_CODES["WATCHER_BROKEN"]
    assert watcher.reader.reads == 3
    assert "three consecutive failed reads" in watcher.final_detail
    assert (
        (tmp_path / "release_verdict.md")
        .read_text()
        .startswith("RELEASE NOT CONFIRMED: WATCHER_BROKEN")
    )


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


def test_deadline_and_startup_failure_verdicts(tmp_path: Path) -> None:
    clock = FakeClock()
    reader = Reader()
    process, _ = fake_process()
    deadline_watcher = watch.ReleaseWatcher(
        options(tmp_path, deadline=1),
        reader,
        process=process,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    assert deadline_watcher.run() == watch.EXIT_CODES["DEADLINE"]

    broken_reader = Reader()
    broken_reader.validation_error = RuntimeError("unknown workflow")
    broken = watch.ReleaseWatcher(options(tmp_path), broken_reader)
    assert broken.run() == watch.EXIT_CODES["WATCHER_BROKEN"]
    assert "startup validation failed" in broken.final_detail


def test_sigterm_writes_verdict_then_closes_bead(tmp_path: Path) -> None:
    clock = FakeClock()
    fake_signals = FakeSignals()
    process, calls = fake_process()
    output: list[str] = []

    def terminate(_seconds: float) -> None:
        fake_signals.handlers[fake_signals.SIGTERM](fake_signals.SIGTERM, None)

    watcher = watch.ReleaseWatcher(
        options(tmp_path, close_bead="sase-1kx.3"),
        Reader(
            signal_values(
                release=pr(), full=(run(70, status="in_progress", conclusion=None),)
            )
        ),
        process=process,
        monotonic=clock.monotonic,
        sleep=terminate,
        output=output.append,
        signal_module=fake_signals,
    )

    assert watcher.run() == watch.EXIT_CODES["DEADLINE"]
    assert calls[0][0][:6] == [
        "sase",
        "bead",
        "close",
        "sase-1kx.3",
        "-R",
        "canceled",
    ]
    assert "--note" in calls[0][0]
    assert "closed on attempt 1" in watcher.close_outcome
    assert (
        (tmp_path / "release_verdict.md")
        .read_text()
        .startswith("RELEASE NOT CONFIRMED: DEADLINE")
    )


def test_close_retries_three_times_and_waits_between_attempts(tmp_path: Path) -> None:
    process, calls = fake_process(returncodes=[1, 1, 0])
    sleeps: list[float] = []
    watcher = watch.ReleaseWatcher(
        options(tmp_path, close_bead="sase-1kx.3"),
        Reader(),
        process=process,
        sleep=sleeps.append,
        output=lambda _line: None,
    )
    watcher.set_verdict("DEADLINE", "time elapsed")

    code = watcher.finalize()

    assert code == watch.EXIT_CODES["DEADLINE"]
    assert len(calls) == 3
    assert sleeps == [30, 30]
    assert watcher.close_outcome == "closed on attempt 3"


def test_once_preflight_prints_one_state_and_close_argv_without_running_it(
    tmp_path: Path,
) -> None:
    output: list[str] = []
    process, calls = fake_process()
    reader = Reader(signal_values(release=pr()))
    watcher = watch.ReleaseWatcher(
        options(tmp_path, once=True, dry_run=True, close_bead="sase-1kx.3"),
        reader,
        process=process,
        output=output.append,
    )

    code = watcher.run()

    state_lines = [line for line in output if "stage=watch" in line]
    assert code == 0
    assert reader.reads == 1
    assert len(state_lines) == 1
    assert "would dispatch:full_ci" in state_lines[0]
    assert 'close_argv=["sase", "bead", "close", "sase-1kx.3"' in output[1]
    assert calls == []


def test_install_attempt_uses_fresh_venv_and_records_core_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[list[str]] = []

    def process(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(argv)
        if argv[-1] == "--version":
            stdout = "sase 0.18.0\n"
        elif "importlib.metadata" in argv[-1]:
            stdout = "0.40.1\n"
        else:
            stdout = ""
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    monkeypatch.setattr(
        engine.shutil, "which", lambda name: "/usr/bin/uv" if name == "uv" else None
    )
    watcher = watch.ReleaseWatcher(options(tmp_path), Reader(), process=process)

    success, detail = watcher.install_attempt(tmp_path / "new-venv")

    assert success
    assert "sase-core-rs=0.40.1" in detail
    assert commands[0][:2] == ["/usr/bin/uv", "venv"]
    assert commands[1][1:4] == ["pip", "install", "--refresh"]
    assert commands[2][-1] == "--version"
    assert commands[3][-1].startswith("import importlib.metadata")


def test_parse_arguments_rejects_bad_fixed_sha() -> None:
    with pytest.raises(watch.WatcherError, match="--fixed-sha"):
        watch.parse_args(["--fixed-sha", "bad"])
