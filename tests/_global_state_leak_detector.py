"""Opt-in pytest plugin for process-global state leaked between tests."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
from types import ModuleType
from typing import Any

import pytest


WORKER_OUTPUT_KEY = "sase_global_state_leaks"
WORKER_DIR_ENV = "SASE_GLOBAL_LEAK_WORKER_DIR"
DEFAULT_REPORT_PATH = ".pytest_cache/sase-global-leaks.json"

_PATTERN_TYPE = type(re.compile(""))
_ENV_KEYS_TO_IGNORE = frozenset(
    {
        "PYTEST_CURRENT_TEST",
        "SASE_PYTEST_SANDBOX_DIR",
    }
)


@dataclass(frozen=True)
class _ValueFingerprint:
    kind: str
    length: int | None
    digest: str
    preview: str
    entries: frozenset[str] = frozenset()
    sequence: tuple[str, ...] = ()

    def public(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": self.kind,
            "digest": self.digest,
            "preview": self.preview,
        }
        if self.length is not None:
            payload["len"] = self.length
        return payload


@dataclass(frozen=True)
class _CacheFingerprint:
    hits: int
    misses: int
    maxsize: int | None
    currsize: int

    def public(self) -> dict[str, int | None]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "maxsize": self.maxsize,
            "currsize": self.currsize,
        }


@dataclass(frozen=True)
class _Snapshot:
    globals: Mapping[str, _ValueFingerprint]
    caches: Mapping[str, _CacheFingerprint]
    environ: _ValueFingerprint
    sys_path: _ValueFingerprint
    cwd: str


@dataclass(frozen=True)
class _Change:
    kind: str
    name: str
    reason: str
    before: dict[str, object]
    after: dict[str, object]
    details: Mapping[str, object] | None = None

    def public(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": self.kind,
            "name": self.name,
            "reason": self.reason,
            "before": self.before,
            "after": self.after,
        }
        if self.details:
            payload["details"] = dict(self.details)
        return payload


@dataclass(frozen=True)
class _Diff:
    poisoning: tuple[_Change, ...]
    warming_counts: Mapping[str, int]
    cooling_counts: Mapping[str, int]
    invalidation_counts: Mapping[str, int]

    @property
    def warming_count(self) -> int:
        return sum(self.warming_counts.values())

    @property
    def cooling_count(self) -> int:
        return sum(self.cooling_counts.values())

    @property
    def invalidation_count(self) -> int:
        return sum(self.invalidation_counts.values())


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


def _snapshot() -> _Snapshot:
    global_values: dict[str, _ValueFingerprint] = {}
    caches: dict[str, _CacheFingerprint] = {}
    for module_name, module in _loaded_sase_modules():
        for attr_name, value in vars(module).items():
            if _is_private_global_name(attr_name):
                fingerprint = _global_fingerprint(value)
                if fingerprint is not None:
                    global_values[f"{module_name}.{attr_name}"] = fingerprint
            cache = _cache_fingerprint(value)
            if cache is not None:
                caches.setdefault(f"{module_name}.{attr_name}", cache)
    return _Snapshot(
        globals=global_values,
        caches=caches,
        environ=_fingerprint_environment(
            {
                key: value
                for key, value in os.environ.items()
                if key not in _ENV_KEYS_TO_IGNORE
            }
        ),
        sys_path=_fingerprint_list(sys.path),
        cwd=_safe_getcwd(),
    )


def _safe_getcwd() -> str:
    try:
        return os.getcwd()
    except FileNotFoundError:
        return "<deleted>"


def _loaded_sase_modules() -> list[tuple[str, ModuleType]]:
    modules: list[tuple[str, ModuleType]] = []
    for name, module in sys.modules.items():
        if name != "sase" and not name.startswith("sase."):
            continue
        if isinstance(module, ModuleType):
            modules.append((name, module))
    return sorted(modules, key=lambda item: item[0])


def _is_private_global_name(name: str) -> bool:
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def _global_fingerprint(value: object) -> _ValueFingerprint | None:
    if value is None:
        return _ValueFingerprint(
            kind="none",
            length=None,
            digest=_digest("None"),
            preview="None",
        )
    if isinstance(value, _PATTERN_TYPE):
        pattern = str(value.pattern)
        flags = int(value.flags)
        text = f"pattern={pattern!r};flags={flags}"
        return _ValueFingerprint(
            kind="re.Pattern",
            length=None,
            digest=_digest(text),
            preview=text,
        )
    if isinstance(value, dict):
        return _fingerprint_dict(value)
    if isinstance(value, set):
        return _fingerprint_set(value, kind="set")
    if isinstance(value, frozenset):
        return _fingerprint_set(value, kind="frozenset")
    if isinstance(value, list):
        return _fingerprint_list(value)
    return None


def _cache_fingerprint(value: object) -> _CacheFingerprint | None:
    cache_info = getattr(value, "cache_info", None)
    cache_clear = getattr(value, "cache_clear", None)
    if not callable(cache_info) or not callable(cache_clear):
        return None
    try:
        info = cache_info()
    except Exception:
        return None
    required = ("hits", "misses", "maxsize", "currsize")
    if not all(hasattr(info, name) for name in required):
        return None
    return _CacheFingerprint(
        hits=int(info.hits),
        misses=int(info.misses),
        maxsize=None if info.maxsize is None else int(info.maxsize),
        currsize=int(info.currsize),
    )


def _fingerprint_dict(value: Mapping[object, object]) -> _ValueFingerprint:
    entries = tuple(
        sorted(
            (f"{_safe_repr(key)} => {_safe_repr(entry_value)}")
            for key, entry_value in value.items()
        )
    )
    text = "\n".join(entries)
    return _ValueFingerprint(
        kind="dict",
        length=len(value),
        digest=_digest(text),
        preview=_preview(entries),
        entries=frozenset(entries),
    )


def _fingerprint_environment(value: Mapping[str, str]) -> _ValueFingerprint:
    entries = tuple(
        sorted(
            f"{key}={_digest(_safe_repr(entry_value))}"
            for key, entry_value in value.items()
        )
    )
    text = "\n".join(entries)
    return _ValueFingerprint(
        kind="environment",
        length=len(value),
        digest=_digest(text),
        preview=_preview(tuple(sorted(value))),
        entries=frozenset(entries),
    )


def _fingerprint_set(
    value: set[object] | frozenset[object], *, kind: str
) -> _ValueFingerprint:
    entries = tuple(sorted(_safe_repr(item) for item in value))
    text = "\n".join(entries)
    return _ValueFingerprint(
        kind=kind,
        length=len(value),
        digest=_digest(text),
        preview=_preview(entries),
        entries=frozenset(entries),
    )


def _fingerprint_list(value: list[object]) -> _ValueFingerprint:
    sequence = tuple(_safe_repr(item) for item in value)
    text = "\n".join(sequence)
    return _ValueFingerprint(
        kind="list",
        length=len(value),
        digest=_digest(text),
        preview=_preview(sequence),
        sequence=sequence,
    )


def _diff_snapshots(before: _Snapshot, after: _Snapshot) -> _Diff:
    poisoning: list[_Change] = []
    warming_counts: Counter[str] = Counter()
    cooling_counts: Counter[str] = Counter()
    invalidation_counts: Counter[str] = Counter()

    for name in sorted(set(before.globals) | set(after.globals)):
        before_value = before.globals.get(name)
        after_value = after.globals.get(name)
        classification = _classify_global_change(name, before_value, after_value)
        if classification == "none":
            continue
        if classification == "warming":
            warming_counts["global"] += 1
            continue
        if classification == "cooling":
            cooling_counts["global"] += 1
            continue
        if classification == "invalidation":
            invalidation_counts["global"] += 1
            continue
        poisoning.append(
            _Change(
                kind="global",
                name=name,
                reason=classification,
                before=_public_fingerprint(before_value),
                after=_public_fingerprint(after_value),
            )
        )

    for name in sorted(set(before.caches) | set(after.caches)):
        before_cache = before.caches.get(name)
        after_cache = after.caches.get(name)
        classification = _classify_cache_change(before_cache, after_cache)
        if classification == "none":
            continue
        if classification == "warming":
            warming_counts["cache"] += 1
            continue
        if classification == "cooling":
            cooling_counts["cache"] += 1
            continue
        if classification == "invalidation":
            invalidation_counts["cache"] += 1
            continue
        poisoning.append(
            _Change(
                kind="cache",
                name=name,
                reason=classification,
                before=_public_cache(before_cache),
                after=_public_cache(after_cache),
            )
        )

    ambient_changes, ambient_warming_counts, ambient_cooling_counts = _ambient_changes(
        before, after
    )
    poisoning.extend(ambient_changes)
    warming_counts.update(ambient_warming_counts)
    cooling_counts.update(ambient_cooling_counts)

    return _Diff(
        poisoning=tuple(poisoning),
        warming_counts=dict(warming_counts),
        cooling_counts=dict(cooling_counts),
        invalidation_counts=dict(invalidation_counts),
    )


def _classify_global_change(
    name: str,
    before: _ValueFingerprint | None,
    after: _ValueFingerprint | None,
) -> str:
    if before == after:
        return "none"
    if before is None:
        return "warming"
    if before.kind == "none" and after is None:
        return "cooling"
    if after is None:
        return "changed-to-untracked-or-deleted"
    if before.kind == "none" and after.kind != "none":
        return "warming"
    if _is_canonical_cold(after):
        return "cooling"
    if before.kind != after.kind:
        if _is_cache_like_global_name(name):
            return "invalidation"
        return "changed-kind"
    if _is_collection_warming(before, after):
        return "warming"
    if _is_cache_like_global_name(name):
        return "invalidation"
    return "changed-value"


def _is_cache_like_global_name(name: str) -> bool:
    attr_name = name.rsplit(".", maxsplit=1)[-1].lower()
    return (
        "cache" in attr_name
        or "memo" in attr_name
        or attr_name
        in {
            "_cleaned_artifact_dirs",
            "_context",
            "_last_saved_dismissed_generation",
        }
    )


def _is_collection_warming(
    before: _ValueFingerprint,
    after: _ValueFingerprint,
) -> bool:
    if before.kind == "dict" and after.kind == "dict":
        return before.entries.issubset(after.entries)
    if before.kind in {"set", "frozenset"} and after.kind == before.kind:
        return before.entries.issubset(after.entries)
    if before.kind == "list" and after.kind == "list":
        return after.sequence[: len(before.sequence)] == before.sequence
    return False


def _is_canonical_cold(value: _ValueFingerprint) -> bool:
    if value.kind == "none":
        return True
    if value.kind in {"dict", "set", "frozenset", "list"}:
        return value.length == 0
    return False


def _classify_cache_change(
    before: _CacheFingerprint | None,
    after: _CacheFingerprint | None,
) -> str:
    if before == after:
        return "none"
    if before is None:
        return "warming"
    if after is None:
        return "invalidation"
    if before.maxsize != after.maxsize:
        return "invalidation"
    if after.currsize == 0 and before.currsize > 0:
        return "cooling"
    if after.currsize < before.currsize:
        return "invalidation"
    if after.hits < before.hits or after.misses < before.misses:
        return "invalidation"
    return "warming"


def _ambient_changes(
    before: _Snapshot, after: _Snapshot
) -> tuple[list[_Change], Counter[str], Counter[str]]:
    changes: list[_Change] = []
    warming_counts: Counter[str] = Counter()
    cooling_counts: Counter[str] = Counter()
    if before.environ != after.environ:
        changes.append(
            _Change(
                kind="environment",
                name="os.environ",
                reason="environment-changed",
                before=_public_environment(before.environ),
                after=_public_environment(after.environ),
                details=_environment_delta(before.environ, after.environ),
            )
        )
    if before.sys_path != after.sys_path:
        classification = _classify_global_change(
            "sys.path", before.sys_path, after.sys_path
        )
        if classification == "warming":
            warming_counts["sys_path"] += 1
        elif classification == "cooling":
            cooling_counts["sys_path"] += 1
        else:
            changes.append(
                _Change(
                    kind="sys_path",
                    name="sys.path",
                    reason="sys-path-changed",
                    before=before.sys_path.public(),
                    after=after.sys_path.public(),
                )
            )
    if before.cwd != after.cwd:
        changes.append(
            _Change(
                kind="cwd",
                name="os.getcwd()",
                reason="working-directory-changed",
                before={"kind": "cwd", "value": before.cwd},
                after={"kind": "cwd", "value": after.cwd},
            )
        )
    return changes, warming_counts, cooling_counts


def _public_fingerprint(value: _ValueFingerprint | None) -> dict[str, object]:
    if value is None:
        return {"kind": "missing"}
    return value.public()


def _public_cache(value: _CacheFingerprint | None) -> dict[str, object]:
    if value is None:
        return {"kind": "missing"}
    payload: dict[str, object] = {"kind": "cache"}
    payload.update(value.public())
    return payload


def _combine_payloads(payloads: list[Mapping[str, object]]) -> dict[str, object]:
    records: list[dict[str, object]] = []
    warming_counts: Counter[str] = Counter()
    cooling_counts: Counter[str] = Counter()
    invalidation_counts: Counter[str] = Counter()
    errors: list[str] = []
    observed_tests = 0
    for payload in payloads:
        observed_tests += int(payload.get("observed_tests") or 0)
        raw_warming = payload.get("warming_counts")
        if isinstance(raw_warming, Mapping):
            warming_counts.update(
                {str(key): int(value) for key, value in raw_warming.items()}
            )
        raw_cooling = payload.get("cooling_counts")
        if isinstance(raw_cooling, Mapping):
            cooling_counts.update(
                {str(key): int(value) for key, value in raw_cooling.items()}
            )
        raw_invalidations = payload.get("invalidation_counts")
        if isinstance(raw_invalidations, Mapping):
            invalidation_counts.update(
                {str(key): int(value) for key, value in raw_invalidations.items()}
            )
        raw_errors = payload.get("errors")
        if isinstance(raw_errors, list):
            errors.extend(str(error) for error in raw_errors)
        raw_records = payload.get("records")
        if isinstance(raw_records, list):
            records.extend(record for record in raw_records if isinstance(record, dict))

    records.sort(
        key=lambda record: (
            str(record.get("worker_id") or ""),
            int(record.get("worker_order") or 0),
            str(record.get("nodeid") or ""),
        )
    )
    poisoning_changes = sum(
        len(record.get("changes") or [])
        for record in records
        if isinstance(record.get("changes"), list)
    )
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": {
            "observed_tests": observed_tests,
            "tests_with_poisoning": len(records),
            "poisoning_changes": poisoning_changes,
            "warming_changes_filtered": sum(warming_counts.values()),
            "warming_by_kind": dict(sorted(warming_counts.items())),
            "cooling_changes_filtered": sum(cooling_counts.values()),
            "cooling_by_kind": dict(sorted(cooling_counts.items())),
            "invalidation_changes_filtered": sum(invalidation_counts.values()),
            "invalidation_by_kind": dict(sorted(invalidation_counts.items())),
        },
        "poisoning": records,
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


def _public_environment(value: _ValueFingerprint) -> dict[str, object]:
    return {
        "kind": "environment",
        "digest": value.digest,
        "len": value.length or 0,
    }


def _environment_delta(
    before: _ValueFingerprint, after: _ValueFingerprint
) -> dict[str, object]:
    before_entries = _entry_digest_by_key(before)
    after_entries = _entry_digest_by_key(after)
    before_keys = set(before_entries)
    after_keys = set(after_entries)
    common_keys = before_keys & after_keys
    return {
        "added_keys": sorted(after_keys - before_keys),
        "removed_keys": sorted(before_keys - after_keys),
        "changed_keys": sorted(
            key for key in common_keys if before_entries[key] != after_entries[key]
        ),
    }


def _entry_digest_by_key(value: _ValueFingerprint) -> dict[str, str]:
    entries: dict[str, str] = {}
    for entry in value.entries:
        key, separator, digest = entry.partition("=")
        if separator:
            entries[key] = digest
    return entries


def _safe_repr(value: object) -> str:
    try:
        return repr(value)
    except Exception as error:
        return f"<unrepresentable {type(value).__name__}: {error}>"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "backslashreplace")).hexdigest()[:16]


def _preview(entries: tuple[str, ...]) -> str:
    if not entries:
        return ""
    preview = ", ".join(entries[:3])
    if len(entries) > 3:
        preview = f"{preview}, ..."
    return preview[:240]
