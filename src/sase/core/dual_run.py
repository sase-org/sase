"""Dual-run comparison logging for the sase.core facade.

When ``SASE_CORE_DUAL_RUN=1`` is set, dispatched operations call both the
Python and Rust implementations on every invocation, compare the results, and
append one JSONL record per call to ``~/.sase/perf/core_dual_run.jsonl``.

The Python result is always returned to callers so dual-run never changes
TUI/CLI behavior. Errors raised by the Rust implementation are captured into
the record (``error_class``, ``match=False``) and do not propagate.

Record shape (one JSON object per line):

```
{
  "operation": "parse_project_file",
  "source_path": "/abs/path/foo.gp",
  "input_hash": "sha256:...",
  "python_duration_ms": 12.3,
  "rust_duration_ms": 4.5,
  "match": true,
  "first_diff_path": null,
  "error_class": null,
  "timestamp": "2026-04-29T12:34:56Z",
  "schema_version": 1
}
```
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import traceback
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DUAL_RUN_LOG_FILENAME = "core_dual_run.jsonl"
DUAL_RUN_LOG_SUBDIR = "perf"
DUAL_RUN_LOG_OVERRIDE_ENV_VAR = "SASE_CORE_DUAL_RUN_LOG"
DUAL_RUN_RECORD_SCHEMA_VERSION = 1


# pyvision: tests/test_core_dual_run.py
@dataclass
class DualRunRecord:
    """One per-call comparison record written to the dual-run JSONL log."""

    operation: str
    input_hash: str
    python_duration_ms: float
    rust_duration_ms: float | None
    match: bool
    source_path: str | None = None
    first_diff_path: str | None = None
    error_class: str | None = None
    timestamp: str = ""
    schema_version: int = DUAL_RUN_RECORD_SCHEMA_VERSION
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dict (drops empty ``extra`` for compactness)."""
        data = asdict(self)
        if not data.get("extra"):
            data.pop("extra", None)
        return data


# pyvision: tests/test_core_dual_run.py
def get_dual_run_log_path() -> Path:
    """Return the JSONL log path, honoring the override env var."""
    override = os.environ.get(DUAL_RUN_LOG_OVERRIDE_ENV_VAR)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".sase" / DUAL_RUN_LOG_SUBDIR / DUAL_RUN_LOG_FILENAME


# pyvision: tests/test_core_dual_run.py
def append_dual_run_record(record: DualRunRecord, log_path: Path | None = None) -> Path:
    """Append a record to the JSONL log, creating parent dirs as needed.

    Returns the path written to.
    """
    target = log_path or get_dual_run_log_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record.to_json_dict(), separators=(",", ":"), sort_keys=True)
    with target.open("a", encoding="utf-8") as fp:
        fp.write(line)
        fp.write("\n")
    return target


# pyvision: tests/test_core_dual_run.py
def compute_input_hash(*parts: Any) -> str:
    """Compute a stable ``sha256:<hex>`` digest over arbitrary input parts.

    Bytes are hashed directly; strings encode as UTF-8; everything else is
    fed through :func:`repr`. Designed to be cheap and reproducible across
    runs, not cryptographically meaningful.
    """
    h = hashlib.sha256()
    for part in parts:
        if isinstance(part, bytes):
            h.update(part)
        elif isinstance(part, str):
            h.update(part.encode("utf-8"))
        else:
            h.update(repr(part).encode("utf-8"))
        h.update(b"\x00")
    return f"sha256:{h.hexdigest()}"


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# pyvision: tests/test_core_dual_run.py
def find_first_diff_path(
    python_result: Any, rust_result: Any, prefix: str = ""
) -> str | None:
    """Return a JSON-pointer-ish path to the first divergence, or ``None``.

    Recurses into dicts and lists. Falls back to equality on primitives.
    Truncates to the first difference encountered (depth-first by key order
    for dicts, by index for lists).
    """
    if python_result == rust_result:
        return None
    if isinstance(python_result, dict) and isinstance(rust_result, dict):
        py_keys = list(python_result.keys())
        rust_keys = list(rust_result.keys())
        if py_keys != rust_keys:
            return prefix or "."
        for k in py_keys:
            sub = find_first_diff_path(
                python_result[k], rust_result[k], f"{prefix}/{k}"
            )
            if sub is not None:
                return sub
        return prefix or "."
    if isinstance(python_result, list) and isinstance(rust_result, list):
        if len(python_result) != len(rust_result):
            return prefix or "."
        for i, (py_v, rs_v) in enumerate(zip(python_result, rust_result, strict=False)):
            sub = find_first_diff_path(py_v, rs_v, f"{prefix}/{i}")
            if sub is not None:
                return sub
        return prefix or "."
    return prefix or "."


def run_with_comparison[T](
    *,
    operation: str,
    python_impl: Callable[..., T],
    rust_impl: Callable[..., T],
    args: tuple = (),
    kwargs: dict | None = None,
    source_path: str | None = None,
    log_path: Path | None = None,
    comparator: Callable[[Any, Any], str | None] | None = None,
    json_serializer: Callable[[Any], Any] | None = None,
) -> T:
    """Run both impls, log a comparison record, return the Python result.

    Args:
        operation: short stable name written into the record.
        python_impl: source-of-truth implementation; its result is returned.
        rust_impl: candidate implementation; exceptions are captured.
        args, kwargs: positional / keyword arguments forwarded to both impls.
        source_path: optional file path attribution for the record.
        log_path: override path for the JSONL log (default: env-aware path).
        comparator: optional ``(python, rust) -> first_diff_path | None``.
            Defaults to :func:`find_first_diff_path` after passing both
            results through ``json_serializer``.
        json_serializer: optional projector to a JSON-safe shape used for
            comparison. Defaults to identity (the comparator must handle
            the raw types).

    The Python result is always returned. The Rust result is discarded after
    comparison so calling code remains identical to the Python-only path.
    """
    call_kwargs = kwargs or {}

    py_start = time.perf_counter()
    python_result = python_impl(*args, **call_kwargs)
    py_duration_ms = (time.perf_counter() - py_start) * 1000.0

    rust_duration_ms: float | None = None
    rust_result: Any = None
    error_class: str | None = None
    error_detail: str | None = None
    try:
        rs_start = time.perf_counter()
        rust_result = rust_impl(*args, **call_kwargs)
        rust_duration_ms = (time.perf_counter() - rs_start) * 1000.0
    except Exception as exc:  # noqa: BLE001 - we record any rust-side failure
        error_class = type(exc).__name__
        error_detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()

    if error_class is not None:
        match = False
        first_diff_path: str | None = None
    else:
        py_view = json_serializer(python_result) if json_serializer else python_result
        rs_view = json_serializer(rust_result) if json_serializer else rust_result
        if comparator is not None:
            first_diff_path = comparator(py_view, rs_view)
        else:
            first_diff_path = find_first_diff_path(py_view, rs_view)
        match = first_diff_path is None

    record = DualRunRecord(
        operation=operation,
        source_path=source_path,
        input_hash=compute_input_hash(operation, args, sorted(call_kwargs.items())),
        python_duration_ms=round(py_duration_ms, 4),
        rust_duration_ms=(
            round(rust_duration_ms, 4) if rust_duration_ms is not None else None
        ),
        match=match,
        first_diff_path=first_diff_path,
        error_class=error_class,
        timestamp=_utc_now_iso(),
        extra={"error_detail": error_detail} if error_detail else {},
    )
    append_dual_run_record(record, log_path=log_path)
    return python_result
