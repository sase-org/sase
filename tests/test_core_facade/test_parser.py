"""Tests for ``sase.core.parser_facade``."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from sase.ace.changespec.models import ChangeSpec
from sase.ace.changespec.parser import parse_project_file as raw_parse_project_file
from sase.ace.changespec.parser import parse_project_file_python
from sase.core import parser_facade
from sase.core.backend import (
    BACKEND_ENV_VAR,
    RUST_EXTENSION_MODULE_NAME,
    RustBackendUnavailableError,
)
from sase.core.dual_run import DUAL_RUN_LOG_OVERRIDE_ENV_VAR
from sase.core.wire import CHANGESPEC_WIRE_SCHEMA_VERSION, ChangeSpecWire

from tests.test_core_facade._helpers import (
    install_fake_rust_module,
    python_wire_records_as_dicts,
)


def test_parse_project_file_matches_python_impl(sample_project: Path) -> None:
    via_facade = parser_facade.parse_project_file(str(sample_project))
    direct = raw_parse_project_file(str(sample_project))
    assert [cs.name for cs in via_facade] == [cs.name for cs in direct]
    assert all(isinstance(cs, ChangeSpec) for cs in via_facade)


def test_parse_project_bytes_returns_wire_records(sample_project: Path) -> None:
    raw_bytes = sample_project.read_bytes()
    wires = parser_facade.parse_project_bytes(str(sample_project), raw_bytes)
    assert all(isinstance(w, ChangeSpecWire) for w in wires)
    assert [w.name for w in wires] == ["example", "child"]
    # File path should be the caller-provided one even though parsing went
    # through a temp file under the hood.
    assert all(w.file_path == str(sample_project) for w in wires)


def test_parse_project_file_rust_backend_still_uses_python_parser(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")
    via_facade = parser_facade.parse_project_file(str(sample_project))
    direct = parse_project_file_python(str(sample_project))
    assert [cs.name for cs in via_facade] == [cs.name for cs in direct]
    assert all(isinstance(cs, ChangeSpec) for cs in via_facade)


def test_parse_project_bytes_rust_unavailable_keeps_python(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No Rust extension + explicit Python backend = Python path, unchanged behavior."""
    monkeypatch.setenv(BACKEND_ENV_VAR, "python")
    monkeypatch.delitem(sys.modules, RUST_EXTENSION_MODULE_NAME, raising=False)

    def fail(name: str) -> object:
        raise ImportError(f"No module named {name!r}")

    monkeypatch.setattr("importlib.import_module", fail)
    raw_bytes = sample_project.read_bytes()
    wires = parser_facade.parse_project_bytes(str(sample_project), raw_bytes)
    assert [w.name for w in wires] == ["example", "child"]


def test_parse_project_bytes_rust_backend_uses_rust_impl(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``SASE_CORE_BACKEND=rust`` calls the registered Rust binding.

    The fake binding records its arguments so we can assert no fallback to
    the Python path happened.
    """
    calls: list[tuple[str, bytes]] = []

    def fake_parse(path: str, data: bytes) -> list[dict]:
        calls.append((path, data))
        # The fake produces parity output by routing through Python so we
        # exercise the dict -> ChangeSpecWire rehydration code path.
        return python_wire_records_as_dicts(path, data)

    install_fake_rust_module(monkeypatch, fake_parse)
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")

    raw_bytes = sample_project.read_bytes()
    wires = parser_facade.parse_project_bytes(str(sample_project), raw_bytes)

    assert len(calls) == 1
    assert calls[0][0] == str(sample_project)
    assert calls[0][1] == raw_bytes
    assert [w.name for w in wires] == ["example", "child"]
    assert all(isinstance(w, ChangeSpecWire) for w in wires)
    # The schema version round-trips through the dict adapter unchanged.
    assert all(w.schema_version == CHANGESPEC_WIRE_SCHEMA_VERSION for w in wires)


def test_parse_project_bytes_rust_backend_missing_binding_raises_cleanly(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")

    with pytest.raises(RustBackendUnavailableError, match="parse_project_bytes"):
        parser_facade.parse_project_bytes(
            str(sample_project),
            sample_project.read_bytes(),
        )


def test_parse_project_bytes_dual_run_logs_comparison(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Dual-run runs both impls, logs one record, returns Python output."""
    log_path = tmp_path / "core_dual_run.jsonl"
    monkeypatch.setenv(DUAL_RUN_LOG_OVERRIDE_ENV_VAR, str(log_path))
    monkeypatch.setenv("SASE_CORE_DUAL_RUN", "1")

    rust_calls: list[tuple[str, bytes]] = []

    def fake_parse(path: str, data: bytes) -> list[dict]:
        rust_calls.append((path, data))
        return python_wire_records_as_dicts(path, data)

    install_fake_rust_module(monkeypatch, fake_parse)

    raw_bytes = sample_project.read_bytes()
    wires = parser_facade.parse_project_bytes(str(sample_project), raw_bytes)

    # Python output is what the caller sees, even under dual-run.
    assert all(isinstance(w, ChangeSpecWire) for w in wires)
    assert [w.name for w in wires] == ["example", "child"]
    assert len(rust_calls) == 1

    records = [
        json.loads(line) for line in log_path.read_text().splitlines() if line.strip()
    ]
    assert len(records) == 1
    rec = records[0]
    assert rec["operation"] == "parse_project_bytes"
    assert rec["match"] is True
    assert rec["error_class"] is None
    assert rec["source_path"] == str(sample_project)


def test_parse_project_bytes_rust_error_surfaces(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Rust-side ``ValueError`` propagates instead of silently falling back."""

    def boom(_path: str, _data: bytes) -> list[dict]:
        raise ValueError("encoding: invalid UTF-8 (bad.gp)")

    install_fake_rust_module(monkeypatch, boom)
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")

    raw_bytes = sample_project.read_bytes()
    with pytest.raises(ValueError, match="encoding"):
        parser_facade.parse_project_bytes(str(sample_project), raw_bytes)
