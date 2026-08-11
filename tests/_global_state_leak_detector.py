"""Opt-in pytest plugin for process-global state leaked between tests.

The implementation is split across ``tests._global_state_leaks``.  Imports below
deliberately preserve the original module surface for the plugin's focused tests.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator, Mapping
import json
import os
from pathlib import Path
import shutil
from typing import Any

import pytest

from tests._global_state_leaks.diffing import (
    _ambient_changes,
    _classify_cache_change,
    _classify_global_change,
    _diff_snapshots,
    _entry_digest_by_key,
    _environment_delta,
    _is_cache_like_global_name,
    _is_canonical_cold,
    _is_collection_warming,
    _public_cache,
    _public_environment,
    _public_fingerprint,
)
from tests._global_state_leaks.fingerprints import (
    _ENV_KEYS_TO_IGNORE,
    _PATTERN_TYPE,
    _cache_fingerprint,
    _digest,
    _fingerprint_dict,
    _fingerprint_environment,
    _fingerprint_list,
    _fingerprint_set,
    _global_fingerprint,
    _is_private_global_name,
    _loaded_sase_modules,
    _preview,
    _safe_getcwd,
    _safe_repr,
    _snapshot,
)
from tests._global_state_leaks.models import (
    _CacheFingerprint,
    _Change,
    _Diff,
    _Snapshot,
    _ValueFingerprint,
)
from tests._global_state_leaks.reporting import (
    _combine_payloads,
    _read_report_summary,
    _report_summary,
    _report_with_errors,
)


WORKER_OUTPUT_KEY = "sase_global_state_leaks"
WORKER_DIR_ENV = "SASE_GLOBAL_LEAK_WORKER_DIR"
DEFAULT_REPORT_PATH = ".pytest_cache/sase-global-leaks.json"


class GlobalStateLeakDetector:
    """Collect per-test global-state poisoning without changing test outcomes."""

    def __init__(
        self,
        report_path: Path,
        *,
        worker_dir: Path,
        fail_on_poison: bool = False,
    ) -> None:
        self._report_path = report_path
        self._worker_dir = worker_dir
        self._worker_id = os.environ.get("PYTEST_XDIST_WORKER")
        self._fail_on_poison = fail_on_poison
        self._records: list[dict[str, object]] = []
        self._warming_counts: Counter[str] = Counter()
        self._cooling_counts: Counter[str] = Counter()
        self._invalidation_counts: Counter[str] = Counter()
        self._observed_tests = 0
        self._worker_order = 0
        self._worker_payloads: list[Mapping[str, object]] = []
        self._errors: list[str] = []
        self._final_report: Mapping[str, object] | None = None
        self._blocking_failure = False

    @property
    def _is_worker(self) -> bool:
        return bool(self._worker_id)

    @property
    def _public_worker_id(self) -> str:
        return self._worker_id or "controller"

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_protocol(
        self, item: pytest.Item, nextitem: pytest.Item | None
    ) -> Iterator[None]:
        before = _snapshot()
        yield
        after = _snapshot()
        self._observed_tests += 1
        self._worker_order += 1

        diff = _diff_snapshots(before, after)
        self._warming_counts.update(diff.warming_counts)
        self._cooling_counts.update(diff.cooling_counts)
        self._invalidation_counts.update(diff.invalidation_counts)
        if diff.poisoning:
            self._records.append(
                {
                    "worker_id": self._public_worker_id,
                    "worker_order": self._worker_order,
                    "nodeid": item.nodeid,
                    "changes": [change.public() for change in diff.poisoning],
                }
            )

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
            self._maybe_fail_session(session, payload)
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
        self._maybe_fail_session(session, report)

    def pytest_terminal_summary(
        self, terminalreporter: pytest.TerminalReporter, exitstatus: int
    ) -> None:
        if self._is_worker:
            return
        if self._errors:
            terminalreporter.write_sep(
                "-",
                "sase global leak detector error(s): " + "; ".join(self._errors),
            )
        report = _report_summary(self._final_report) or _read_report_summary(
            self._report_path
        )
        terminalreporter.write_sep(
            "-",
            (
                "sase global leak detector: "
                f"{report.get('poisoning_changes', 0)} poisoning change(s) across "
                f"{report.get('tests_with_poisoning', 0)} test(s); "
                f"{report.get('warming_changes_filtered', 0)} warming mutation(s) "
                f"filtered; {report.get('cooling_changes_filtered', 0)} cooling "
                f"mutation(s) filtered; "
                f"{report.get('invalidation_changes_filtered', 0)} "
                f"invalidation(s) filtered; report={self._report_path}"
            ),
        )
        if self._blocking_failure:
            terminalreporter.write_sep(
                "-",
                "sase global leak detector blocking gate failed",
            )

    def _payload(self) -> dict[str, object]:
        return {
            "worker_id": self._public_worker_id,
            "observed_tests": self._observed_tests,
            "warming_counts": dict(self._warming_counts),
            "cooling_counts": dict(self._cooling_counts),
            "invalidation_counts": dict(self._invalidation_counts),
            "records": self._records,
            "errors": list(self._errors),
        }

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

    def _maybe_fail_session(
        self, session: pytest.Session, payload: Mapping[str, object]
    ) -> None:
        if not self._fail_on_poison:
            return
        summary = _report_summary(payload)
        poison_count = int(summary.get("poisoning_changes") or 0)
        errors = payload.get("errors")
        has_errors = isinstance(errors, list) and bool(errors)
        if poison_count == 0 and not has_errors:
            return
        self._blocking_failure = True
        session.exitstatus = int(pytest.ExitCode.TESTS_FAILED)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--sase-detect-global-leaks",
        action="store_true",
        default=False,
        help="Report process-global state left changed by individual tests.",
    )
    parser.addoption(
        "--sase-fail-on-global-leaks",
        action="store_true",
        default=False,
        help="Fail the pytest run when global-state poisoning is detected.",
    )
    parser.addoption(
        "--sase-global-leak-report",
        default=DEFAULT_REPORT_PATH,
        help="JSON report path for --sase-detect-global-leaks.",
    )


def register_global_state_leak_detector(config: pytest.Config) -> None:
    if not bool(config.getoption("--sase-detect-global-leaks", default=False)):
        return
    plugin_name = "sase-global-state-leak-detector"
    if config.pluginmanager.hasplugin(plugin_name):
        return
    report_path = _resolve_report_path(config)
    worker_dir = report_path.with_suffix(f"{report_path.suffix}.workers")
    if not os.environ.get("PYTEST_XDIST_WORKER"):
        shutil.rmtree(worker_dir, ignore_errors=True)
        os.environ[WORKER_DIR_ENV] = str(worker_dir)
    else:
        worker_dir = Path(os.environ.get(WORKER_DIR_ENV, str(worker_dir)))
    config.pluginmanager.register(
        GlobalStateLeakDetector(
            report_path,
            worker_dir=worker_dir,
            fail_on_poison=bool(
                config.getoption("--sase-fail-on-global-leaks", default=False)
            ),
        ),
        plugin_name,
    )


def pytest_configure(config: pytest.Config) -> None:
    register_global_state_leak_detector(config)


def _resolve_report_path(config: pytest.Config) -> Path:
    raw_path = Path(str(config.getoption("--sase-global-leak-report")))
    if raw_path.is_absolute():
        return raw_path
    return Path(config.rootpath) / raw_path
