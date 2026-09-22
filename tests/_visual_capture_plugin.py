"""Opt-in pytest plugin for isolated visual screenshot candidate capture.

Enabled by ``--sase-visual-capture-dir``. Workers write only into their own
directories; the controller merges those records after the session finishes.
"""

from __future__ import annotations

from collections.abc import Sequence
import json
import os
from pathlib import Path
from typing import Any
import uuid

import pytest

from tests.ace.tui.visual._visual_capture import (
    DEFAULT_ACE_ROOT,
    DEFAULT_PAGER_ROOT,
    PLUGIN_NAME,
    VisualCaptureRoots,
    VisualCaptureSession,
    WorkerSessionRecord,
    merge_capture_dir,
    write_inventory,
)
from tests.ace.tui.visual._visual_capture_paths import atomic_write_text


class VisualCapturePlugin:
    """Record captures and execution evidence for one capture run."""

    def __init__(
        self,
        session: VisualCaptureSession,
        *,
        config: pytest.Config,
        requested_scope: str,
    ) -> None:
        self.capture_session = session
        self._config = config
        self._requested_scope = requested_scope
        self._expected_workers: list[str] = []
        self._lost_workers: list[str] = []
        self._collected: list[str] = []
        self._deselected: list[str] = []
        self._executed: set[str] = set()
        self._skipped: set[str] = set()
        self._xfailed: set[str] = set()
        self._xpassed: set[str] = set()
        self._failed: set[str] = set()
        self._errors: set[str] = set()
        self._worker_errors: list[str] = []

    @property
    def _xdist_controller(self) -> bool:
        if os.environ.get("PYTEST_XDIST_WORKER"):
            return False
        numprocesses = getattr(self._config.option, "numprocesses", None)
        return bool(numprocesses)

    @property
    def _runs_tests(self) -> bool:
        return not self._xdist_controller

    def pytest_configure_node(self, node: Any) -> None:
        worker_id = str(node.gateway.id)
        self._expected_workers.append(worker_id)
        node.workerinput["sase_visual_capture_run_id"] = self.capture_session.run_id
        node.workerinput["sase_visual_capture_dir"] = str(
            self.capture_session.capture_dir
        )

    def pytest_sessionstart(self, session: pytest.Session) -> None:
        if self._runs_tests:
            self._write_worker_session(exitstatus=None, completed=False)

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        if not self._runs_tests:
            return
        self._collected = [item.nodeid for item in session.items]
        self._write_worker_session(exitstatus=None, completed=False)

    def pytest_deselected(self, items: Sequence[pytest.Item]) -> None:
        if not self._runs_tests:
            return
        self._deselected.extend(
            item.nodeid for item in items if _is_visual_deselection(item)
        )

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if not self._runs_tests:
            return
        nodeid = report.nodeid
        wasxfail = getattr(report, "wasxfail", None)
        if report.when == "call":
            self._executed.add(nodeid)
            if report.failed:
                self._failed.add(nodeid)
            elif report.passed and wasxfail:
                self._xpassed.add(nodeid)
        if report.skipped:
            if wasxfail:
                self._xfailed.add(nodeid)
            else:
                self._skipped.add(nodeid)
        if report.failed and report.when in {"setup", "teardown"}:
            self._errors.add(nodeid)

    def pytest_testnodedown(self, node: Any, error: object | None) -> None:
        if error is not None:
            self._lost_workers.append(str(node.gateway.id))

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        collectonly = bool(getattr(session.config.option, "collectonly", False))
        if self._runs_tests:
            self._write_worker_session(
                exitstatus=int(exitstatus),
                completed=True,
                collectonly=collectonly,
            )
        if os.environ.get("PYTEST_XDIST_WORKER"):
            return
        expected = self._expected_workers or _fallback_expected_workers(session.config)
        inventory = merge_capture_dir(
            self.capture_session.capture_dir,
            run_id=self.capture_session.run_id,
            requested_scope=self._requested_scope,
            expected_workers=expected,
            session_exitstatus=int(exitstatus),
            collectonly=collectonly,
            lost_workers=self._lost_workers,
        )
        write_inventory(self.capture_session.capture_dir, inventory)
        if inventory.errors:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED

    def _write_worker_session(
        self,
        *,
        exitstatus: int | None,
        completed: bool,
        collectonly: bool = False,
    ) -> None:
        record = WorkerSessionRecord(
            run_id=self.capture_session.run_id,
            worker_id=self.capture_session.worker_id,
            completed=completed,
            collectonly=collectonly,
            exitstatus=exitstatus,
            collected_node_ids=tuple(self._collected),
            executed_node_ids=tuple(sorted(self._executed)),
            skipped_node_ids=tuple(sorted(self._skipped)),
            xfailed_node_ids=tuple(sorted(self._xfailed)),
            xpassed_node_ids=tuple(sorted(self._xpassed)),
            failed_node_ids=tuple(sorted(self._failed)),
            error_node_ids=tuple(sorted(self._errors)),
            deselected_node_ids=tuple(self._deselected),
            capture_count=len(self.capture_session.captures),
            errors=tuple(self._worker_errors),
        )
        self.capture_session.write_worker_session(record)


def _is_visual_deselection(item: pytest.Item) -> bool:
    """Return whether a deselected item can still block a full inventory.

    Items with no ``visual`` marker that also request neither PNG fixture
    cannot produce a golden, so their marker-based deselection is expected
    exclusion rather than incomplete inventory. Marked or PNG-fixture items
    are still recorded so a mis-marked snapshot test blocks pruning instead
    of getting its golden deleted.
    """
    if item.get_closest_marker("visual") is not None:
        return True
    fixturenames = getattr(item, "fixturenames", ())
    return "ace_png_visual" in fixturenames or "pager_png_visual" in fixturenames


def capture_session_from_config(
    config: pytest.Config,
) -> VisualCaptureSession | None:
    """Return the active capture session, if this run is collecting candidates."""
    plugin = config.pluginmanager.get_plugin(PLUGIN_NAME)
    if not isinstance(plugin, VisualCapturePlugin):
        return None
    return plugin.capture_session


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("sase visual capture")
    group.addoption(
        "--sase-visual-capture-dir",
        default=None,
        help="Internal candidate directory for a visual capture session.",
    )
    group.addoption(
        "--sase-visual-capture-run-id",
        default=None,
        help="Internal run identity for a visual capture session.",
    )
    group.addoption(
        "--sase-visual-capture-scope",
        choices=("full", "targeted"),
        default="targeted",
        help="Internal inventory scope. full is required for orphan evidence.",
    )
    group.addoption(
        "--sase-visual-capture-ace-root",
        default=DEFAULT_ACE_ROOT,
        help="Repository-relative ACE PNG golden root (internal).",
    )
    group.addoption(
        "--sase-visual-capture-pager-root",
        default=DEFAULT_PAGER_ROOT,
        help="Repository-relative pager PNG golden root (internal).",
    )


def pytest_configure(config: pytest.Config) -> None:
    capture_dir_option = config.getoption("--sase-visual-capture-dir", default=None)
    if not capture_dir_option:
        return
    if config.pluginmanager.hasplugin(PLUGIN_NAME):
        return
    rootpath = Path(config.rootpath) if config.rootpath is not None else Path.cwd()
    workerinput = getattr(config, "workerinput", None)
    capture_dir = _resolve_capture_dir(
        capture_dir_option, rootpath=rootpath, workerinput=workerinput
    )
    run_id = _resolve_run_id(config, workerinput)
    worker_id = os.environ.get("PYTEST_XDIST_WORKER") or "controller"
    ace_root = _resolve_root(
        config.getoption("--sase-visual-capture-ace-root"), rootpath
    )
    pager_root = _resolve_root(
        config.getoption("--sase-visual-capture-pager-root"), rootpath
    )
    session = VisualCaptureSession(
        capture_dir=capture_dir,
        run_id=run_id,
        worker_id=worker_id,
        repo_root=rootpath,
        roots=VisualCaptureRoots(ace=ace_root, pager=pager_root),
    )
    if not os.environ.get("PYTEST_XDIST_WORKER"):
        capture_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            capture_dir / "run.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "run",
                    "run_id": run_id,
                    "requested_scope": config.getoption("--sase-visual-capture-scope"),
                    "ace_root": _posix_relative(ace_root, rootpath),
                    "pager_root": _posix_relative(pager_root, rootpath),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )
    plugin = VisualCapturePlugin(
        session,
        config=config,
        requested_scope=str(
            config.getoption("--sase-visual-capture-scope") or "targeted"
        ),
    )
    config.pluginmanager.register(plugin, PLUGIN_NAME)


def _resolve_capture_dir(
    value: object,
    *,
    rootpath: Path,
    workerinput: dict[str, Any] | None,
) -> Path:
    if isinstance(workerinput, dict):
        raw = workerinput.get("sase_visual_capture_dir")
        if isinstance(raw, str) and raw:
            return Path(raw)
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = rootpath / path
    return path


def _resolve_run_id(config: pytest.Config, workerinput: dict[str, Any] | None) -> str:
    if isinstance(workerinput, dict):
        raw = workerinput.get("sase_visual_capture_run_id")
        if isinstance(raw, str) and raw:
            return raw
    cli = config.getoption("--sase-visual-capture-run-id", default=None)
    if isinstance(cli, str) and cli.strip():
        return cli.strip()
    return uuid.uuid4().hex


def _resolve_root(value: object, rootpath: Path) -> Path:
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = rootpath / path
    return path


def _posix_relative(path: Path, rootpath: Path) -> str:
    try:
        return path.resolve().relative_to(rootpath.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _fallback_expected_workers(config: pytest.Config) -> list[str]:
    numprocesses = getattr(config.option, "numprocesses", None)
    if not numprocesses:
        return ["controller"]
    return [f"gw{index}" for index in range(int(numprocesses))]
