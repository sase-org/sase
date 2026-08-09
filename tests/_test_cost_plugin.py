"""Opt-in pytest plugin for the suite cost-attribution lane."""

from __future__ import annotations

import contextvars
import functools
import importlib
import inspect
import json
import os
import resource
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from tests._test_cost import write_cost_record
from tests._test_selection_timings import file_for_nodeid


TEST_COST_RECORD_ENV = "SASE_TEST_COST_RECORD"
WORKER_OUTPUT_KEY = "sase_test_cost"
RSS_SAMPLE_ITEM_STRIDE = 100

_CURRENT_FILE: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "sase_test_cost_current_file", default=None
)


class _AsyncContextProxy:
    """Time an async context manager's enter and exit without changing it."""

    def __init__(self, recorder: CostRecorder, wrapped: Any) -> None:
        self._recorder = recorder
        self._wrapped = wrapped

    async def __aenter__(self) -> Any:
        with self._recorder.measure("textual_app_run_test_enter"):
            return await self._wrapped.__aenter__()

    async def __aexit__(self, *args: Any) -> Any:
        with self._recorder.measure("textual_app_run_test_exit"):
            return await self._wrapped.__aexit__(*args)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped, name)


class CostRecorder:
    """Collect per-worker and per-test-file cost attribution."""

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
        self._worker_id = os.environ.get("PYTEST_XDIST_WORKER") or "controller"
        self._pid = os.getpid()
        self._lock = threading.Lock()
        self._files: dict[str, dict[str, Any]] = {}
        self._causes: dict[str, dict[str, float | int]] = {}
        self._worker_payloads: list[Mapping[str, Any]] = []
        self._patches: list[tuple[Any, str, Any]] = []
        self._session_wall_start = time.perf_counter()
        self._session_cpu_start = time.process_time()
        self._collection_wall_start: float | None = None
        self._collection_cpu_start: float | None = None
        self._collection_wall_seconds = 0.0
        self._collection_cpu_seconds = 0.0
        self._items_since_rss_sample = 0
        self._rss_samples_kib: list[int] = []
        self._install_patches()
        self._record_rss_sample()

    @property
    def files(self) -> dict[str, dict[str, Any]]:
        return self._normalised_files()

    @property
    def causes(self) -> dict[str, dict[str, float | int]]:
        with self._lock:
            return {
                name: {"count": int(payload["count"]), "seconds": payload["seconds"]}
                for name, payload in self._causes.items()
            }

    def measure(self, cause: str) -> Iterator[None]:
        recorder = self

        class _Measurement:
            def __enter__(self) -> None:
                self._start = time.perf_counter()

            def __exit__(
                self,
                _exc_type: type[BaseException] | None,
                _exc: BaseException | None,
                _tb: Any,
            ) -> None:
                recorder._record_cause(cause, time.perf_counter() - self._start)

        return _Measurement()

    def _file_metrics(self, path: str) -> dict[str, Any]:
        return self._files.setdefault(
            path,
            {
                "node_count": 0,
                "wall_seconds": 0.0,
                "cpu_seconds": 0.0,
                "causes": {},
            },
        )

    def _record_item(
        self, path: str, *, wall_seconds: float, cpu_seconds: float
    ) -> None:
        with self._lock:
            metrics = self._file_metrics(path)
            metrics["node_count"] += 1
            metrics["wall_seconds"] += max(wall_seconds, 0.0)
            metrics["cpu_seconds"] += max(cpu_seconds, 0.0)

    def _record_collect_report(self, path: str, *, wall_seconds: float) -> None:
        with self._lock:
            metrics = self._file_metrics(path)
            metrics["wall_seconds"] += max(wall_seconds, 0.0)

    def _record_cause(self, cause: str, seconds: float) -> None:
        seconds = max(seconds, 0.0)
        path = _CURRENT_FILE.get()
        with self._lock:
            cause_metrics = self._causes.setdefault(cause, {"count": 0, "seconds": 0.0})
            cause_metrics["count"] = int(cause_metrics["count"]) + 1
            cause_metrics["seconds"] = float(cause_metrics["seconds"]) + seconds
            if path is None:
                return
            file_metrics = self._file_metrics(path)
            file_causes = file_metrics["causes"]
            file_cause = file_causes.setdefault(cause, {"count": 0, "seconds": 0.0})
            file_cause["count"] = int(file_cause["count"]) + 1
            file_cause["seconds"] = float(file_cause["seconds"]) + seconds

    def _patch(self, target: Any, name: str, replacement: Any) -> None:
        original = getattr(target, name)
        self._patches.append((target, name, original))
        setattr(target, name, replacement)

    def _install_patches(self) -> None:
        self._patch_subprocess()
        self._patch_function("gettext", "find", "gettext_find")
        self._patch_function("yaml", "load", "yaml_load")
        self._patch_function("sase.main.parser", "create_parser", "parser_create")
        self._patch_function(
            "sase.config.core", "load_merged_config", "config_load_merged"
        )
        self._patch_async_method("textual.pilot", "Pilot", "pause", self._pause_cause)
        self._patch_async_function(
            "textual._wait", "wait_for_idle", "textual_wait_for_idle"
        )
        self._patch_async_function(
            "sase.ace.testing.settle", "settle_pilot", "ace_settle_pilot"
        )
        self._patch_async_function(
            "sase.ace.testing.settle",
            "pause_until_cpu_idle",
            "ace_pause_until_cpu_idle",
        )
        self._patch_async_function(
            "sase.ace.testing", "settle_pilot", "ace_settle_pilot"
        )
        self._patch_async_function(
            "sase.ace.testing",
            "pause_until_cpu_idle",
            "ace_pause_until_cpu_idle",
        )
        self._patch_app_run_test()
        self._patch_async_method(
            "sase.ace.testing.ace_page", "AcePage", "__aenter__", "ace_page_enter"
        )
        self._patch_async_method(
            "sase.ace.testing.ace_page", "AcePage", "__aexit__", "ace_page_exit"
        )

    def _patch_function(self, module_name: str, attr: str, cause: str) -> None:
        try:
            module = importlib.import_module(module_name)
            original = getattr(module, attr)
        except (ImportError, AttributeError):
            return

        if inspect.iscoroutinefunction(original):
            self._patch_async_callable(module, attr, original, cause)
        else:
            self._patch_sync_callable(module, attr, original, cause)

    def _patch_sync_callable(
        self,
        target: Any,
        attr: str,
        original: Callable[..., Any],
        cause: str,
    ) -> None:
        @functools.wraps(original)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with self.measure(cause):
                return original(*args, **kwargs)

        self._patch(target, attr, wrapper)

    def _patch_async_callable(
        self,
        target: Any,
        attr: str,
        original: Callable[..., Any],
        cause: str | Callable[[tuple[Any, ...], dict[str, Any]], str],
    ) -> None:
        @functools.wraps(original)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            measured = cause(args, kwargs) if callable(cause) else cause
            with self.measure(measured):
                return await original(*args, **kwargs)

        self._patch(target, attr, wrapper)

    def _patch_async_function(self, module_name: str, attr: str, cause: str) -> None:
        try:
            module = importlib.import_module(module_name)
            original = getattr(module, attr)
        except (ImportError, AttributeError):
            return
        if not inspect.iscoroutinefunction(original):
            return
        self._patch_async_callable(module, attr, original, cause)

    def _patch_async_method(
        self,
        module_name: str,
        class_name: str,
        attr: str,
        cause: str | Callable[[tuple[Any, ...], dict[str, Any]], str],
    ) -> None:
        try:
            module = importlib.import_module(module_name)
            cls = getattr(module, class_name)
            original = getattr(cls, attr)
        except (ImportError, AttributeError):
            return
        if not inspect.iscoroutinefunction(original):
            return
        self._patch_async_callable(cls, attr, original, cause)

    def _patch_app_run_test(self) -> None:
        try:
            module = importlib.import_module("textual.app")
            cls = module.App
            original = cls.run_test
        except (ImportError, AttributeError):
            return

        @functools.wraps(original)
        def wrapper(app: Any, *args: Any, **kwargs: Any) -> Any:
            return _AsyncContextProxy(self, original(app, *args, **kwargs))

        self._patch(cls, "run_test", wrapper)

    def _patch_subprocess(self) -> None:
        try:
            module = importlib.import_module("subprocess")
            original_run = module.run
            original_popen = module.Popen
        except (ImportError, AttributeError):
            return

        in_run: contextvars.ContextVar[bool] = contextvars.ContextVar(
            "sase_test_cost_in_subprocess_run", default=False
        )

        @functools.wraps(original_run)
        def run_wrapper(*args: Any, **kwargs: Any) -> Any:
            token = in_run.set(True)
            try:
                with self.measure("subprocess_run"):
                    return original_run(*args, **kwargs)
            finally:
                in_run.reset(token)

        recorder = self

        class TimedPopen(original_popen):  # type: ignore[misc, valid-type]
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                if in_run.get():
                    super().__init__(*args, **kwargs)
                    return
                with recorder.measure("subprocess_popen"):
                    super().__init__(*args, **kwargs)

        TimedPopen.__name__ = getattr(original_popen, "__name__", "Popen")
        TimedPopen.__qualname__ = getattr(original_popen, "__qualname__", "Popen")
        TimedPopen.__module__ = getattr(original_popen, "__module__", "subprocess")

        self._patch(module, "run", run_wrapper)
        self._patch(module, "Popen", TimedPopen)

    @staticmethod
    def _pause_cause(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
        delay = kwargs.get("delay")
        if len(args) >= 2:
            delay = args[1]
        return "pilot_pause_none" if delay is None else "pilot_pause_delay"

    @pytest.hookimpl(hookwrapper=True)
    def pytest_collection(self, session: pytest.Session) -> Iterator[None]:
        self._collection_wall_start = time.perf_counter()
        self._collection_cpu_start = time.process_time()
        yield
        if self._collection_wall_start is None or self._collection_cpu_start is None:
            return
        self._collection_wall_seconds += (
            time.perf_counter() - self._collection_wall_start
        )
        self._collection_cpu_seconds += time.process_time() - self._collection_cpu_start
        self._record_rss_sample()

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_protocol(
        self, item: pytest.Item, nextitem: pytest.Item | None
    ) -> Iterator[None]:
        path = file_for_nodeid(item.nodeid)
        if path is None:
            yield
            return
        token = _CURRENT_FILE.set(path)
        wall_start = time.perf_counter()
        cpu_start = time.process_time()
        try:
            yield
        finally:
            _CURRENT_FILE.reset(token)
            self._record_item(
                path,
                wall_seconds=time.perf_counter() - wall_start,
                cpu_seconds=time.process_time() - cpu_start,
            )
            self._items_since_rss_sample += 1
            if self._items_since_rss_sample >= RSS_SAMPLE_ITEM_STRIDE:
                self._items_since_rss_sample = 0
                self._record_rss_sample()

    @pytest.hookimpl(trylast=True)
    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        path = file_for_nodeid(str(getattr(report, "nodeid", "")))
        duration = float(getattr(report, "duration", 0.0) or 0.0)
        if path is not None and duration > 0:
            self._record_collect_report(path, wall_seconds=duration)

    def pytest_testnodedown(self, node: Any, error: object | None) -> None:
        payload = getattr(node, "workeroutput", {}).get(WORKER_OUTPUT_KEY)
        if isinstance(payload, Mapping):
            self._worker_payloads.append(payload)

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        payload = self._worker_payload()
        if hasattr(session.config, "workeroutput"):
            session.config.workeroutput[WORKER_OUTPUT_KEY] = payload
            self._restore_patches()
            return
        payloads: list[Mapping[str, Any]] = [payload, *self._worker_payloads]
        try:
            write_cost_record(
                self._directory,
                payloads,
                mode=self._mode,
                worker_count=self._worker_count,
            )
        except OSError:
            pass
        finally:
            self._restore_patches()

    def _restore_patches(self) -> None:
        for target, name, original in reversed(self._patches):
            setattr(target, name, original)
        self._patches.clear()

    def _peak_rss_kib(self) -> int:
        peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        if sys.platform == "darwin":
            return peak // 1024
        return peak

    def _current_rss_kib(self) -> int:
        if sys.platform.startswith("linux"):
            try:
                statm = Path(f"/proc/{self._pid}/statm").read_text(encoding="utf-8")
                pages = int(statm.split()[1])
                return pages * os.sysconf("SC_PAGE_SIZE") // 1024
            except (OSError, IndexError, ValueError):
                pass
        return self._peak_rss_kib()

    def _record_rss_sample(self) -> None:
        sample = self._current_rss_kib()
        with self._lock:
            self._rss_samples_kib.append(sample)

    def _rss_curve(self, peak_rss_kib: int) -> dict[str, int]:
        with self._lock:
            samples = [sample for sample in self._rss_samples_kib if sample > 0]
        if not samples:
            samples = [peak_rss_kib]
        peak_rss_kib = max(peak_rss_kib, max(samples, default=0))
        ordered = sorted(samples)
        midpoint = len(ordered) // 2
        if len(ordered) % 2:
            median = ordered[midpoint]
        else:
            median = (ordered[midpoint - 1] + ordered[midpoint]) // 2
        return {
            "start": samples[0],
            "post_collection": samples[1] if len(samples) > 1 else samples[-1],
            "median": median,
            "peak": peak_rss_kib,
            "sample_count": len(samples),
        }

    def _normalised_files(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {
                path: {
                    "node_count": int(metrics["node_count"]),
                    "wall_seconds": round(float(metrics["wall_seconds"]), 6),
                    "cpu_seconds": round(float(metrics["cpu_seconds"]), 6),
                    "causes": {
                        name: {
                            "count": int(cause["count"]),
                            "seconds": round(float(cause["seconds"]), 6),
                        }
                        for name, cause in sorted(metrics["causes"].items())
                    },
                }
                for path, metrics in sorted(self._files.items())
            }

    def _worker_payload(self) -> dict[str, Any]:
        wall_seconds = time.perf_counter() - self._session_wall_start
        cpu_seconds = time.process_time() - self._session_cpu_start
        self._record_rss_sample()
        rss_curve = self._rss_curve(self._peak_rss_kib())
        peak_rss_kib = rss_curve["peak"]
        return {
            "worker_id": self._worker_id,
            "pid": self._pid,
            "wall_seconds": round(wall_seconds, 6),
            "cpu_seconds": round(cpu_seconds, 6),
            "collection_seconds": round(self._collection_wall_seconds, 6),
            "collection_cpu_seconds": round(self._collection_cpu_seconds, 6),
            "peak_rss_kib": peak_rss_kib,
            "rss_curve_kib": rss_curve,
            "causes": self.causes,
            "files": self.files,
        }


def _recorder_request() -> dict[str, Any] | None:
    raw = os.environ.get(TEST_COST_RECORD_ENV)
    if not raw:
        return None
    try:
        request = json.loads(raw)
    except ValueError:
        return None
    return request if isinstance(request, dict) and request.get("directory") else None


def pytest_configure(config: pytest.Config) -> None:
    request = _recorder_request()
    if request is None:
        return
    raw_workers = request.get("worker_count")
    recorder = CostRecorder(
        Path(str(request["directory"])),
        mode=str(request.get("mode") or "unknown"),
        worker_count=int(raw_workers) if isinstance(raw_workers, int) else None,
    )
    config.pluginmanager.register(recorder, "sase-test-cost-recorder")
