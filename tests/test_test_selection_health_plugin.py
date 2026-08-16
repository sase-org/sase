"""Unit tests for the full-lane failure recorder plugin.

The recorder is what gives the correlator its other half: the failures a full
suite run actually saw. It is telemetry, so it must record exactly the failures
and never fail a run of its own accord.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests._selection_health_case_helpers import CHANGED, WORKSPACE
from tests._test_selection_health_plugin import (
    FullRunFailureRecorder,
    pytest_configure,
)
from tests._test_selection_health_store import KIND_FULL_RUN, RECORD_ENV


class _FakeReport:
    def __init__(self, nodeid: str, *, failed: bool) -> None:
        self.nodeid = nodeid
        self.failed = failed


class _FakePluginManager:
    def __init__(self) -> None:
        self.registered: dict[str, object] = {}

    def register(self, plugin: object, name: str) -> None:
        self.registered[name] = plugin


class _FakeConfig:
    def __init__(self) -> None:
        self.pluginmanager = _FakePluginManager()


def test_recorder_writes_only_the_failures_it_saw(tmp_path: Path) -> None:
    path = tmp_path / "record.json"
    recorder = FullRunFailureRecorder(
        path,
        head="abc",
        mode="fast",
        workspace=WORKSPACE,
        changed_files=CHANGED,
        tree_dirty=True,
    )

    for _ in range(2):
        recorder.pytest_runtest_logreport(
            _FakeReport("tests/test_a.py::test_x", failed=True)
        )
    recorder.pytest_runtest_logreport(
        _FakeReport("tests/test_b.py::test_y", failed=False)
    )
    recorder.pytest_collectreport(_FakeReport("tests/test_c.py", failed=True))
    recorder.pytest_sessionfinish(1)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["kind"] == KIND_FULL_RUN
    assert payload["head"] == "abc"
    assert payload["failures"] == ["tests/test_a.py::test_x", "tests/test_c.py"]
    assert payload["workspace"] == WORKSPACE
    assert payload["changed_files"] == list(CHANGED)
    assert payload["tree_dirty"] is True


def test_recorder_never_fails_a_run_over_an_unwritable_store(tmp_path: Path) -> None:
    # A directory is not a writable record path; telemetry must swallow that.
    recorder = FullRunFailureRecorder(tmp_path, head=None, mode="fast")

    recorder.pytest_sessionfinish(0)


def test_plugin_registers_a_recorder_and_consumes_the_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    record_path = tmp_path / "record.json"
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    monkeypatch.setenv(
        RECORD_ENV,
        json.dumps(
            {
                "path": str(record_path),
                "head": "abc",
                "mode": "cov",
                "workspace": WORKSPACE,
                "changed_files": list(CHANGED),
                "tree_dirty": True,
            }
        ),
    )
    config = _FakeConfig()

    pytest_configure(config)

    recorder = config.pluginmanager.registered["sase-selection-health-recorder"]
    assert isinstance(recorder, FullRunFailureRecorder)
    recorder.pytest_sessionfinish(0)
    written = json.loads(record_path.read_text(encoding="utf-8"))
    assert written["workspace"] == WORKSPACE
    assert written["changed_files"] == list(CHANGED)
    assert written["tree_dirty"] is True
    # Popped so nested pytest subprocesses cannot overwrite this run's record.
    assert RECORD_ENV not in os.environ


def test_plugin_does_nothing_without_a_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(RECORD_ENV, raising=False)
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    config = _FakeConfig()

    pytest_configure(config)

    assert not config.pluginmanager.registered


def test_plugin_leaves_recording_to_the_xdist_controller(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw3")
    monkeypatch.setenv(RECORD_ENV, json.dumps({"path": str(tmp_path / "record.json")}))
    config = _FakeConfig()

    pytest_configure(config)

    assert not config.pluginmanager.registered
