"""#git setup claims a row the identity-checked release step can still free."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.running_field import get_claimed_workspaces
from sase.scripts import git_release, git_setup
from tests._running_field_helpers import create_project_file_with_running


def _resolved(project_file: str, primary: str = "/work/proj/") -> SimpleNamespace:
    return SimpleNamespace(
        project_name="proj",
        project_file=project_file,
        primary_workspace_dir=primary,
        checkout_target="main",
    )


def _isolate_ledger(tmp_path: Path) -> object:
    return patch(
        "sase.logs.workspace_claim_ledger.LEDGER_FILE",
        str(tmp_path / "workspace_claims.jsonl"),
    )


def _setup_output(out: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in out.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            parsed[key] = value
    return parsed


def _run_setup(
    tmp_path: Path,
    project_file: str,
    capsys: pytest.CaptureFixture[str],
    *,
    n: int | None = None,
) -> dict[str, str]:
    workspace_dir = str(tmp_path / "proj_10")
    with (
        _isolate_ledger(tmp_path),
        patch(
            "sase.scripts.git_setup.resolve_git_ref",
            return_value=_resolved(project_file),
        ),
        patch.dict(os.environ, {"SASE_GIT_PRE_ALLOCATED": "0"}),
        patch(
            "sase.scripts.git_setup.ensure_workspace_checkout",
            return_value=workspace_dir,
        ),
    ):
        git_setup.main(git_ref="proj", n=n, release=True)
    return _setup_output(capsys.readouterr().out)


def test_allocated_claim_names_the_runner_pid_and_ref(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project_file = create_project_file_with_running(tmp_path)

    output = _run_setup(tmp_path, project_file, capsys)

    assert output["should_release"] == "true"
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    # The setup step is a short-lived subprocess: the row must name the
    # runner, so stale cleanup and the identity-checked release both agree.
    assert claims[0].pid == os.getppid()
    assert claims[0].cl_name == "proj"


def test_release_step_frees_the_claim_setup_took(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project_file = create_project_file_with_running(tmp_path)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    output = _run_setup(tmp_path, project_file, capsys)
    assert get_claimed_workspaces(project_file)

    with (
        _isolate_ledger(tmp_path),
        patch.dict(os.environ, {"SASE_ARTIFACTS_DIR": str(artifacts)}),
    ):
        git_release.main(
            project_file=project_file,
            workspace_num=int(output["workspace_num"]),
            workspace_dir=output["workspace_dir"],
            workflow_name=output["workflow_name"],
            cl_name="proj",
        )

    assert "released=true" in capsys.readouterr().out
    assert get_claimed_workspaces(project_file) == []


def test_pinned_claim_is_also_releasable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project_file = create_project_file_with_running(tmp_path)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    output = _run_setup(tmp_path, project_file, capsys, n=17)
    assert output["workspace_num"] == "17"
    assert output["should_release"] == "true"

    with (
        _isolate_ledger(tmp_path),
        patch.dict(os.environ, {"SASE_ARTIFACTS_DIR": str(artifacts)}),
    ):
        git_release.main(
            project_file=project_file,
            workspace_num=17,
            workspace_dir=output["workspace_dir"],
            workflow_name=output["workflow_name"],
            cl_name="proj",
        )

    assert "released=true" in capsys.readouterr().out
    assert get_claimed_workspaces(project_file) == []
