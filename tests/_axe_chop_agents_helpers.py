"""Shared helpers for chop-launched agent tracking tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.agent.launcher import spawn_agent_subprocess


def _redirect_managed_tmpdir(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    """Point the managed temp root at *root* for one launch under test."""

    def fake_managed_tmpdir(*parts: str) -> str:
        managed = root.joinpath(*parts)
        managed.mkdir(parents=True, exist_ok=True)
        return str(managed)

    monkeypatch.setattr("sase.core.paths.get_sase_managed_tmpdir", fake_managed_tmpdir)


def _spawn_agent_for_env_test(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mock_spawn: MagicMock,
    extra_env: dict[str, str] | None = None,
    retry_transfer_from_pid: int | None = None,
) -> None:
    output_path = tmp_path / "proj_ace-run-260101_120000.txt"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir()
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    mock_spawn.side_effect = _fake_spawn_success
    _redirect_managed_tmpdir(monkeypatch, tmp_dir)
    monkeypatch.setattr("sase.core.paths.sharded_path", lambda *_args: str(output_path))

    spawn_agent_subprocess(
        cl_name="proj",
        project_file="/tmp/projects/proj/proj.sase",
        workspace_dir=str(workspace_dir),
        workspace_num=3,
        workflow_name="ace(run)-260101_120000",
        prompt="do work",
        timestamp="260101_120000",
        project_name="proj",
        extra_env=extra_env,
        retry_transfer_from_pid=retry_transfer_from_pid,
    )


def _fake_spawn_success(
    _prepared: object,
    *,
    env: dict[str, str],
    claim_callback: Callable[[int], bool] | None = None,
) -> int:
    if claim_callback is not None:
        assert callable(claim_callback)
        assert claim_callback(4321) is True
    assert env["SASE_AGENT"] == "1"
    assert env["SASE_HOME"]
    assert "PYTEST_CURRENT_TEST" in env
    return 4321
