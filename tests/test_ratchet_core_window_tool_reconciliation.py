"""Transitive uv.lock reconciliation tests for ratchet_core_window."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import ModuleType

import pytest

from tests._ratchet_core_window_tool_helpers import PLATFORMS
from tests._ratchet_core_window_tool_helpers import (
    ASTTOKENS_DEPENDENCIES_FIELD as _ASTTOKENS_DEPENDENCIES_FIELD,
)
from tests._ratchet_core_window_tool_helpers import (
    asttokens_refresh_lock_runner as _asttokens_refresh_lock_runner,
)
from tests._ratchet_core_window_tool_helpers import load_tool as _load_tool
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


def test_default_mode_rejects_transitive_lock_refresh_and_restores_files(
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
    monkeypatch.setattr(tool, "_run_uv_lock", _asttokens_refresh_lock_runner(tool))

    code = tool.main(["--pyproject", str(pyproject), "--uv-lock", str(uv_lock)])

    assert code == tool.EXIT_COULD_NOT_DETERMINE
    assert pyproject.read_text(encoding="utf-8") == before_pyproject
    assert uv_lock.read_text(encoding="utf-8") == before_uv_lock
    assert "uv.lock changed unrelated package asttokens" in capsys.readouterr().err


def test_reconciliation_mode_allows_transitive_lock_refresh(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject, uv_lock = _write_project_with_asttokens(tmp_path)
    monkeypatch.setattr(
        tool, "fetch_pypi_metadata", lambda: _metadata("0.21.3", "0.22.0")
    )
    monkeypatch.setattr(tool, "_run_uv_lock", _asttokens_refresh_lock_runner(tool))

    code = tool.main(
        [
            "--allow-transitive-lock-refresh",
            "--pyproject",
            str(pyproject),
            "--uv-lock",
            str(uv_lock),
        ]
    )

    assert code == tool.EXIT_RATCHET
    assert '    "sase-core-rs>=0.22.0,<0.23.0",' in pyproject.read_text(
        encoding="utf-8"
    )
    lock_text = uv_lock.read_text(encoding="utf-8")
    assert 'name = "asttokens"\nversion = "3.0.1"' in lock_text
    assert "sha256:new-sdist" in lock_text
    out = capsys.readouterr().out
    assert "allowed transitive uv.lock refresh: asttokens 3.0.0 -> 3.0.1" in out
    assert "applied" in out


def test_default_mode_rejects_asttokens_lock_format_field_refresh(
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
    monkeypatch.setattr(
        tool,
        "_run_uv_lock",
        _asttokens_refresh_lock_runner(
            tool,
            asttokens_extra_lines=_ASTTOKENS_DEPENDENCIES_FIELD,
        ),
    )

    code = tool.main(["--pyproject", str(pyproject), "--uv-lock", str(uv_lock)])

    assert code == tool.EXIT_COULD_NOT_DETERMINE
    assert pyproject.read_text(encoding="utf-8") == before_pyproject
    assert uv_lock.read_text(encoding="utf-8") == before_uv_lock
    assert "uv.lock changed unrelated package asttokens" in capsys.readouterr().err


def test_reconciliation_mode_allows_asttokens_lock_format_field_refresh(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject, uv_lock = _write_project_with_asttokens(tmp_path)
    monkeypatch.setattr(
        tool, "fetch_pypi_metadata", lambda: _metadata("0.21.3", "0.22.0")
    )
    monkeypatch.setattr(
        tool,
        "_run_uv_lock",
        _asttokens_refresh_lock_runner(
            tool,
            asttokens_extra_lines=_ASTTOKENS_DEPENDENCIES_FIELD,
        ),
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

    assert code == tool.EXIT_RATCHET
    lock_text = uv_lock.read_text(encoding="utf-8")
    assert "dependencies = []" in lock_text
    assert 'name = "asttokens"\nversion = "3.0.1"' in lock_text
    out = capsys.readouterr().out
    assert "allowed transitive uv.lock refresh: asttokens 3.0.0 -> 3.0.1" in out
    assert "applied" in out


def test_reconciliation_mode_allows_project_lock_version_to_follow_pyproject(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyproject, uv_lock = _write_project(tmp_path, project_version="0.17.0")
    monkeypatch.setattr(
        tool, "fetch_pypi_metadata", lambda: _metadata("0.21.3", "0.22.0")
    )

    def _runner(project_dir: Path, target: object) -> subprocess.CompletedProcess[str]:
        specifier = tool.dependency_specifier_for_floor(target)
        lock_text = _lock_text_for_platforms(target.raw, specifier, platforms=PLATFORMS)
        lock_text = lock_text.replace('version = "0.16.0"', 'version = "0.17.0"', 1)
        (project_dir / "uv.lock").write_text(lock_text, encoding="utf-8")
        return subprocess.CompletedProcess(["uv", "lock"], 0, "", "")

    monkeypatch.setattr(tool, "_run_uv_lock", _runner)

    code = tool.main(["--pyproject", str(pyproject), "--uv-lock", str(uv_lock)])

    assert code == tool.EXIT_RATCHET
    lock_text = uv_lock.read_text(encoding="utf-8")
    assert 'name = "sase"\nversion = "0.17.0"' in lock_text
    assert 'specifier = ">=0.22.0,<0.23.0"' in lock_text


def test_reconciliation_mode_rejects_non_pypi_source_rewrite(
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

    def _runner(project_dir: Path, target: object) -> subprocess.CompletedProcess[str]:
        specifier = tool.dependency_specifier_for_floor(target)
        lock_text = _lock_text_with_asttokens(target.raw, specifier).replace(
            'source = { registry = "https://pypi.org/simple/" }',
            'source = { path = "vendor/asttokens" }',
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
    assert "is not a canonical PyPI registry package" in capsys.readouterr().err


def test_reconciliation_mode_rejects_unexpected_transitive_metadata_field(
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
    monkeypatch.setattr(
        tool,
        "_run_uv_lock",
        _asttokens_refresh_lock_runner(
            tool,
            asttokens_extra_lines="metadata = { requires-dist = [] }\n",
        ),
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
    err = capsys.readouterr().err
    assert "changed fields outside" in err
    assert "metadata" in err
