"""Record a full-lane run's failures for selection-health correlation.

``tools/run_pytest`` loads this with ``-p`` for the full lanes (``fast`` and
``cov``) only. It cannot live in ``tests/conftest.py``: the full lanes hand off
with ``os.execv``, so the runner has no chance to write anything after pytest
exits, and a conftest hook would fire for every nested pytest subprocess the
suite itself spawns.

The record is what :mod:`tests._test_selection_health` correlates against
scoped selection manifests to detect false negatives — a test that failed in a
full run after a scoped run over an ancestor commit of the *same change*
excluded it. That last qualifier is why the record carries the runner's
workspace identity and change set alongside the failures.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from tests._test_selection_health import RECORD_ENV, full_run_record, write_record


class FullRunFailureRecorder:
    """Collect failing node IDs on the controller and write them at the end."""

    def __init__(
        self,
        path: Path,
        *,
        head: str | None,
        mode: str,
        workspace: str | None = None,
        changed_files: Sequence[str] | None = None,
    ) -> None:
        self._path = path
        self._head = head
        self._mode = mode
        # The runner resolves both in the parent process, before `execv`: the
        # correlator needs the change set this run is testing, and pytest is
        # in no position to recompute it once it is running.
        self._workspace = workspace
        self._changed_files = changed_files
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
        # A collection error means the whole file never ran; treat it as a
        # failure of that file, which is exactly the granularity the
        # correlator works at.
        if report.failed and report.nodeid:
            self._failures.add(report.nodeid)

    def pytest_sessionfinish(self, exitstatus: int) -> None:
        try:
            write_record(
                self._path,
                full_run_record(
                    head=self._head,
                    mode=self._mode,
                    failures=self.failures,
                    exit_status=int(exitstatus),
                    workspace=self._workspace,
                    changed_files=self._changed_files,
                ),
            )
        except OSError:
            # Health telemetry must never turn a green run red.
            pass


def _recorder_request() -> dict[str, Any] | None:
    """Consume the runner's request, so no child process inherits it.

    Popping matters: tests in this suite spawn their own pytest subprocesses,
    and an inherited request would have them overwrite this run's record with
    their own handful of node IDs.
    """
    raw = os.environ.pop(RECORD_ENV, None)
    if not raw:
        return None
    try:
        request = json.loads(raw)
    except ValueError:
        return None
    return request if isinstance(request, dict) and request.get("path") else None


def pytest_configure(config: pytest.Config) -> None:
    if os.environ.get("PYTEST_XDIST_WORKER"):
        # Workers report to the controller; only the controller writes.
        return
    request = _recorder_request()
    if request is None:
        return
    head = request.get("head")
    workspace = request.get("workspace")
    changed_files = request.get("changed_files")
    recorder = FullRunFailureRecorder(
        Path(str(request["path"])),
        head=str(head) if head else None,
        mode=str(request.get("mode") or "unknown"),
        workspace=str(workspace) if workspace else None,
        changed_files=(
            [str(path) for path in changed_files]
            if isinstance(changed_files, list)
            else None
        ),
    )
    config.pluginmanager.register(recorder, "sase-selection-health-recorder")
