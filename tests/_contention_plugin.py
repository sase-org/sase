"""Record one contention repeat's failing node IDs for the soak tally.

`tools/run_pytest contention` loads this with ``-p`` for each repeat and reads
the record back to build the per-node tally. It deliberately does not live in
``tests/conftest.py``: the hook would then fire for every nested pytest
subprocess the suite itself spawns, and each one would overwrite the repeat's
record with its own handful of node IDs.

Nothing here touches the durable selection-health store. A soak deliberately
starves the machine, so its failures are not evidence about what a scoped run
should have selected, and must not be recorded as if they were.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests._contention import FAILURES_ENV, write_failures


class ContentionFailureRecorder:
    """Collect failing node IDs on the controller and write them at the end."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._failures: set[str] = set()

    @property
    def failures(self) -> tuple[str, ...]:
        return tuple(sorted(self._failures))

    @pytest.hookimpl(trylast=True)
    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        # xdist forwards worker reports to the controller, so collecting here
        # sees every failure exactly once regardless of worker count.
        if report.failed:
            self._failures.add(report.nodeid)

    @pytest.hookimpl(trylast=True)
    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        # A collection error under contention means the whole file never ran.
        # The tally reports it at file granularity rather than dropping it.
        if report.failed and report.nodeid:
            self._failures.add(report.nodeid)

    def pytest_sessionfinish(self) -> None:
        try:
            write_failures(self._path, self.failures)
        except OSError:
            # The harness still counts this repeat red from its exit status.
            pass


def pytest_configure(config: pytest.Config) -> None:
    if os.environ.get("PYTEST_XDIST_WORKER"):
        # Workers report to the controller; only the controller writes.
        return
    # Popped, not read: tests in this suite spawn their own pytest
    # subprocesses, and an inherited request would have them overwrite this
    # repeat's record.
    requested_path = os.environ.pop(FAILURES_ENV, None)
    if not requested_path:
        return
    config.pluginmanager.register(
        ContentionFailureRecorder(Path(requested_path)), "sase-contention-recorder"
    )
