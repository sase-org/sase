"""Tests for ``sase.core.parser_facade``.

Phase 8D rewired :func:`parse_project_bytes` to call ``sase_core_rs``
directly through :func:`sase.core.rust.require_rust_binding`. The legacy
``dispatch`` plumbing and the Python tempfile-bridge fallback have been
deleted, so the test surface here pins the new contract:

- the facade returns the Rust binding's output, rehydrated into typed
  wire records;
- a missing or stale Rust extension raises a clean
  :class:`ImportError` / :class:`AttributeError` instead of silently
  switching to a Python path.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from sase.ace.changespec.models import ChangeSpec
from sase.ace.changespec.parser import parse_project_file as raw_parse_project_file
from sase.core import parser_facade
from sase.core.rust import RUST_EXTENSION_MODULE_NAME
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
    # File path on each record reflects the caller-supplied path; the Rust
    # binding sets it from the ``file_path`` argument it receives.
    assert all(w.file_path == str(sample_project) for w in wires)


def test_parse_project_bytes_uses_rust_binding(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The facade calls the registered ``sase_core_rs.parse_project_bytes``.

    Replaces the real Rust binding with a fake that records arguments and
    returns parity output through the Python parser, exercising the
    dict -> :class:`ChangeSpecWire` rehydration code path the facade owns
    after Phase 8D.
    """
    calls: list[tuple[str, bytes]] = []

    def fake_parse(path: str, data: bytes) -> list[dict]:
        calls.append((path, data))
        return python_wire_records_as_dicts(path, data)

    install_fake_rust_module(monkeypatch, fake_parse)

    raw_bytes = sample_project.read_bytes()
    wires = parser_facade.parse_project_bytes(str(sample_project), raw_bytes)

    assert len(calls) == 1
    assert calls[0][0] == str(sample_project)
    assert calls[0][1] == raw_bytes
    assert [w.name for w in wires] == ["example", "child"]
    assert all(isinstance(w, ChangeSpecWire) for w in wires)
    # The schema version round-trips through the dict adapter unchanged.
    assert all(w.schema_version == CHANGESPEC_WIRE_SCHEMA_VERSION for w in wires)


def test_parse_project_bytes_missing_extension_raises_importerror(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the wheel is gone, the facade raises :class:`ImportError`."""
    monkeypatch.delitem(sys.modules, RUST_EXTENSION_MODULE_NAME, raising=False)

    def fail(name: str) -> object:
        raise ImportError(f"No module named {name!r}")

    monkeypatch.setattr("importlib.import_module", fail)
    with pytest.raises(ImportError, match=RUST_EXTENSION_MODULE_NAME):
        parser_facade.parse_project_bytes(
            str(sample_project), sample_project.read_bytes()
        )


def test_parse_project_bytes_stale_wheel_raises_attributeerror(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wheel without the binding raises :class:`AttributeError` naming the op."""
    import types

    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)
    with pytest.raises(AttributeError, match="parse_project_bytes"):
        parser_facade.parse_project_bytes(
            str(sample_project), sample_project.read_bytes()
        )


def test_parse_project_bytes_rust_error_surfaces(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Rust-side ``ValueError`` propagates instead of silently falling back."""

    def boom(_path: str, _data: bytes) -> list[dict]:
        raise ValueError("encoding: invalid UTF-8 (bad.gp)")

    install_fake_rust_module(monkeypatch, boom)

    raw_bytes = sample_project.read_bytes()
    with pytest.raises(ValueError, match="encoding"):
        parser_facade.parse_project_bytes(str(sample_project), raw_bytes)
