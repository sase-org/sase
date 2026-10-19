"""Shared builders for release-watch tests.

Split from ``tests.test_release_watch``. Every helper defined here carries a
public name so the sibling ``test_release_watch_*`` modules can import it
without a ``_``-private cross-module import.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))

import _release_watch as watch  # noqa: E402
import _release_watch_api as watch_api  # noqa: E402
import _release_watch_engine as engine  # noqa: E402

NOW = datetime(2026, 10, 14, 12, tzinfo=UTC)
SHA = "a" * 40
CORE_SHA = "c" * 40

__all__ = [
    "CORE_SHA",
    "FakeClock",
    "FakeSignals",
    "NOW",
    "SHA",
    "UTC",
    "Reader",
    "core_check",
    "core_pr",
    "core_state",
    "engine",
    "fake_process",
    "options",
    "pr",
    "red_gate",
    "run",
    "run_payload",
    "signal_values",
    "snapshot",
    "watch",
    "watch_api",
]


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


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


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
    event: str = "",
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
        event,
    )


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


def pr(
    *,
    merged: datetime | None = None,
    floor: str = "success",
    head_created: datetime = NOW - timedelta(hours=2),
    head_sha: str = SHA,
    merge_base: str | None = None,
    behind_by: int = 0,
    base_gate: str | None = None,
) -> watch.ReleasePullRequest:
    return watch.ReleasePullRequest(
        299,
        "chore: release 0.18.0",
        "MERGED" if merged else "OPEN",
        merged,
        "CLEAN",
        head_sha,
        head_created,
        "https://github.com/sase-org/sase/pull/299",
        {"release-core-floor-smoke": floor},
        merge_base,
        behind_by,
        base_gate,
    )


def core_check(
    name: str = "cargo fmt + clippy + test (macos-latest)",
    status: str = "failure",
) -> watch.CoreCheck:
    slug = name.replace(" ", "-")
    return watch.CoreCheck(
        name, status, f"https://github.com/sase-org/sase-core/actions/job/{slug}"
    )


def core_pr(
    *checks: watch.CoreCheck, head_sha: str = CORE_SHA
) -> watch.CoreReleasePullRequest:
    return watch.CoreReleasePullRequest(
        331,
        "chore: release v0.42.0",
        "0.42.0",
        head_sha,
        "https://github.com/sase-org/sase-core/pull/331",
        checks,
    )


def core_state(
    pr: watch.CoreReleasePullRequest | None = None,
    *runs: watch.WorkflowRun,
    active: bool = True,
) -> watch.CoreReleaseState:
    return watch.CoreReleaseState(active, pr, runs)


def snapshot(
    *,
    pypi: tuple[str, ...] = (),
    release_pr: watch.ReleasePullRequest | None = None,
    full: tuple[watch.WorkflowRun, ...] = (),
    publish: tuple[watch.WorkflowRun, ...] = (),
    core_version: str = "0.40.0",
    core_upload: datetime = NOW - timedelta(hours=3),
    gate: watch.WorkflowRun | None = None,
    master_sha: str = SHA,
    core_release: watch.CoreReleaseState | None = None,
) -> watch.Snapshot:
    return watch.Snapshot(
        pypi,
        release_pr,
        full,
        master_sha,
        gate,
        publish,
        core_version,
        core_upload,
        "green",
        core_release,
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
    core: tuple[str, datetime] = ("0.40.0", NOW - timedelta(hours=3)),
    core_release: watch.CoreReleaseState | None = None,
) -> dict[str, object]:
    values: dict[str, object] = {
        "pypi": pypi,
        "release_pr": release,
        "full_ci": full,
        "master_gate": (SHA, None),
        "publish": publish,
        "core_pypi": core,
    }
    if core_release is not None:
        values["core_pr"] = core_release
    return values


def run_payload(
    *,
    status: str = "completed",
    conclusion: object = "success",
    run_id: int = 1,
) -> dict[str, object]:
    return {
        "databaseId": run_id,
        "headSha": SHA,
        "status": status,
        "conclusion": conclusion,
        "createdAt": "2026-10-14T12:00:00Z",
        "updatedAt": "2026-10-14T12:00:00Z",
        "url": f"https://github.com/sase-org/sase/actions/runs/{run_id}",
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


def fake_process(*, returncodes: list[int] | None = None):
    calls: list[tuple[list[str], dict[str, Any]]] = []
    codes = list(returncodes or [0])

    def process(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        code = codes.pop(0) if codes else 0
        return subprocess.CompletedProcess(argv, code, "", "failed" if code else "")

    return process, calls
