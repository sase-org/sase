"""Opt-in pytest plugin that records ambient config-cache readers.

A live poller in one xdist worker can warm or invalidate process-global config
state while another test is running. This plugin wraps the public
``sase.config.core`` cache entry points and attributes each off-thread call to
the nodeid that was running when the thread first appeared.

Enable with ``--sase-detect-config-readers``. The default JSON report is
``.pytest_cache/sase-config-readers.json``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime
import functools
import json
import os
from pathlib import Path
import shutil
import threading
import traceback
from typing import Any

import pytest

from sase.config import core as config_core
from sase.config.core import CONFIG_TOKEN_REFRESH_THREAD_NAME


WRAPPED_FUNCTION_NAMES = (
    "load_merged_config",
    "current_config_token",
    "clear_config_cache",
)
WORKER_OUTPUT_KEY = "sase_config_readers"
WORKER_DIR_ENV = "SASE_CONFIG_READER_WORKER_DIR"
DEFAULT_REPORT_PATH = ".pytest_cache/sase-config-readers.json"
BETWEEN_TESTS_NODEID = "<between-tests>"
PLUGIN_NAME = "sase-config-reader-probe"


class ConfigReaderProbe:
    """Collect off-thread config-cache reads without changing test outcomes."""

    def __init__(self, report_path: Path, *, worker_dir: Path) -> None:
        self._report_path = report_path
        self._worker_dir = worker_dir
        self._worker_id = os.environ.get("PYTEST_XDIST_WORKER")
        self._lock = threading.Lock()
        self._current_nodeid: str | None = None
        self._baseline_idents: set[int] = set()
        self._threads: dict[int, dict[str, Any]] = {}
        self._reads: dict[tuple[int, str, str], dict[str, Any]] = {}
        self._originals: dict[str, Callable[..., Any]] = {}
        self._wrappers: dict[str, Callable[..., Any]] = {}
        self._wrapped = False
        self._observed_tests = 0
        self._worker_order = 0
        self._worker_payloads: list[Mapping[str, object]] = []
        self._errors: list[str] = []
        self._final_report: Mapping[str, object] | None = None

    @property
    def _is_worker(self) -> bool:
        return bool(self._worker_id)

    @property
    def _public_worker_id(self) -> str:
        return self._worker_id or "controller"

    def install_wrappers(self) -> None:
        """Replace the public cache entry points with recording wrappers."""
        if self._wrapped:
            return
        for name in WRAPPED_FUNCTION_NAMES:
            original = getattr(config_core, name)
            wrapper = self._make_wrapper(name, original)
            self._originals[name] = original
            self._wrappers[name] = wrapper
            setattr(config_core, name, wrapper)
            _rebind_package_alias(name, original, wrapper)
        self._wrapped = True

    def uninstall_wrappers(self) -> None:
        """Restore the wrapped entry points when they are still our wrappers."""
        if not self._wrapped:
            return
        for name, original in self._originals.items():
            wrapper = self._wrappers[name]
            if getattr(config_core, name) is wrapper:
                setattr(config_core, name, original)
                _rebind_package_alias(name, wrapper, original)
        self._wrapped = False

    def mark_baseline_threads(self) -> None:
        """Ignore threads that already existed before any test ran."""
        with self._lock:
            self._baseline_idents.update(
                ident
                for ident in (thread.ident for thread in threading.enumerate())
                if ident is not None
            )

    def set_current_nodeid(self, nodeid: str | None) -> None:
        with self._lock:
            self._current_nodeid = nodeid

    def record_call(self, function: str) -> None:
        """Record one wrapped call when it comes from an ambient thread."""
        thread = threading.current_thread()
        if _ignored_reader_thread(thread):
            return
        ident = thread.ident
        if ident is None:
            return
        stack = "".join(traceback.format_stack(limit=20))
        with self._lock:
            nodeid = self._current_nodeid or BETWEEN_TESTS_NODEID
            self._remember_thread_locked(thread, nodeid)
            key = (ident, thread.name, function)
            record = self._reads.get(key)
            if record is None:
                origin = self._threads.get(ident, {}).get("originating_nodeid")
                record = {
                    "thread_ident": ident,
                    "thread_name": thread.name,
                    "function": function,
                    "call_count": 0,
                    "originating_nodeid": origin,
                    "nodeids": [],
                    "stack": stack,
                }
                self._reads[key] = record
            record["call_count"] += 1
            if nodeid not in record["nodeids"]:
                record["nodeids"].append(nodeid)
            if record["originating_nodeid"] is None and ident in self._threads:
                record["originating_nodeid"] = self._threads[ident][
                    "originating_nodeid"
                ]

    def observe_after_test(self, nodeid: str) -> None:
        """Attribute still-live non-main threads to *nodeid* or later victims."""
        live = [
            thread
            for thread in threading.enumerate()
            if thread is not threading.main_thread()
        ]
        with self._lock:
            for thread in live:
                self._remember_thread_locked(thread, nodeid)
                ident = thread.ident
                if ident is None:
                    continue
                info = self._threads.get(ident)
                if info is None:
                    continue
                origin = info["originating_nodeid"]
                if origin != nodeid and nodeid not in info["victim_nodeids"]:
                    info["victim_nodeids"].append(nodeid)
                info["last_seen_nodeid"] = nodeid

    def _remember_thread_locked(self, thread: threading.Thread, nodeid: str) -> None:
        ident = thread.ident
        if ident is None or ident in self._baseline_idents:
            return
        if ident in self._threads:
            return
        self._threads[ident] = {
            "thread_ident": ident,
            "thread_name": thread.name,
            "originating_nodeid": nodeid,
            "victim_nodeids": [],
            "last_seen_nodeid": nodeid,
            "is_refresh_worker": thread.name == CONFIG_TOKEN_REFRESH_THREAD_NAME,
        }

    def _make_wrapper(
        self, name: str, original: Callable[..., Any]
    ) -> Callable[..., Any]:
        @functools.wraps(original)
        def wrapper(*args: object, **kwargs: object) -> object:
            self.record_call(name)
            return original(*args, **kwargs)

        return wrapper

    def _ambient_read_records(self) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        for record in self._reads.values():
            origin = record.get("originating_nodeid")
            nodeids = [str(item) for item in record.get("nodeids") or ()]
            poisoning_nodeids = _poisoning_nodeids(
                str(origin) if origin is not None else None,
                nodeids,
            )
            records.append(
                {
                    "worker_id": self._public_worker_id,
                    "thread_ident": record["thread_ident"],
                    "thread_name": record["thread_name"],
                    "function": record["function"],
                    "call_count": record["call_count"],
                    "originating_nodeid": origin,
                    "nodeids": nodeids,
                    "poisoning_nodeids": poisoning_nodeids,
                    "stack": record["stack"],
                }
            )
        return records

    def _thread_records(
        self,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        live_idents = {
            ident
            for ident in (thread.ident for thread in threading.enumerate())
            if ident is not None
        }
        cross_test: list[dict[str, object]] = []
        refresh_workers: list[dict[str, object]] = []
        for info in self._threads.values():
            public = {
                "worker_id": self._public_worker_id,
                "thread_ident": info["thread_ident"],
                "thread_name": info["thread_name"],
                "originating_nodeid": info["originating_nodeid"],
                "victim_nodeids": list(info["victim_nodeids"]),
                "last_seen_nodeid": info["last_seen_nodeid"],
                "still_alive": info["thread_ident"] in live_idents,
            }
            if info["is_refresh_worker"]:
                refresh_workers.append(public)
            elif info["victim_nodeids"]:
                cross_test.append(public)
        return cross_test, refresh_workers

    def _payload(self) -> dict[str, object]:
        with self._lock:
            ambient_reads = self._ambient_read_records()
            cross_test, refresh_workers = self._thread_records()
            return {
                "worker_id": self._public_worker_id,
                "observed_tests": self._observed_tests,
                "ambient_reads": ambient_reads,
                "cross_test_threads": cross_test,
                "refresh_workers": refresh_workers,
                "errors": list(self._errors),
            }

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_protocol(
        self, item: pytest.Item, nextitem: pytest.Item | None
    ) -> Iterator[None]:
        self.set_current_nodeid(item.nodeid)
        self._observed_tests += 1
        self._worker_order += 1
        yield
        self.observe_after_test(item.nodeid)
        self.set_current_nodeid(None)

    def pytest_sessionstart(self, session: pytest.Session) -> None:
        self.mark_baseline_threads()

    def pytest_testnodedown(self, node: Any, error: object | None) -> None:
        payload = getattr(node, "workeroutput", {}).get(WORKER_OUTPUT_KEY)
        if isinstance(payload, Mapping):
            self._worker_payloads.append(payload)

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        if self._is_worker:
            write_error = self._write_worker_payload()
            if write_error is not None:
                self._errors.append(write_error)
            payload = self._payload()
            if hasattr(session.config, "workeroutput"):
                session.config.workeroutput[WORKER_OUTPUT_KEY] = payload
            return

        worker_file_payloads, read_errors = self._read_worker_payloads()
        self._errors.extend(read_errors)
        payload = self._payload()
        payloads = [payload, *worker_file_payloads]
        if not worker_file_payloads:
            payloads.extend(self._worker_payloads)
        report = _combine_payloads(payloads)
        if self._errors:
            report = _report_with_errors(report, self._errors)
        try:
            self._write_report(report)
        except OSError as error:
            self._errors.append(f"could not write report {self._report_path}: {error}")
            report = _report_with_errors(report, self._errors)
        self._final_report = report

    def pytest_terminal_summary(
        self, terminalreporter: pytest.TerminalReporter, exitstatus: int
    ) -> None:
        if self._is_worker:
            return
        if self._errors:
            terminalreporter.write_sep(
                "-",
                "sase config-reader probe error(s): " + "; ".join(self._errors),
            )
        report = self._final_report
        summary = _report_summary(report) or _read_report_summary(self._report_path)
        terminalreporter.write_sep(
            "-",
            (
                "sase config-reader probe: "
                f"{summary.get('ambient_reader_calls', 0)} ambient read(s) "
                f"from {summary.get('ambient_reader_records', 0)} record(s); "
                f"{summary.get('poisoning_reads', 0)} poisoning; "
                f"{summary.get('cross_test_live_threads', 0)} cross-test "
                f"thread(s); {summary.get('timed_out_refresh_workers', 0)} "
                f"refresh worker(s) still live after origin; "
                f"report={self._report_path}"
            ),
        )

    def _write_worker_payload(self) -> str | None:
        worker_id = self._worker_id
        if not worker_id:
            return None
        payload = self._payload()
        try:
            self._worker_dir.mkdir(parents=True, exist_ok=True)
            worker_path = self._worker_dir / f"{worker_id}.json"
            worker_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except OSError as error:
            return f"worker {worker_id} could not write payload: {error}"
        return None

    def _read_worker_payloads(self) -> tuple[list[Mapping[str, object]], list[str]]:
        if not self._worker_dir.is_dir():
            return [], []
        payloads: list[Mapping[str, object]] = []
        errors: list[str] = []
        for path in sorted(self._worker_dir.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                errors.append(f"could not read worker payload {path}: {error}")
                continue
            if isinstance(raw, Mapping):
                payloads.append(raw)
            else:
                errors.append(f"worker payload {path} is not a JSON object")
        return payloads, errors

    def _write_report(self, payload: Mapping[str, object]) -> None:
        self._report_path.parent.mkdir(parents=True, exist_ok=True)
        self._report_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--sase-detect-config-readers",
        action="store_true",
        default=False,
        help="Report non-main-thread readers of sase.config.core cache entry points.",
    )
    parser.addoption(
        "--sase-config-reader-report",
        default=DEFAULT_REPORT_PATH,
        help="JSON report path for --sase-detect-config-readers.",
    )


def register_config_reader_probe(config: pytest.Config) -> None:
    if not bool(config.getoption("--sase-detect-config-readers", default=False)):
        return
    if config.pluginmanager.hasplugin(PLUGIN_NAME):
        return
    report_path = _resolve_report_path(config)
    worker_dir = report_path.with_suffix(f"{report_path.suffix}.workers")
    if not os.environ.get("PYTEST_XDIST_WORKER"):
        shutil.rmtree(worker_dir, ignore_errors=True)
        os.environ[WORKER_DIR_ENV] = str(worker_dir)
    else:
        worker_dir = Path(os.environ.get(WORKER_DIR_ENV, str(worker_dir)))
    probe = ConfigReaderProbe(report_path, worker_dir=worker_dir)
    probe.install_wrappers()
    probe.mark_baseline_threads()
    config.pluginmanager.register(probe, PLUGIN_NAME)


def pytest_configure(config: pytest.Config) -> None:
    register_config_reader_probe(config)


def _ignored_reader_thread(thread: threading.Thread) -> bool:
    return (
        thread is threading.main_thread()
        or thread.name == CONFIG_TOKEN_REFRESH_THREAD_NAME
    )


def _poisoning_nodeids(origin: str | None, nodeids: list[str]) -> list[str]:
    return [nodeid for nodeid in nodeids if origin is None or nodeid != origin]


def _rebind_package_alias(name: str, expected_old: object, new: object) -> None:
    import sase.config as config_pkg

    if getattr(config_pkg, name, None) is expected_old:
        setattr(config_pkg, name, new)


def _combine_payloads(payloads: list[Mapping[str, object]]) -> dict[str, object]:
    ambient_reads: list[dict[str, object]] = []
    cross_test_threads: list[dict[str, object]] = []
    refresh_workers: list[dict[str, object]] = []
    errors: list[str] = []
    observed_tests = 0
    for payload in payloads:
        observed_tests += int(payload.get("observed_tests") or 0)
        raw_errors = payload.get("errors")
        if isinstance(raw_errors, list):
            errors.extend(str(error) for error in raw_errors)
        raw_reads = payload.get("ambient_reads")
        if isinstance(raw_reads, list):
            ambient_reads.extend(
                record for record in raw_reads if isinstance(record, dict)
            )
        raw_threads = payload.get("cross_test_threads")
        if isinstance(raw_threads, list):
            cross_test_threads.extend(
                record for record in raw_threads if isinstance(record, dict)
            )
        raw_refresh = payload.get("refresh_workers")
        if isinstance(raw_refresh, list):
            refresh_workers.extend(
                record for record in raw_refresh if isinstance(record, dict)
            )

    ambient_reads.sort(
        key=lambda record: (
            str(record.get("worker_id") or ""),
            str(record.get("thread_name") or ""),
            str(record.get("function") or ""),
            str(record.get("originating_nodeid") or ""),
        )
    )
    cross_test_threads.sort(
        key=lambda record: (
            str(record.get("worker_id") or ""),
            str(record.get("thread_name") or ""),
            str(record.get("originating_nodeid") or ""),
        )
    )
    refresh_workers.sort(
        key=lambda record: (
            str(record.get("worker_id") or ""),
            str(record.get("originating_nodeid") or ""),
        )
    )
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": {
            "observed_tests": observed_tests,
            "ambient_reader_calls": sum(
                int(record.get("call_count") or 0) for record in ambient_reads
            ),
            "ambient_reader_records": len(ambient_reads),
            "poisoning_reads": sum(
                1
                for record in ambient_reads
                if isinstance(record.get("poisoning_nodeids"), list)
                and record["poisoning_nodeids"]
            ),
            "cross_test_live_threads": len(cross_test_threads),
            "timed_out_refresh_workers": len(refresh_workers),
        },
        "ambient_reads": ambient_reads,
        "cross_test_threads": cross_test_threads,
        "refresh_workers": refresh_workers,
        "errors": errors,
    }


def _report_with_errors(
    report: Mapping[str, object], errors: list[str]
) -> dict[str, object]:
    merged_errors: list[str] = []
    raw_errors = report.get("errors")
    if isinstance(raw_errors, list):
        merged_errors.extend(str(error) for error in raw_errors)
    merged_errors.extend(str(error) for error in errors)
    return {**dict(report), "errors": list(dict.fromkeys(merged_errors))}


def _report_summary(payload: Mapping[str, object] | None) -> Mapping[str, object]:
    if not isinstance(payload, Mapping):
        return {}
    summary = payload.get("summary")
    return summary if isinstance(summary, Mapping) else {}


def _read_report_summary(path: Path) -> Mapping[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, Mapping):
        return {}
    summary = raw.get("summary")
    return summary if isinstance(summary, Mapping) else {}


def _resolve_report_path(config: pytest.Config) -> Path:
    raw_path = Path(str(config.getoption("--sase-config-reader-report")))
    if raw_path.is_absolute():
        return raw_path
    return Path(config.rootpath) / raw_path
