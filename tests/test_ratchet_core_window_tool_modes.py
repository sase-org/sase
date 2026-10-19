"""Report/check/apply mode tests for ratchet_core_pin."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import ModuleType

import pytest

from tests._ratchet_core_window_tool_helpers import PLATFORMS
from tests._ratchet_core_window_tool_helpers import fake_core_lag as _fake_core_lag
from tests._ratchet_core_window_tool_helpers import fake_ensure as _fake_ensure
from tests._ratchet_core_window_tool_helpers import load_tool as _load_tool
from tests._ratchet_core_window_tool_helpers import (
    successful_lock_runner as _successful_lock_runner,
)
from tests._ratchet_core_window_tool_helpers import write_project as _write_project


pytestmark = pytest.mark.contract


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    return _load_tool()


def test_report_only_prints_exact_diff_without_writing(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject, uv_lock = _write_project(tmp_path)
    before_pyproject = pyproject.read_text(encoding="utf-8")
    before_uv_lock = uv_lock.read_text(encoding="utf-8")
    monkeypatch.setattr(tool, "ensure_core", _fake_ensure(tool, "0.22.0"))
    monkeypatch.setattr(tool, "_run_uv_lock", _successful_lock_runner(tool))

    code = tool.main(
        [
            "--pyproject",
            str(pyproject),
            "--uv-lock",
            str(uv_lock),
            "--report-only",
        ]
    )

    assert code == tool.EXIT_RATCHET
    assert pyproject.read_text(encoding="utf-8") == before_pyproject
    assert uv_lock.read_text(encoding="utf-8") == before_uv_lock
    out = capsys.readouterr().out
    assert "PINNED(0.22.0, files=" in out
    assert "sase-core-rs ratchet >=0.21.3,<0.22.0 -> ==0.22.0" in out
    assert "--- a/pyproject.toml" in out
    assert "--- a/uv.lock" in out
    assert '+    "sase-core-rs==0.22.0",' in out
    assert '+version = "0.22.0"' in out


def test_check_reports_pending_without_running_uv_lock(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject, uv_lock = _write_project(tmp_path)
    monkeypatch.setattr(tool, "ensure_core", _fake_ensure(tool, "0.22.0"))

    def _unexpected_lock_runner(
        _project_dir: Path,
        _target: object,
    ) -> subprocess.CompletedProcess[str]:
        raise AssertionError("check mode must not refresh uv.lock")

    monkeypatch.setattr(tool, "_run_uv_lock", _unexpected_lock_runner)

    code = tool.main(
        ["--pyproject", str(pyproject), "--uv-lock", str(uv_lock), "--check"]
    )

    assert code == tool.EXIT_RATCHET
    assert "pending" in capsys.readouterr().out


def test_default_mode_applies_pyproject_and_guarded_lock_update(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject, uv_lock = _write_project(tmp_path)
    monkeypatch.setattr(tool, "ensure_core", _fake_ensure(tool, "0.22.0"))
    monkeypatch.setattr(tool, "_run_uv_lock", _successful_lock_runner(tool))

    code = tool.main(["--pyproject", str(pyproject), "--uv-lock", str(uv_lock)])

    assert code == tool.EXIT_RATCHET
    assert '    "sase-core-rs==0.22.0",' in pyproject.read_text(encoding="utf-8")
    assert 'version = "0.22.0"' in uv_lock.read_text(encoding="utf-8")
    assert "applied" in capsys.readouterr().out


def test_default_mode_accepts_expanded_core_artifact_set(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyproject, uv_lock = _write_project(tmp_path)
    monkeypatch.setattr(tool, "ensure_core", _fake_ensure(tool, "0.22.0"))
    expanded_platforms = PLATFORMS + ("manylinux_2_28_ppc64le",)
    monkeypatch.setattr(
        tool,
        "_run_uv_lock",
        _successful_lock_runner(tool, platforms=expanded_platforms),
    )

    code = tool.main(["--pyproject", str(pyproject), "--uv-lock", str(uv_lock)])

    assert code == tool.EXIT_RATCHET
    assert "sase_core_rs-0.22.0-cp312-abi3-manylinux_2_28_ppc64le.whl" in (
        uv_lock.read_text(encoding="utf-8")
    )


def test_idempotent_when_declared_floor_is_newest(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject, uv_lock = _write_project(tmp_path, specifier="==0.21.3")
    monkeypatch.setattr(tool, "ensure_core", _fake_ensure(tool, "0.21.3"))

    def _unexpected_lock_runner(
        _project_dir: Path,
        _target: object,
    ) -> subprocess.CompletedProcess[str]:
        raise AssertionError("idempotent mode must not refresh uv.lock")

    monkeypatch.setattr(tool, "_run_uv_lock", _unexpected_lock_runner)

    code = tool.main(["--pyproject", str(pyproject), "--uv-lock", str(uv_lock)])

    assert code == tool.EXIT_OK
    out = capsys.readouterr().out
    assert "PINNED(0.21.3, files=" in out
    assert "already matches" in out


def test_downgrade_is_refused_without_writing(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject, uv_lock = _write_project(tmp_path)
    before_pyproject = pyproject.read_text(encoding="utf-8")
    before_uv_lock = uv_lock.read_text(encoding="utf-8")
    monkeypatch.setattr(tool, "ensure_core", _fake_ensure(tool, "0.20.0"))

    code = tool.main(["--pyproject", str(pyproject), "--uv-lock", str(uv_lock)])

    assert code == tool.EXIT_COULD_NOT_DETERMINE
    assert pyproject.read_text(encoding="utf-8") == before_pyproject
    assert uv_lock.read_text(encoding="utf-8") == before_uv_lock
    captured = capsys.readouterr()
    assert "PINNED(0.20.0, files=" in captured.out
    assert "refusing to lower" in captured.err


def test_network_failure_is_distinguishable_and_non_destructive(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject, uv_lock = _write_project(tmp_path)
    before_pyproject = pyproject.read_text(encoding="utf-8")
    before_uv_lock = uv_lock.read_text(encoding="utf-8")

    def _ensure(_pin: str) -> object:
        raise tool.release_core.CoreEnsureError("network unavailable")

    monkeypatch.setattr(tool, "ensure_core", _ensure)

    code = tool.main(["--pyproject", str(pyproject), "--uv-lock", str(uv_lock)])

    assert code == tool.EXIT_COULD_NOT_DETERMINE
    assert pyproject.read_text(encoding="utf-8") == before_pyproject
    assert uv_lock.read_text(encoding="utf-8") == before_uv_lock
    assert "network unavailable" in capsys.readouterr().err


def test_core_lag_changes_nothing(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject, uv_lock = _write_project(tmp_path)
    before_pyproject = pyproject.read_text(encoding="utf-8")
    before_uv_lock = uv_lock.read_text(encoding="utf-8")
    monkeypatch.setattr(tool, "ensure_core", _fake_core_lag(tool))

    code = tool.main(["--pyproject", str(pyproject), "--uv-lock", str(uv_lock)])

    assert code == tool.EXIT_COULD_NOT_DETERMINE
    assert pyproject.read_text(encoding="utf-8") == before_pyproject
    assert uv_lock.read_text(encoding="utf-8") == before_uv_lock
    captured = capsys.readouterr()
    assert "CORE_LAG(pin=" in captured.out
    assert "newest_complete=0.42.1" in captured.out
