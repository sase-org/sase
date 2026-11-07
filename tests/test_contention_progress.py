"""The contention soak's live progress records and kill audit.

These are read by the sampler while a soak may be dying, so they must be
written as whole records, stay bounded, reach workers without reaching the
pytest subprocesses tests spawn, and never change what a test does. The kill
audit is exercised by calling the hook directly: no test here sends a signal.
"""

from __future__ import annotations

import json
import os
import signal
import sys
from pathlib import Path
from typing import Any

import pytest

from tests._contention import (
    CONTROLLER_PROGRESS_FILENAME,
    DIAGNOSTICS_ENV,
    KILLS_FILENAME,
    read_json,
)
from tests._contention_progress import (
    CONTROLLER_PLUGIN_NAME,
    KILL_RECORD_LIMIT,
    WORKER_PLUGIN_NAME,
    WORKERINPUT_KEY,
    ControllerProgress,
    KillAudit,
    WorkerProgress,
    register_controller_progress,
    register_worker_progress,
)


class _Node:
    def __init__(self, worker_id: str) -> None:
        self.workerinput: dict[str, Any] = {"workerid": worker_id}


class _Report:
    def __init__(self, *, failed: bool) -> None:
        self.failed = failed


class _Manager:
    def __init__(self) -> None:
        self.registered: list[tuple[object, str]] = []

    def register(self, plugin: object, name: str) -> None:
        self.registered.append((plugin, name))


class _Config:
    def __init__(self, workerinput: dict[str, Any] | None = None) -> None:
        self.pluginmanager = _Manager()
        if workerinput is not None:
            self.workerinput = workerinput


def test_controller_records_workers_collection_boundary_and_progress(
    tmp_path: Path,
) -> None:
    progress = ControllerProgress(tmp_path)
    node = _Node("gw0")

    progress.pytest_configure_node(node)
    progress.pytest_sessionstart()
    progress.pytest_xdist_node_collection_finished(node, ["a", "b", "c"])
    progress.pytest_runtest_logstart("tests/t.py::test_a")
    progress.pytest_runtest_logstart("tests/t.py::test_b")
    progress.pytest_runtest_logfinish("tests/t.py::test_a")
    progress.pytest_runtest_logreport(_Report(failed=True))  # type: ignore[arg-type]
    progress.pytest_sessionfinish(1)

    # The directory reaches workers through workerinput, never the environment.
    assert node.workerinput[WORKERINPUT_KEY] == str(tmp_path)
    record = read_json(tmp_path / CONTROLLER_PROGRESS_FILENAME)
    assert record is not None
    assert record["workers_configured"] == 1
    assert record["collection"]["workers_finished"] == 1
    assert record["collection"]["items"] == 3
    assert (record["started"], record["finished"], record["failed_reports"]) == (
        2,
        1,
        1,
    )
    assert [item["nodeid"] for item in record["inflight"]] == ["tests/t.py::test_b"]
    assert record["recent"] == ["tests/t.py::test_a"]
    assert record["exitstatus"] == 1


def test_worker_record_marks_a_finished_node_idle(tmp_path: Path) -> None:
    progress = WorkerProgress(tmp_path, "gw2")
    path = tmp_path / "worker-gw2.json"

    progress.pytest_runtest_logstart("tests/t.py::test_a")
    running = read_json(path)
    progress.pytest_runtest_logfinish("tests/t.py::test_other")
    assert read_json(path) == running
    progress.pytest_runtest_logfinish("tests/t.py::test_a")
    finished = read_json(path)

    assert running is not None and finished is not None
    assert running["finished_at"] is None
    assert (running["pid"], running["worker"], running["count"]) == (
        os.getpid(),
        "gw2",
        1,
    )
    assert finished["finished_at"] is not None
    assert progress.current_nodeid == "tests/t.py::test_a"


def test_kill_audit_flags_only_kills_that_can_reach_the_soak(tmp_path: Path) -> None:
    audit = KillAudit(tmp_path / KILLS_FILENAME, "gw0", lambda: None)
    group = os.getpgid(0)
    unrelated = 4_194_303  # above any default pid_max-allocated live pid here

    assert audit.hazard("os.killpg", 0) == "caller's own process group"
    assert audit.hazard("os.killpg", group) == "the soak's process group"
    assert audit.hazard("os.kill", 0) == "caller's own process group"
    assert audit.hazard("os.kill", -1) == "every process the user may signal"
    assert audit.hazard("os.kill", -group) == "the soak's process group"
    assert audit.hazard("os.kill", os.getpid()) == "the worker itself"
    assert audit.hazard("os.kill", os.getppid()) == "a soak ancestor"
    assert audit.hazard("os.kill", unrelated) is None
    assert audit.hazard("os.killpg", unrelated) is None


def test_kill_audit_records_hazards_with_their_test_and_stays_bounded(
    tmp_path: Path,
) -> None:
    path = tmp_path / KILLS_FILENAME
    audit = KillAudit(path, "gw5", lambda: "tests/t.py::test_kills")

    audit("open", ("/etc/hostname", "r", 0))
    audit("os.kill", (os.getpid(), 0))  # a liveness probe, not a kill
    audit("os.kill", (4_194_303, int(signal.SIGTERM)))
    assert not path.exists()

    for _ in range(KILL_RECORD_LIMIT + 5):
        audit("os.killpg", (0, int(signal.SIGTERM)))

    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(records) == KILL_RECORD_LIMIT
    assert records[0]["call"] == "os.killpg(0, SIGTERM)"
    assert records[0]["worker"] == "gw5"
    assert records[0]["nodeid"] == "tests/t.py::test_kills"
    assert any("test_kill_audit_records" in frame for frame in records[0]["stack"])


def test_kill_audit_never_raises_into_the_audited_call(tmp_path: Path) -> None:
    audit = KillAudit(tmp_path / "missing-dir" / KILLS_FILENAME, "gw0", lambda: None)

    audit("os.killpg", (0, int(signal.SIGTERM)))
    audit("os.kill", ("not-a-pid", "not-a-signal"))


def test_worker_arms_progress_and_audit_only_when_the_controller_asked(
    tmp_path: Path,
) -> None:
    hooks: list[object] = []
    unrequested = _Config({"workerid": "gw1"})
    register_worker_progress(unrequested, add_audit_hook=hooks.append)  # type: ignore[arg-type]
    assert unrequested.pluginmanager.registered == []
    register_worker_progress(_Config(), add_audit_hook=hooks.append)  # type: ignore[arg-type]
    assert hooks == []

    requested = _Config({"workerid": "gw1", WORKERINPUT_KEY: str(tmp_path)})
    register_worker_progress(requested, add_audit_hook=hooks.append)  # type: ignore[arg-type]

    assert [name for _, name in requested.pluginmanager.registered] == [
        WORKER_PLUGIN_NAME
    ]
    assert len(hooks) == 1 and isinstance(hooks[0], KillAudit)


class _Stdout:
    def __init__(self) -> None:
        self.reconfigured: dict[str, object] = {}

    def reconfigure(self, **options: object) -> None:
        self.reconfigured.update(options)


def test_controller_consumes_the_request_and_line_buffers_its_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stdout = _Stdout()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.delenv(DIAGNOSTICS_ENV, raising=False)
    config = _Config()
    register_controller_progress(config)  # type: ignore[arg-type]
    assert config.pluginmanager.registered == []
    assert stdout.reconfigured == {}

    monkeypatch.setenv(DIAGNOSTICS_ENV, str(tmp_path / "repeat-01"))
    register_controller_progress(config)  # type: ignore[arg-type]

    assert [name for _, name in config.pluginmanager.registered] == [
        CONTROLLER_PLUGIN_NAME
    ]
    # Popped, so the pytest subprocesses tests spawn cannot inherit it.
    assert DIAGNOSTICS_ENV not in os.environ
    assert stdout.reconfigured == {"line_buffering": True}
    assert (tmp_path / "repeat-01" / CONTROLLER_PROGRESS_FILENAME).exists()
