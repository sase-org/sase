"""Opt-in pytest plugin that writes structured qualification session evidence.

Activate only by loading this module (``-p tests._pytest_qualify_evidence``) and
setting ``SASE_QUALIFY_EVIDENCE_PATH``. Nothing in pytest.ini, conftest, or
``tools/run_pytest`` enables it. Nested pytest subprocesses inherit the path
but cannot overwrite the outer session's report: the outer session claims the
path exclusively. xdist workers never write; the controller counts each node
once from aggregated log reports.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest


EVIDENCE_PATH_ENV = "SASE_QUALIFY_EVIDENCE_PATH"
OWNER_SUFFIX = ".owner"
SESSION_KIND = "pytest_session"
SESSION_SCHEMA_VERSION = 1
_FLAKY_PREFIX = "FLAKY:"


def _path_from_env() -> Path | None:
    raw = os.environ.get(EVIDENCE_PATH_ENV, "").strip()
    if not raw:
        return None
    return Path(raw)


def _claim_path(path: Path) -> bool:
    """Return True when this process exclusively owns ``path``'s report."""
    claim = path.with_name(path.name + OWNER_SUFFIX)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(claim), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    try:
        os.write(fd, str(os.getpid()).encode("utf-8"))
    finally:
        os.close(fd)
    return True


def _is_xdist_worker(config: pytest.Config) -> bool:
    # workerinput is xdist's session-local marker. PYTEST_XDIST_WORKER is
    # inherited by nested pytest subprocesses inside tests, so it would make
    # those inner controllers skip the report they are supposed to write.
    return hasattr(config, "workerinput")


def _flaky_from_text(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith(_FLAKY_PREFIX):
            lines.append(stripped)
    return lines


def _report_text(report: object) -> str:
    chunks: list[str] = []
    longrepr = getattr(report, "longreprtext", None)
    if isinstance(longrepr, str):
        chunks.append(longrepr)
    longrepr_obj = getattr(report, "longrepr", None)
    if longrepr_obj is not None and not isinstance(longrepr, str):
        chunks.append(str(longrepr_obj))
    for attr in ("capstdout", "capstderr", "caplog"):
        value = getattr(report, attr, None)
        if isinstance(value, str):
            chunks.append(value)
    sections = getattr(report, "sections", None)
    if isinstance(sections, list):
        for section in sections:
            if isinstance(section, tuple) and len(section) >= 2:
                chunks.append(str(section[1]))
    return "\n".join(chunks)


class QualifyEvidencePlugin:
    """Collect one session's pytest counts without inventing a green report."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._outcomes: dict[str, str] = {}
        self._failing: list[str] = []
        self._flaky: list[str] = []
        self._collection_failed = False
        self._exit_status = 0

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        self._record_flaky(report)
        if report.failed:
            self._collection_failed = True
            nodeid = str(getattr(report, "nodeid", "") or "")
            if nodeid:
                self._add_failing(nodeid)

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        self._record_flaky(report)
        nodeid = str(report.nodeid)
        if report.when == "call":
            self._outcomes[nodeid] = report.outcome
            if report.failed:
                self._add_failing(nodeid)
            return
        if report.when in {"setup", "teardown"} and report.failed:
            self._outcomes[nodeid] = "error"
            self._add_failing(nodeid)
            return
        if report.when == "setup" and report.skipped and nodeid not in self._outcomes:
            self._outcomes[nodeid] = "skipped"

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        self._exit_status = int(exitstatus)
        collected_hint = int(getattr(session, "testscollected", 0) or 0)
        payload = self._payload(collected_hint)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(self._path.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        tmp.replace(self._path)

    def _add_failing(self, nodeid: str) -> None:
        if nodeid not in self._failing:
            self._failing.append(nodeid)

    def _record_flaky(self, report: object) -> None:
        for line in _flaky_from_text(_report_text(report)):
            if line not in self._flaky:
                self._flaky.append(line)

    def _payload(self, collected_hint: int) -> dict[str, Any]:
        passed = sum(1 for outcome in self._outcomes.values() if outcome == "passed")
        failed = sum(1 for outcome in self._outcomes.values() if outcome == "failed")
        errors = sum(1 for outcome in self._outcomes.values() if outcome == "error")
        skipped = sum(1 for outcome in self._outcomes.values() if outcome == "skipped")
        collected = len(self._outcomes)
        if collected == 0 and collected_hint > 0 and not self._collection_failed:
            collected = collected_hint
        return {
            "schema_version": SESSION_SCHEMA_VERSION,
            "kind": SESSION_KIND,
            "collected": collected,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "skipped": skipped,
            "collection_failed": self._collection_failed,
            "exit_status": self._exit_status,
            "first_failing_node_ids": list(self._failing),
            "flaky_lines": list(self._flaky),
        }


def pytest_configure(config: pytest.Config) -> None:
    path = _path_from_env()
    if path is None:
        return
    if _is_xdist_worker(config):
        return
    if not _claim_path(path):
        return
    plugin = QualifyEvidencePlugin(path)
    config.pluginmanager.register(plugin, "sase-qualify-evidence")
