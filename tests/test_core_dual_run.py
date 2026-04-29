"""Tests for the sase.core dual-run JSONL logging."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.core.backend import (
    BACKEND_ENV_VAR,
    DUAL_RUN_ENV_VAR,
    dispatch,
)
from sase.core.dual_run import (
    DUAL_RUN_LOG_OVERRIDE_ENV_VAR,
    DUAL_RUN_RECORD_SCHEMA_VERSION,
    DualRunRecord,
    append_dual_run_record,
    compute_input_hash,
    find_first_diff_path,
    get_dual_run_log_path,
    run_with_comparison,
)


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def test_get_dual_run_log_path_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DUAL_RUN_LOG_OVERRIDE_ENV_VAR, raising=False)
    monkeypatch.setattr(Path, "home", lambda: Path("/fake-home"))
    assert get_dual_run_log_path() == Path("/fake-home/.sase/perf/core_dual_run.jsonl")


def test_get_dual_run_log_path_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "custom.jsonl"
    monkeypatch.setenv(DUAL_RUN_LOG_OVERRIDE_ENV_VAR, str(target))
    assert get_dual_run_log_path() == target


def test_append_dual_run_record_creates_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dir" / "log.jsonl"
    record = DualRunRecord(
        operation="op",
        input_hash="sha256:abc",
        python_duration_ms=1.0,
        rust_duration_ms=2.0,
        match=True,
        timestamp="2026-04-29T00:00:00Z",
    )
    append_dual_run_record(record, log_path=target)
    assert target.exists()
    [row] = _read_jsonl(target)
    assert row["schema_version"] == DUAL_RUN_RECORD_SCHEMA_VERSION
    assert row["operation"] == "op"
    assert row["match"] is True
    assert row["python_duration_ms"] == 1.0
    assert row["rust_duration_ms"] == 2.0
    assert row["error_class"] is None


def test_compute_input_hash_is_stable() -> None:
    h1 = compute_input_hash("op", (1, "two"), [("k", "v")])
    h2 = compute_input_hash("op", (1, "two"), [("k", "v")])
    assert h1 == h2
    assert h1.startswith("sha256:")
    h3 = compute_input_hash("op", (1, "two"), [("k", "v2")])
    assert h1 != h3


def test_find_first_diff_path_match() -> None:
    assert find_first_diff_path({"a": [1, 2]}, {"a": [1, 2]}) is None


def test_find_first_diff_path_dict() -> None:
    diff = find_first_diff_path({"a": 1, "b": 2}, {"a": 1, "b": 3})
    assert diff == "/b"


def test_find_first_diff_path_list_index() -> None:
    diff = find_first_diff_path({"xs": [1, 2, 3]}, {"xs": [1, 9, 3]})
    assert diff == "/xs/1"


def test_find_first_diff_path_keys_differ() -> None:
    diff = find_first_diff_path({"a": 1}, {"b": 1})
    assert diff == "."


def test_run_with_comparison_logs_match(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log = tmp_path / "match.jsonl"
    monkeypatch.setenv(DUAL_RUN_LOG_OVERRIDE_ENV_VAR, str(log))

    def py(x: int) -> int:
        return x * 2

    def rust(x: int) -> int:
        return x * 2

    result = run_with_comparison(
        operation="double",
        python_impl=py,
        rust_impl=rust,
        args=(3,),
        source_path="src.gp",
    )
    assert result == 6

    [row] = _read_jsonl(log)
    assert row["operation"] == "double"
    assert row["match"] is True
    assert row["first_diff_path"] is None
    assert row["error_class"] is None
    assert row["source_path"] == "src.gp"
    assert row["timestamp"].endswith("Z")


def test_run_with_comparison_logs_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log = tmp_path / "mismatch.jsonl"
    monkeypatch.setenv(DUAL_RUN_LOG_OVERRIDE_ENV_VAR, str(log))

    def py() -> dict:
        return {"a": 1, "b": 2}

    def rust() -> dict:
        return {"a": 1, "b": 99}

    result = run_with_comparison(operation="diverge", python_impl=py, rust_impl=rust)
    assert result == {"a": 1, "b": 2}  # python result is returned

    [row] = _read_jsonl(log)
    assert row["match"] is False
    assert row["first_diff_path"] == "/b"


def test_run_with_comparison_captures_rust_exception(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log = tmp_path / "rust_err.jsonl"
    monkeypatch.setenv(DUAL_RUN_LOG_OVERRIDE_ENV_VAR, str(log))

    def py() -> int:
        return 7

    def rust() -> int:
        raise RuntimeError("rust says no")

    result = run_with_comparison(operation="boom", python_impl=py, rust_impl=rust)
    assert result == 7

    [row] = _read_jsonl(log)
    assert row["match"] is False
    assert row["error_class"] == "RuntimeError"


def test_run_with_comparison_uses_json_serializer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A custom serializer can compare otherwise-incomparable types."""
    log = tmp_path / "ser.jsonl"
    monkeypatch.setenv(DUAL_RUN_LOG_OVERRIDE_ENV_VAR, str(log))

    class Wrapper:
        def __init__(self, v: int) -> None:
            self.v = v

    def py() -> Wrapper:
        return Wrapper(5)

    def rust() -> Wrapper:
        return Wrapper(5)

    result = run_with_comparison(
        operation="wrap",
        python_impl=py,
        rust_impl=rust,
        json_serializer=lambda w: {"v": w.v},
    )
    assert isinstance(result, Wrapper)
    [row] = _read_jsonl(log)
    assert row["match"] is True


def test_dual_run_dispatch_returns_python_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log = tmp_path / "dispatch.jsonl"
    monkeypatch.setenv(DUAL_RUN_LOG_OVERRIDE_ENV_VAR, str(log))
    monkeypatch.setenv(DUAL_RUN_ENV_VAR, "1")
    monkeypatch.delenv(BACKEND_ENV_VAR, raising=False)

    def py(x: int) -> int:
        return x + 1

    def rust(x: int) -> int:
        return x + 100  # diverges; Python wins

    result = dispatch(
        operation="inc",
        python_impl=py,
        rust_impl=rust,
        args=(10,),
        source_path="cs.gp",
    )
    assert result == 11

    [row] = _read_jsonl(log)
    assert row["match"] is False
    assert row["operation"] == "inc"
    assert row["source_path"] == "cs.gp"


def test_dual_run_dispatch_no_op_without_rust_impl(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log = tmp_path / "no_rust.jsonl"
    monkeypatch.setenv(DUAL_RUN_LOG_OVERRIDE_ENV_VAR, str(log))
    monkeypatch.setenv(DUAL_RUN_ENV_VAR, "1")
    monkeypatch.delenv(BACKEND_ENV_VAR, raising=False)

    def py() -> int:
        return 99

    assert dispatch(operation="solo", python_impl=py) == 99
    assert not log.exists()
