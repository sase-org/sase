"""Tests for the pytest sandboxing of the managed SASE temp root."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sase.core.paths import (
    PYTEST_SANDBOX_MANAGED_TMPDIR_NAME,
    _unsandboxed_managed_tmpdir_root,
    get_sase_managed_tmpdir,
    sase_subdir,
)
from sase.core.state_write_guard import (
    PYTEST_CONTEXT_ENV_VARS,
    PYTEST_SANDBOX_DIR_ENV_VAR,
)
from tests.conftest import redirect_sase_home


def _leave_pytest_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the process look like a production run to the state-write guard."""
    for name in PYTEST_CONTEXT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_managed_tmpdir_lands_in_the_published_sandbox(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    monkeypatch.setenv(PYTEST_SANDBOX_DIR_ENV_VAR, str(sandbox))
    monkeypatch.setenv("SASE_TMPDIR", str(tmp_path / "developer-root"))

    managed = Path(get_sase_managed_tmpdir("handoff"))

    assert managed == sandbox / PYTEST_SANDBOX_MANAGED_TMPDIR_NAME / "handoff"
    assert managed.is_dir()
    assert not (tmp_path / "developer-root").exists()


def test_managed_tmpdir_ignores_sase_tmpdir_under_pytest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    developer_root = tmp_path / "developer-root"
    developer_root.mkdir()
    monkeypatch.setenv(PYTEST_SANDBOX_DIR_ENV_VAR, str(tmp_path / "sandbox"))
    monkeypatch.setenv("SASE_TMPDIR", str(developer_root))

    Path(get_sase_managed_tmpdir("workflow-artifacts"))

    assert list(developer_root.iterdir()) == []


def test_managed_tmpdir_fails_closed_without_a_published_sandbox(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_TMPDIR", str(tmp_path / "developer-root"))
    monkeypatch.delenv(PYTEST_SANDBOX_DIR_ENV_VAR, raising=False)

    with pytest.raises(RuntimeError, match=PYTEST_SANDBOX_DIR_ENV_VAR):
        get_sase_managed_tmpdir("handoff")

    assert not (tmp_path / "developer-root").exists()


def test_managed_tmpdir_fails_closed_on_a_blank_sandbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(PYTEST_SANDBOX_DIR_ENV_VAR, "   ")

    with pytest.raises(RuntimeError, match="cannot be proven sandboxed"):
        get_sase_managed_tmpdir()


def test_managed_tmpdir_honors_sase_tmpdir_outside_pytest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _leave_pytest_context(monkeypatch)
    developer_root = tmp_path / "developer-root"
    monkeypatch.setenv("SASE_TMPDIR", str(developer_root))

    managed = Path(get_sase_managed_tmpdir("wrappers"))

    assert managed == developer_root / "wrappers"
    assert managed.is_dir()


def test_managed_tmpdir_falls_back_to_sase_home_outside_pytest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _leave_pytest_context(monkeypatch)
    monkeypatch.delenv("SASE_TMPDIR", raising=False)
    # Leaving the pytest context also leaves the sandbox behind, so redirect
    # ~/.sase explicitly rather than creating "editors/" in the developer's
    # real managed root — the exact leak this module's subject prevents.
    redirect_sase_home(monkeypatch, tmp_path / ".sase")

    managed = Path(get_sase_managed_tmpdir("editors"))

    assert managed == sase_subdir("tmp") / "editors"
    assert managed.is_dir()


def test_unsandboxed_root_reports_the_developer_root_from_inside_pytest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    developer_root = tmp_path / "developer-root"
    monkeypatch.setenv("SASE_TMPDIR", str(developer_root))
    monkeypatch.setenv(PYTEST_SANDBOX_DIR_ENV_VAR, str(tmp_path / "sandbox"))

    assert _unsandboxed_managed_tmpdir_root() == developer_root
    assert not developer_root.exists()
    assert os.environ["SASE_TMPDIR"] == str(developer_root)


def test_unsandboxed_root_falls_back_to_sase_home(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_TMPDIR", raising=False)

    assert _unsandboxed_managed_tmpdir_root() == sase_subdir("tmp")
