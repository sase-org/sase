"""Record per-test-file wall seconds from a run the lane already does.

``tools/run_pytest`` loads this with ``-p`` for the full lanes and for scoped
runs. It cannot live in ``tests/conftest.py`` for the same two reasons the
selection-health recorder cannot: the full lanes hand off with ``os.execv``, so
the runner gets no chance to write anything after pytest exits, and a conftest
hook would fire inside every nested pytest subprocess this suite spawns and
overwrite the real recording with a handful of node IDs.

What lands on disk is the cost model :mod:`tests._test_selection_timings`
merges and estimates from. Nothing here decides anything.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from tests._test_selection_timings import file_for_nodeid, write_timings


#: JSON handed to this plugin by ``tools/run_pytest``, which resolves the store
#: in the parent process where ``SASE_HOME`` is the real one rather than a
#: per-test redirect.
TIMINGS_RECORD_ENV = "SASE_TEST_SELECTION_TIMINGS_RECORD"


class FileDurationRecorder:
    """Sum every phase's wall seconds per test file, and write them at the end."""

    def __init__(
        self,
        directory: Path,
        *,
        mode: str,
        worker_count: int | None = None,
    ) -> None:
        self._directory = directory
        self._mode = mode
        self._worker_count = worker_count
        self._durations: dict[str, float] = {}

    @property
    def durations(self) -> dict[str, float]:
        return dict(self._durations)

    def _add(self, report: object) -> None:
        # `duration` is not on every report type in every pytest version, and a
        # zero is not a measurement — a file whose whole contribution is zeros
        # would otherwise merge over a real duration as if it were free.
        duration = float(getattr(report, "duration", 0.0) or 0.0)
        path = file_for_nodeid(str(getattr(report, "nodeid", "")))
        if path is None or duration <= 0:
            return
        self._durations[path] = self._durations.get(path, 0.0) + duration

    @pytest.hookimpl(trylast=True)
    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        # xdist forwards worker reports to the controller, so summing here sees
        # every phase of every test exactly once at any worker count. Setup and
        # teardown are counted too: a file whose fixtures cost more than its
        # assertions still costs that time when a selection includes it.
        self._add(report)

    @pytest.hookimpl(trylast=True)
    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        self._add(report)

    def pytest_sessionfinish(self, exitstatus: int) -> None:
        try:
            write_timings(
                self._directory,
                self._durations,
                mode=self._mode,
                worker_count=self._worker_count,
            )
        except OSError:
            # A cost model must never turn a green run red.
            pass


def _recorder_request() -> dict[str, Any] | None:
    """Consume the runner's request, so no child process inherits it."""
    raw = os.environ.pop(TIMINGS_RECORD_ENV, None)
    if not raw:
        return None
    try:
        request = json.loads(raw)
    except ValueError:
        return None
    return request if isinstance(request, dict) and request.get("directory") else None


def pytest_configure(config: pytest.Config) -> None:
    if os.environ.get("PYTEST_XDIST_WORKER"):
        # Workers report to the controller; only the controller writes.
        return
    request = _recorder_request()
    if request is None:
        return
    raw_workers = request.get("worker_count")
    recorder = FileDurationRecorder(
        Path(str(request["directory"])),
        mode=str(request.get("mode") or "unknown"),
        worker_count=int(raw_workers) if isinstance(raw_workers, int) else None,
    )
    config.pluginmanager.register(recorder, "sase-selection-timings-recorder")
