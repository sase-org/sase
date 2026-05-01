"""Tests for :mod:`sase.core.health` and the ``sase core health`` CLI."""

from __future__ import annotations

import json
import sys
import types
from typing import Any

import pytest

from sase.core.health import (
    HEALTH_ERROR,
    HEALTH_OK,
    BackendHealthReport,
    check_backend_health,
)
from sase.core.rust import RUST_EXTENSION_MODULE_NAME


def _install_fake_extension(
    monkeypatch: pytest.MonkeyPatch,
    *,
    parse_query: Any = None,
    agent_launch_wire_schema_version: Any = None,
    plan_agent_launch_fanout: Any = None,
    version: str | None = "0.0.0-fake",
    file_path: str | None = "/fake/sase_core_rs/__init__.py",
    omit_parse_query: bool = False,
    omit_agent_launch_wire_schema_version: bool = False,
    omit_plan_agent_launch_fanout: bool = False,
) -> types.ModuleType:
    """Install a fake ``sase_core_rs`` in ``sys.modules`` for the test."""

    def _ok(_query: str) -> dict[str, Any]:
        return {"kind": "MetadataField", "field": "status", "value": "Ready"}

    def _schema_version() -> int:
        return 1

    def _launch_plan(prompt: str, launch_kind: str | None = None) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "launch_kind": launch_kind or "single",
            "slots": [
                {
                    "prompt": prompt,
                    "launch_kind": launch_kind or "single",
                    "slot_index": 0,
                }
            ],
            "fanout_sleep_seconds": 0.0,
            "requires_sequential_naming_wait": False,
        }

    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    if not omit_parse_query:
        fake.parse_query = parse_query if parse_query is not None else _ok  # type: ignore[attr-defined]
    if not omit_agent_launch_wire_schema_version:
        fake.agent_launch_wire_schema_version = (  # type: ignore[attr-defined]
            agent_launch_wire_schema_version
            if agent_launch_wire_schema_version is not None
            else _schema_version
        )
    if not omit_plan_agent_launch_fanout:
        fake.plan_agent_launch_fanout = (  # type: ignore[attr-defined]
            plan_agent_launch_fanout
            if plan_agent_launch_fanout is not None
            else _launch_plan
        )
    if version is not None:
        fake.__version__ = version  # type: ignore[attr-defined]
    if file_path is not None:
        fake.__file__ = file_path
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)
    return fake


def _force_import_failure(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    """Make ``sase_core_rs`` import raise ``exc`` (clears any cached module)."""
    monkeypatch.delitem(sys.modules, RUST_EXTENSION_MODULE_NAME, raising=False)
    real_import = __import__

    def _raising(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == RUST_EXTENSION_MODULE_NAME:
            raise exc
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _raising)


def test_health_ok_with_extension(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_extension(monkeypatch, version="1.2.3")

    report = check_backend_health()

    assert report.status == HEALTH_OK
    assert report.rust_extension_loaded is True
    assert report.rust_extension_version == "1.2.3"
    assert report.rust_extension_path == "/fake/sase_core_rs/__init__.py"
    assert report.probe_ok is True
    assert report.extras["probes"]["parse_query"] is True
    assert report.extras["probes"]["agent_launch_wire_schema_version"] is True
    assert report.extras["probes"]["plan_agent_launch_fanout"] is True
    assert report.error is None


def test_health_error_when_extension_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_import_failure(monkeypatch, ImportError("no sase_core_rs"))

    report = check_backend_health()

    assert report.status == HEALTH_ERROR
    assert report.rust_extension_loaded is False
    assert report.error_kind == "ImportError"
    assert report.error is not None
    assert RUST_EXTENSION_MODULE_NAME in report.error


def test_health_misbuilt_extension_surfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-``ImportError`` import failures must not be silently swallowed."""
    _force_import_failure(
        monkeypatch, RuntimeError("symbol PyInit_sase_core_rs missing")
    )

    report = check_backend_health()

    assert report.status == HEALTH_ERROR
    assert report.rust_extension_loaded is False
    assert report.error_kind == "RuntimeError"
    assert report.error is not None
    assert "symbol PyInit_sase_core_rs missing" in report.error


def test_health_extension_missing_parse_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_extension(monkeypatch, omit_parse_query=True)

    report = check_backend_health()

    assert report.status == HEALTH_ERROR
    assert report.rust_extension_loaded is True
    assert report.probe_ok is False
    assert report.error_kind == "AttributeError"
    assert report.error is not None
    assert "parse_query" in report.error


def test_health_parse_query_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def _broken(_query: str) -> Any:
        raise ValueError("invalid token")

    _install_fake_extension(monkeypatch, parse_query=_broken)

    report = check_backend_health()

    assert report.status == HEALTH_ERROR
    assert report.rust_extension_loaded is True
    assert report.probe_ok is False
    assert report.error_kind == "ValueError"
    assert report.error is not None
    assert "invalid token" in report.error


def test_health_extension_missing_launch_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_extension(monkeypatch, omit_plan_agent_launch_fanout=True)

    report = check_backend_health()

    assert report.status == HEALTH_ERROR
    assert report.rust_extension_loaded is True
    assert report.probe_ok is False
    assert report.error_kind == "AttributeError"
    assert report.error is not None
    assert "plan_agent_launch_fanout" in report.error
    assert report.extras["probes"]["parse_query"] is True
    assert report.extras["probes"]["plan_agent_launch_fanout"] is False


def test_report_to_dict_is_json_serializable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_extension(monkeypatch)

    report = check_backend_health()
    payload = report.to_dict()

    assert isinstance(payload, dict)
    assert payload["status"] == HEALTH_OK
    assert json.dumps(payload)  # round-trips


# -------------------- CLI --------------------


def _run_cli() -> int:
    from sase.main.entry import main

    try:
        main()
    except SystemExit as exc:
        return int(exc.code or 0)
    raise AssertionError("sase.main.entry.main() returned without sys.exit()")


def test_cli_health_human_ok(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _install_fake_extension(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["sase", "core", "health"])

    code = _run_cli()
    out = capsys.readouterr().out

    assert code == 0
    assert "status: ok" in out
    assert "rust extension loaded: yes" in out


def test_cli_health_json_ok(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _install_fake_extension(monkeypatch, version="9.9.9")
    monkeypatch.setattr(sys, "argv", ["sase", "core", "health", "--json"])

    code = _run_cli()
    out = capsys.readouterr().out

    assert code == 0
    payload = json.loads(out)
    assert payload["status"] == "ok"
    assert payload["rust_extension_version"] == "9.9.9"


def test_cli_health_short_json_flag(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _install_fake_extension(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["sase", "core", "health", "-j"])

    code = _run_cli()
    out = capsys.readouterr().out

    assert code == 0
    payload = json.loads(out)
    assert payload["status"] == "ok"


def test_cli_health_rust_missing_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _force_import_failure(monkeypatch, ImportError("no sase_core_rs"))
    monkeypatch.setattr(sys, "argv", ["sase", "core", "health", "-j"])

    code = _run_cli()
    out = capsys.readouterr().out

    assert code != 0
    payload = json.loads(out)
    assert payload["status"] == "error"
    assert payload["error_kind"] == "ImportError"
    assert RUST_EXTENSION_MODULE_NAME in payload["error"]


def test_cli_health_report_is_a_dataclass() -> None:
    """Guard against accidentally widening the report into a mutable type."""
    assert BackendHealthReport.__dataclass_params__.frozen  # type: ignore[attr-defined]
