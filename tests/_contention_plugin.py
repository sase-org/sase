"""Record one contention repeat's failing node IDs for the soak tally.

`tools/run_pytest contention` loads this with ``-p`` for each repeat and reads
the record back to build the per-node tally. It deliberately does not live in
``tests/conftest.py``: the hook would then fire for every nested pytest
subprocess the suite itself spawns, and each one would overwrite the repeat's
record with its own handful of node IDs.

Nothing here touches the durable selection-health store. A soak deliberately
starves the machine, so its failures are not evidence about what a scoped run
should have selected, and must not be recorded as if they were.

The same plugin arms the soak's diagnostic progress records
(`tests._contention_progress`) and its sharded collection
(`tests._contention_shards`) when the harness asks for them.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

from tests._contention import (
    FAILURE_DETAIL_LIMIT,
    FAILURE_RECORD_LIMIT,
    FAILURES_ENV,
    append_failure_report,
    finish_failure_record,
    start_failure_record,
)
from tests._contention_progress import (
    register_controller_progress,
    register_worker_progress,
)
from tests._contention_shards import (
    register_controller_shards,
    register_worker_shards,
)


class ContentionFailureRecorder:
    """Persist bounded failure reports on the controller as pytest reports arrive."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._reports: list[dict[str, Any]] = []
        self._report_keys: set[tuple[str, str]] = set()
        self._reports_seen = 0
        self._reports_omitted = 0
        self._reports_unwritten = 0
        self._log_count = 0
        try:
            start_failure_record(path)
        except OSError:
            # Diagnostics never change the pytest outcome.
            self._reports_unwritten += 1

    @property
    def failures(self) -> tuple[str, ...]:
        return tuple(sorted({str(report["nodeid"]) for report in self._reports}))

    def _record(self, nodeid: str, phase: str, longrepr: object) -> None:
        if not nodeid:
            return
        key = (nodeid, phase)
        if key in self._report_keys:
            return
        self._reports_seen += 1
        try:
            detail = str(longrepr) if longrepr is not None else ""
        except Exception as error:
            detail = f"<failure detail unavailable: {type(error).__name__}>"
        truncated = len(detail) > FAILURE_DETAIL_LIMIT
        detail = detail[:FAILURE_DETAIL_LIMIT]
        if len(self._reports) >= FAILURE_RECORD_LIMIT:
            self._reports_omitted += 1
        else:
            try:
                append_failure_report(
                    self._path,
                    nodeid=nodeid,
                    phase=phase,
                    detail=detail,
                    detail_truncated=truncated,
                )
            except OSError:
                self._reports_unwritten += 1
            else:
                self._reports.append(
                    {
                        "nodeid": nodeid,
                        "phase": phase,
                        "detail": detail,
                        "detail_truncated": truncated,
                    }
                )
                self._report_keys.add(key)
        if self._log_count < FAILURE_RECORD_LIMIT:
            self._log_count += 1
            try:
                sys.stderr.write(f"[contention-failure] {phase} {nodeid}: {detail}\n")
                sys.stderr.flush()
            except (OSError, ValueError):
                pass

    @pytest.hookimpl(trylast=True)
    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        # xdist forwards worker reports to the controller, so collecting here
        # sees every failure exactly once regardless of worker count.
        if report.failed:
            self._record(report.nodeid, str(report.when), report.longrepr)

    @pytest.hookimpl(trylast=True)
    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        # A collection error under contention means the whole file never ran.
        # The tally reports it at file granularity rather than dropping it.
        if report.failed and report.nodeid:
            self._record(report.nodeid, "collect", report.longrepr)

    def pytest_sessionfinish(self, exitstatus: int | None = None) -> None:
        try:
            finish_failure_record(
                self._path,
                exitstatus=exitstatus,
                reports_seen=self._reports_seen,
                reports_written=len(self._reports),
                reports_omitted=self._reports_omitted,
                reports_unwritten=self._reports_unwritten,
            )
        except OSError:
            # The harness still counts this repeat red from its exit status.
            pass


def pytest_configure(config: pytest.Config) -> None:
    if os.environ.get("PYTEST_XDIST_WORKER"):
        # Workers report to the controller; only the controller writes the
        # failure record. A worker only keeps its own diagnostic progress and
        # collects its own shard.
        register_worker_shards(config)
        register_worker_progress(config)
        return
    sharded = register_controller_shards(config) is not None
    register_controller_progress(config, sharded=sharded)
    # Popped, not read: tests in this suite spawn their own pytest
    # subprocesses, and an inherited request would have them overwrite this
    # repeat's record.
    requested_path = os.environ.pop(FAILURES_ENV, None)
    if not requested_path:
        return
    config.pluginmanager.register(
        ContentionFailureRecorder(Path(requested_path)), "sase-contention-recorder"
    )
