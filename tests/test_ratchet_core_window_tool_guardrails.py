"""Unexpected uv.lock diff guardrail tests for ratchet_core_window."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import ModuleType

import pytest

from tests._ratchet_core_window_tool_helpers import PLATFORMS
from tests._ratchet_core_window_tool_helpers import (
    asttokens_refresh_lock_runner as _asttokens_refresh_lock_runner,
)
from tests._ratchet_core_window_tool_helpers import load_tool as _load_tool
from tests._ratchet_core_window_tool_helpers import lock_text as _lock_text
from tests._ratchet_core_window_tool_helpers import (
    lock_text_for_platforms as _lock_text_for_platforms,
)
from tests._ratchet_core_window_tool_helpers import (
    lock_text_with_asttokens as _lock_text_with_asttokens,
)
from tests._ratchet_core_window_tool_helpers import metadata as _metadata
from tests._ratchet_core_window_tool_helpers import write_project as _write_project
from tests._ratchet_core_window_tool_helpers import (
    write_project_with_asttokens as _write_project_with_asttokens,
)


pytestmark = pytest.mark.contract


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    return _load_tool()


def test_unrelated_package_movement_restores_files(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject, uv_lock = _write_project(tmp_path)
    before_pyproject = pyproject.read_text(encoding="utf-8")
    before_uv_lock = uv_lock.read_text(encoding="utf-8")
    monkeypatch.setattr(
        tool, "fetch_pypi_metadata", lambda: _metadata("0.21.3", "0.22.0")
    )

    def _bad_lock_runner(
        project_dir: Path,
        target: object,
    ) -> subprocess.CompletedProcess[str]:
        specifier = tool.dependency_specifier_for_floor(target)
        bad_lock = _lock_text(target.raw, specifier).replace(
            'name = "sase"',
            'name = "sase-renamed"',
            1,
        )
        (project_dir / "uv.lock").write_text(bad_lock, encoding="utf-8")
        return subprocess.CompletedProcess(["uv", "lock"], 0, "", "")

    monkeypatch.setattr(tool, "_run_uv_lock", _bad_lock_runner)

    code = tool.main(["--pyproject", str(pyproject), "--uv-lock", str(uv_lock)])

    assert code == tool.EXIT_COULD_NOT_DETERMINE
    assert pyproject.read_text(encoding="utf-8") == before_pyproject
    assert uv_lock.read_text(encoding="utf-8") == before_uv_lock
    assert (
        "package order or package set changed unexpectedly" in capsys.readouterr().err
    )


def test_reconciliation_mode_rejects_package_set_changes(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject, uv_lock = _write_project_with_asttokens(tmp_path)
    before_pyproject = pyproject.read_text(encoding="utf-8")
    before_uv_lock = uv_lock.read_text(encoding="utf-8")
    monkeypatch.setattr(
        tool, "fetch_pypi_metadata", lambda: _metadata("0.21.3", "0.22.0")
    )

    def _bad_lock_runner(
        project_dir: Path,
        target: object,
    ) -> subprocess.CompletedProcess[str]:
        specifier = tool.dependency_specifier_for_floor(target)
        bad_lock = _lock_text_with_asttokens(target.raw, specifier).replace(
            'name = "asttokens"',
            'name = "asttokens-renamed"',
            1,
        )
        (project_dir / "uv.lock").write_text(bad_lock, encoding="utf-8")
        return subprocess.CompletedProcess(["uv", "lock"], 0, "", "")

    monkeypatch.setattr(tool, "_run_uv_lock", _bad_lock_runner)

    code = tool.main(
        [
            "--allow-transitive-lock-refresh",
            "--pyproject",
            str(pyproject),
            "--uv-lock",
            str(uv_lock),
        ]
    )

    assert code == tool.EXIT_COULD_NOT_DETERMINE
    assert pyproject.read_text(encoding="utf-8") == before_pyproject
    assert uv_lock.read_text(encoding="utf-8") == before_uv_lock
    assert (
        "package order or package set changed unexpectedly" in capsys.readouterr().err
    )


def test_reconciliation_mode_rejects_direct_dependency_package_refresh(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject, uv_lock = _write_project_with_asttokens(
        tmp_path,
        asttokens_direct=True,
    )
    before_pyproject = pyproject.read_text(encoding="utf-8")
    before_uv_lock = uv_lock.read_text(encoding="utf-8")
    monkeypatch.setattr(
        tool, "fetch_pypi_metadata", lambda: _metadata("0.21.3", "0.22.0")
    )
    monkeypatch.setattr(
        tool,
        "_run_uv_lock",
        _asttokens_refresh_lock_runner(tool, asttokens_direct=True),
    )

    code = tool.main(
        [
            "--allow-transitive-lock-refresh",
            "--pyproject",
            str(pyproject),
            "--uv-lock",
            str(uv_lock),
        ]
    )

    assert code == tool.EXIT_COULD_NOT_DETERMINE
    assert pyproject.read_text(encoding="utf-8") == before_pyproject
    assert uv_lock.read_text(encoding="utf-8") == before_uv_lock
    assert "direct dependency package asttokens" in capsys.readouterr().err


def test_reconciliation_mode_rejects_direct_dependency_diff_restores_files(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject, uv_lock = _write_project(tmp_path)
    before_pyproject = pyproject.read_text(encoding="utf-8")
    before_uv_lock = uv_lock.read_text(encoding="utf-8")
    monkeypatch.setattr(
        tool, "fetch_pypi_metadata", lambda: _metadata("0.21.3", "0.22.0")
    )

    def _bad_lock_runner(
        project_dir: Path,
        target: object,
    ) -> subprocess.CompletedProcess[str]:
        specifier = tool.dependency_specifier_for_floor(target)
        bad_lock = _lock_text(target.raw, specifier).replace(
            '{ name = "sase-core-rs" },',
            '{ name = "sase-core-rs", specifier = ">=999" },',
            1,
        )
        (project_dir / "uv.lock").write_text(bad_lock, encoding="utf-8")
        return subprocess.CompletedProcess(["uv", "lock"], 0, "", "")

    monkeypatch.setattr(tool, "_run_uv_lock", _bad_lock_runner)

    code = tool.main(
        [
            "--allow-transitive-lock-refresh",
            "--pyproject",
            str(pyproject),
            "--uv-lock",
            str(uv_lock),
        ]
    )

    assert code == tool.EXIT_COULD_NOT_DETERMINE
    assert pyproject.read_text(encoding="utf-8") == before_pyproject
    assert uv_lock.read_text(encoding="utf-8") == before_uv_lock
    assert "package sase changed outside" in capsys.readouterr().err


def test_core_package_still_refuses_extra_lock_format_fields(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject, uv_lock = _write_project(tmp_path)
    before_pyproject = pyproject.read_text(encoding="utf-8")
    before_uv_lock = uv_lock.read_text(encoding="utf-8")
    monkeypatch.setattr(
        tool, "fetch_pypi_metadata", lambda: _metadata("0.21.3", "0.22.0")
    )

    def _runner(project_dir: Path, target: object) -> subprocess.CompletedProcess[str]:
        specifier = tool.dependency_specifier_for_floor(target)
        lock_text = _lock_text_for_platforms(target.raw, specifier, platforms=PLATFORMS)
        lock_text = lock_text.replace(
            f'version = "{target.raw}"\nsource = {{ registry = "https://pypi.org/simple/" }}',
            f'version = "{target.raw}"\nsource = {{ registry = "https://pypi.org/simple/" }}\ndependencies = []',
            1,
        )
        (project_dir / "uv.lock").write_text(lock_text, encoding="utf-8")
        return subprocess.CompletedProcess(["uv", "lock"], 0, "", "")

    monkeypatch.setattr(tool, "_run_uv_lock", _runner)

    code = tool.main(
        [
            "--allow-transitive-lock-refresh",
            "--pyproject",
            str(pyproject),
            "--uv-lock",
            str(uv_lock),
        ]
    )

    assert code == tool.EXIT_COULD_NOT_DETERMINE
    assert pyproject.read_text(encoding="utf-8") == before_pyproject
    assert uv_lock.read_text(encoding="utf-8") == before_uv_lock
    err = capsys.readouterr().err
    assert "sase-core-rs package changed fields other than" in err
    assert "dependencies" in err
