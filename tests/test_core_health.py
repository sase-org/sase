"""Tests for :mod:`sase.core.health` and the ``sase core health`` CLI."""

from __future__ import annotations

import json
import sys
import types
from typing import Any

import pytest

from sase.core.backend import (
    BACKEND_ENV_VAR,
    DUAL_RUN_ENV_VAR,
    RUST_EXTENSION_MODULE_NAME,
)
from sase.core.health import (
    HEALTH_ERROR,
    HEALTH_OK,
    BackendHealthReport,
    check_backend_health,
)


def _install_fake_extension(
    monkeypatch: pytest.MonkeyPatch,
    *,
    parse_query: Any = None,
    version: str | None = "0.0.0-fake",
    file_path: str | None = "/fake/sase_core_rs/__init__.py",
    omit_parse_query: bool = False,
) -> types.ModuleType:
    """Install a fake ``sase_core_rs`` in ``sys.modules`` for the test."""

    def _ok(_query: str) -> dict[str, Any]:
        return {"kind": "MetadataField", "field": "status", "value": "Ready"}

    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    if not omit_parse_query:
        fake.parse_query = parse_query if parse_query is not None else _ok  # type: ignore[attr-defined]
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


def test_python_mode_ok_without_extension(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BACKEND_ENV_VAR, "python")
    monkeypatch.delenv(DUAL_RUN_ENV_VAR, raising=False)
    _force_import_failure(monkeypatch, ImportError("no sase_core_rs"))

    report = check_backend_health()

    assert report.status == HEALTH_OK
    assert report.backend == "python"
    assert report.rust_required is False
    assert report.rust_extension_loaded is False
    assert report.probe_ok is False
    assert report.error is None


def test_python_mode_includes_extension_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(BACKEND_ENV_VAR, "python")
    monkeypatch.delenv(DUAL_RUN_ENV_VAR, raising=False)
    _install_fake_extension(monkeypatch)

    report = check_backend_health()

    assert report.status == HEALTH_OK
    assert report.backend == "python"
    assert report.rust_required is False
    assert report.rust_extension_loaded is True
    # Python mode still calls parse_query if the extension happens to be
    # importable — so users can confirm the wheel works while staying on
    # the Python escape hatch.
    assert report.probe_ok is True


def test_rust_mode_ok_with_extension(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")
    monkeypatch.delenv(DUAL_RUN_ENV_VAR, raising=False)
    _install_fake_extension(monkeypatch, version="1.2.3")

    report = check_backend_health()

    assert report.status == HEALTH_OK
    assert report.backend == "rust"
    assert report.rust_required is True
    assert report.rust_extension_loaded is True
    assert report.rust_extension_version == "1.2.3"
    assert report.rust_extension_path == "/fake/sase_core_rs/__init__.py"
    assert report.probe_ok is True
    assert report.error is None


def test_rust_mode_error_when_extension_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")
    monkeypatch.delenv(DUAL_RUN_ENV_VAR, raising=False)
    _force_import_failure(monkeypatch, ImportError("no sase_core_rs"))

    report = check_backend_health()

    assert report.status == HEALTH_ERROR
    assert report.rust_required is True
    assert report.rust_extension_loaded is False
    assert report.error_kind == "ImportError"
    assert report.error is not None
    assert RUST_EXTENSION_MODULE_NAME in report.error
    assert "SASE_CORE_BACKEND=python" in report.error


def test_rust_mode_misbuilt_extension_surfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-``ImportError`` import failures must not be silently swallowed."""
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")
    monkeypatch.delenv(DUAL_RUN_ENV_VAR, raising=False)
    _force_import_failure(
        monkeypatch, RuntimeError("symbol PyInit_sase_core_rs missing")
    )

    report = check_backend_health()

    assert report.status == HEALTH_ERROR
    assert report.rust_extension_loaded is False
    assert report.error_kind == "RuntimeError"
    assert report.error is not None
    assert "symbol PyInit_sase_core_rs missing" in report.error


def test_rust_mode_extension_missing_parse_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")
    monkeypatch.delenv(DUAL_RUN_ENV_VAR, raising=False)
    _install_fake_extension(monkeypatch, omit_parse_query=True)

    report = check_backend_health()

    assert report.status == HEALTH_ERROR
    assert report.rust_extension_loaded is True
    assert report.probe_ok is False
    assert report.error_kind == "AttributeError"
    assert report.error is not None
    assert "parse_query" in report.error


def test_rust_mode_parse_query_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")
    monkeypatch.delenv(DUAL_RUN_ENV_VAR, raising=False)

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


def test_dual_run_flag_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BACKEND_ENV_VAR, "python")
    monkeypatch.setenv(DUAL_RUN_ENV_VAR, "1")
    _install_fake_extension(monkeypatch)

    report = check_backend_health()

    assert report.dual_run is True
    assert report.status == HEALTH_OK


def test_report_to_dict_is_json_serializable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")
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
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")
    _install_fake_extension(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["sase", "core", "health"])

    code = _run_cli()
    out = capsys.readouterr().out

    assert code == 0
    assert "status: ok" in out
    assert "backend: rust" in out
    assert "rust extension loaded: yes" in out


def test_cli_health_json_ok(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")
    _install_fake_extension(monkeypatch, version="9.9.9")
    monkeypatch.setattr(sys, "argv", ["sase", "core", "health", "--json"])

    code = _run_cli()
    out = capsys.readouterr().out

    assert code == 0
    payload = json.loads(out)
    assert payload["status"] == "ok"
    assert payload["backend"] == "rust"
    assert payload["rust_extension_version"] == "9.9.9"


def test_cli_health_short_json_flag(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(BACKEND_ENV_VAR, "python")
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
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")
    _force_import_failure(monkeypatch, ImportError("no sase_core_rs"))
    monkeypatch.setattr(sys, "argv", ["sase", "core", "health", "-j"])

    code = _run_cli()
    out = capsys.readouterr().out

    assert code != 0
    payload = json.loads(out)
    assert payload["status"] == "error"
    assert payload["error_kind"] == "ImportError"
    assert RUST_EXTENSION_MODULE_NAME in payload["error"]


def test_cli_python_mode_does_not_require_extension(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(BACKEND_ENV_VAR, "python")
    _force_import_failure(monkeypatch, ImportError("no sase_core_rs"))
    monkeypatch.setattr(sys, "argv", ["sase", "core", "health", "-j"])

    code = _run_cli()
    out = capsys.readouterr().out

    assert code == 0
    payload = json.loads(out)
    assert payload["status"] == "ok"
    assert payload["backend"] == "python"
    assert payload["rust_extension_loaded"] is False


def test_cli_health_report_is_a_dataclass() -> None:
    """Guard against accidentally widening the report into a mutable type."""
    assert BackendHealthReport.__dataclass_params__.frozen  # type: ignore[attr-defined]
