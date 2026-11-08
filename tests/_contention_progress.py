"""Live progress and signal-hazard records for the contention soak.

Diagnostic only. `tools/run_pytest contention` hands the controller one
directory per repeat through `DIAGNOSTICS_ENV`; the controller passes it on to
its xdist workers through ``workerinput``, never through the environment, so the
pytest subprocesses tests spawn cannot inherit it and overwrite the evidence.

Three kinds of file land there, all small and overwritten or capped:

- ``controller.json``: the controller's view -- workers configured, the
  collection boundary, tests started and finished, recent and in-flight nodes.
  Rewritten at most once a second.
- ``worker-<id>.json``: the node a worker started last, with its PID, so a
  sampler that learns a PID sent or received a signal can name the test.
- ``kills.jsonl``: worker ``os.kill``/``os.killpg`` calls aimed at the soak's
  own process group, an ancestor, or every process. Seen through an audit hook,
  which observes the call and never vetoes it.

Nothing here may change a test outcome: every write is best effort, and the
audit hook swallows its own errors.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
import traceback
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests._contention import (
    CONTROLLER_PROGRESS_FILENAME,
    DIAGNOSTICS_ENV,
    KILLS_FILENAME,
    WORKER_PROGRESS_PREFIX,
    write_json_atomic,
)


#: The ``workerinput`` key the controller forwards the progress directory under.
WORKERINPUT_KEY = "sase_contention_diagnostics"
CONTROLLER_PLUGIN_NAME = "sase-contention-progress"
WORKER_PLUGIN_NAME = "sase-contention-worker-progress"
CONTROLLER_WRITE_INTERVAL_SECONDS = 1.0
RECENT_NODE_LIMIT = 20
INFLIGHT_NODE_LIMIT = 64
KILL_RECORD_LIMIT = 50
KILL_STACK_LIMIT = 12
KILL_EVENTS = frozenset({"os.kill", "os.killpg"})


def _node_worker_id(node: Any) -> str:
    workerinput = getattr(node, "workerinput", None)
    if isinstance(workerinput, dict) and workerinput.get("workerid"):
        return str(workerinput["workerid"])
    gateway = getattr(node, "gateway", None)
    return str(getattr(gateway, "id", "?"))


class ControllerProgress:
    """The controller's progress record, written at a bounded rate."""

    def __init__(
        self,
        directory: Path,
        *,
        clock: Callable[[], float] = time.time,
        sharded: bool = False,
    ) -> None:
        self._directory = directory
        self._clock = clock
        # Workers that collected the same selection report the same count;
        # sharded workers each report their own part of it.
        self._sharded = sharded
        self._pid = os.getpid()
        self._configured_at = clock()
        self._session_started_at: float | None = None
        self._workers_configured = 0
        self._collected: dict[str, int] = {}
        self._collection_first_at: float | None = None
        self._collection_last_at: float | None = None
        self._inflight: dict[str, float] = {}
        self._recent: deque[str] = deque(maxlen=RECENT_NODE_LIMIT)
        self._started = 0
        self._finished = 0
        self._failed_reports = 0
        self._exitstatus: int | None = None
        self._last_write = float("-inf")
        self._persist(force=True)

    def snapshot(self) -> dict[str, Any]:
        oldest_first = sorted(self._inflight.items(), key=lambda item: item[1])
        return {
            "pid": self._pid,
            "configured_at": self._configured_at,
            "session_started_at": self._session_started_at,
            "workers_configured": self._workers_configured,
            "collection": {
                "workers_finished": len(self._collected),
                "items": (
                    sum(self._collected.values())
                    if self._sharded
                    else max(self._collected.values(), default=0)
                ),
                "first_at": self._collection_first_at,
                "last_at": self._collection_last_at,
            },
            "started": self._started,
            "finished": self._finished,
            "failed_reports": self._failed_reports,
            "inflight": [
                {"nodeid": nodeid, "started_at": started}
                for nodeid, started in oldest_first[:INFLIGHT_NODE_LIMIT]
            ],
            "recent": list(self._recent),
            "exitstatus": self._exitstatus,
            "written_at": self._clock(),
        }

    def _persist(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_write < CONTROLLER_WRITE_INTERVAL_SECONDS:
            return
        self._last_write = now
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            write_json_atomic(
                self._directory / CONTROLLER_PROGRESS_FILENAME, self.snapshot()
            )
        except OSError:
            pass

    @pytest.hookimpl(optionalhook=True)
    def pytest_configure_node(self, node: Any) -> None:
        self._workers_configured += 1
        node.workerinput[WORKERINPUT_KEY] = str(self._directory)
        # Forced: nothing else writes before a worker finishes collecting, so a
        # throttled write here left the record one worker short all collection.
        self._persist(force=True)

    def pytest_sessionstart(self) -> None:
        self._session_started_at = self._clock()
        self._persist(force=True)

    @pytest.hookimpl(optionalhook=True)
    def pytest_xdist_node_collection_finished(self, node: Any, ids: Any) -> None:
        now = self._clock()
        self._collected[_node_worker_id(node)] = len(ids)
        if self._collection_first_at is None:
            self._collection_first_at = now
        self._collection_last_at = now
        self._persist(force=True)

    def pytest_runtest_logstart(self, nodeid: str) -> None:
        self._started += 1
        self._inflight[nodeid] = self._clock()
        self._persist()

    def pytest_runtest_logfinish(self, nodeid: str) -> None:
        self._finished += 1
        self._inflight.pop(nodeid, None)
        self._recent.append(nodeid)
        self._persist()

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if report.failed:
            self._failed_reports += 1

    def pytest_sessionfinish(self, exitstatus: int) -> None:
        self._exitstatus = int(exitstatus)
        self._persist(force=True)


class WorkerProgress:
    """One worker's latest node, rewritten as each test starts and finishes.

    ``finished_at`` is ``None`` while the node runs, so a reader can tell a
    worker inside a test from one that is idle or between tests.
    """

    def __init__(self, directory: Path, worker_id: str) -> None:
        self._path = directory / f"{WORKER_PROGRESS_PREFIX}{worker_id}.json"
        self._record: dict[str, Any] = {
            "worker": worker_id,
            "pid": os.getpid(),
            "start_time_ticks": _self_start_time_ticks(),
            "nodeid": None,
            "started_at": None,
            "finished_at": None,
            "count": 0,
        }
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    @property
    def current_nodeid(self) -> str | None:
        return self._record["nodeid"]

    def _write(self) -> None:
        try:
            write_json_atomic(self._path, self._record)
        except OSError:
            pass

    def pytest_runtest_logstart(self, nodeid: str) -> None:
        self._record["count"] += 1
        self._record.update(nodeid=nodeid, started_at=time.time(), finished_at=None)
        self._write()

    def pytest_runtest_logfinish(self, nodeid: str) -> None:
        if nodeid == self._record["nodeid"]:
            self._record["finished_at"] = time.time()
            self._write()


def _stat_fields(pid: int) -> tuple[int, int] | None:
    """``(ppid, pgrp)`` for ``pid`` from ``/proc``, or ``None``."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        fields = raw[raw.rindex(")") + 2 :].split()
        return int(fields[1]), int(fields[2])
    except (OSError, ValueError, IndexError):
        return None


def _self_start_time_ticks() -> int | None:
    """The kernel start tick distinguishes this PID from a later reuse."""
    try:
        raw = Path("/proc/self/stat").read_text(encoding="utf-8")
        fields = raw[raw.rindex(")") + 2 :].split()
        return int(fields[19])
    except (OSError, ValueError, IndexError):
        return None


def _ancestry() -> tuple[frozenset[int], frozenset[int]]:
    """This process's ancestor PIDs and their process groups."""
    pids: set[int] = set()
    groups: set[int] = set()
    pid = os.getppid()
    while pid > 1 and pid not in pids and len(pids) < 64:
        pids.add(pid)
        fields = _stat_fields(pid)
        if fields is None:
            break
        pid, group = fields
        groups.add(group)
    return frozenset(pids), frozenset(groups)


class KillAudit:
    """Record kill calls that could reach the soak itself.

    Installed with `sys.addaudithook`, which cannot be removed, so it stays
    cheap for every other audit event and never raises.
    """

    def __init__(
        self,
        path: Path,
        worker_id: str,
        current_nodeid: Callable[[], str | None],
    ) -> None:
        self._path = path
        self._worker_id = worker_id
        self._current_nodeid = current_nodeid
        self._pid = os.getpid()
        self._group = os.getpgid(0)
        self._ancestors, ancestor_groups = _ancestry()
        self._groups = frozenset({self._group, *ancestor_groups})
        self._records = 0
        self._busy = False

    def hazard(self, event: str, target: int) -> str | None:
        """Why a kill of ``target`` could reach the soak, or ``None``."""
        if event == "os.killpg":
            if target <= 0:
                return "caller's own process group"
            if target in self._groups:
                return "the soak's process group"
            return None
        if target == 0:
            return "caller's own process group"
        if target == -1:
            return "every process the user may signal"
        if target < 0 and -target in self._groups:
            return "the soak's process group"
        if target == self._pid:
            return "the worker itself"
        if target in self._ancestors:
            return "a soak ancestor"
        return None

    def __call__(self, event: str, args: tuple[Any, ...]) -> None:
        if event not in KILL_EVENTS or self._busy:
            return
        self._busy = True
        try:
            target, signum = int(args[0]), int(args[1])
            reason = None if signum == 0 else self.hazard(event, target)
            if reason is None or self._records >= KILL_RECORD_LIMIT:
                return
            self._records += 1
            self._append(event, target, signum, reason)
        except Exception:
            pass
        finally:
            self._busy = False

    def _append(self, event: str, target: int, signum: int, reason: str) -> None:
        try:
            name = signal.Signals(signum).name
        except ValueError:
            name = str(signum)
        record = {
            "at": time.time(),
            "worker": self._worker_id,
            "pid": self._pid,
            "call": f"{event}({target}, {name})",
            "reason": reason,
            "nodeid": self._current_nodeid(),
            "stack": traceback.format_stack(limit=KILL_STACK_LIMIT)[:-2],
        }
        line = (json.dumps(record, sort_keys=True) + "\n").encode()
        descriptor = os.open(self._path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(descriptor, line)
        finally:
            os.close(descriptor)


def register_worker_progress(
    config: pytest.Config,
    *,
    add_audit_hook: Callable[[Callable[[str, tuple[Any, ...]], None]], None] = (
        sys.addaudithook
    ),
) -> None:
    """Arm this worker's progress record and kill audit, if requested.

    ``add_audit_hook`` exists for tests: a real audit hook cannot be removed,
    and must not outlive a unit test inside the worker that ran it.
    """
    workerinput = getattr(config, "workerinput", None)
    if not isinstance(workerinput, dict):
        return
    directory = workerinput.get(WORKERINPUT_KEY)
    worker_id = workerinput.get("workerid")
    if not directory or not worker_id:
        return
    progress = WorkerProgress(Path(directory), str(worker_id))
    config.pluginmanager.register(progress, WORKER_PLUGIN_NAME)
    try:
        add_audit_hook(
            KillAudit(
                Path(directory) / KILLS_FILENAME,
                str(worker_id),
                lambda: progress.current_nodeid,
            )
        )
    except Exception:
        pass


def register_controller_progress(
    config: pytest.Config, *, sharded: bool = False
) -> None:
    """Arm the controller's progress record, consuming the request."""
    # Popped like the failure record: nested pytest runs must not inherit it.
    directory = os.environ.pop(DIAGNOSTICS_ENV, None)
    if not directory:
        return
    config.pluginmanager.register(
        ControllerProgress(Path(directory), sharded=sharded), CONTROLLER_PLUGIN_NAME
    )
    # Piped stdout is block-buffered until the first test reports, so a soak
    # that dies while its workers are still collecting printed nothing at all.
    # Line buffering only changes when the same output reaches the log.
    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]
    except (AttributeError, ValueError, OSError):
        pass
