"""#git setup adopts the calling runner's numbered workspace claim."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from sase.running_field import ClaimResult, WorkspaceClaim
from sase.scripts import git_setup
from tests._running_field_helpers import create_project_file_with_running


def _resolved(project_file: str, primary: str = "/work/proj/") -> SimpleNamespace:
    return SimpleNamespace(
        project_name="proj",
        project_file=project_file,
        primary_workspace_dir=primary,
        checkout_target="main",
    )


def _parent_claim(workspace_num: int) -> WorkspaceClaim:
    return WorkspaceClaim(
        workspace_num, "ace(run)-launcher", "feature", pid=os.getppid()
    )


def test_adopts_parent_numbered_claim_without_second_claim(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project_file = create_project_file_with_running(
        tmp_path, running_claims=[_parent_claim(12)]
    )
    workspace_dir = str(tmp_path / "proj_12")

    with (
        patch(
            "sase.scripts.git_setup.resolve_git_ref",
            return_value=_resolved(project_file),
        ),
        patch.dict(os.environ, {"SASE_GIT_PRE_ALLOCATED": "0"}),
        patch(
            "sase.scripts.git_setup.ensure_workspace_checkout",
            return_value=workspace_dir,
        ) as checkout,
        patch("sase.scripts.git_setup.materialize_sdd_store") as materialize,
        patch("sase.scripts.git_setup.claim_next_axe_workspace") as claim_next,
        patch("sase.scripts.git_setup.claim_workspace") as claim,
    ):
        git_setup.main(git_ref="proj", n=None, release=True)

    claim_next.assert_not_called()
    claim.assert_not_called()
    checkout.assert_called_once_with("/work/proj/", 12)
    materialize.assert_called_once_with(workspace_dir, 12)
    out = capsys.readouterr().out
    assert "workspace_num=12" in out
    assert f"workspace_dir={workspace_dir}" in out
    assert "should_release=false" in out
    assert "_chdir=" + workspace_dir in out
    assert "meta_workspace=12" in out


def test_parent_placeholder_allocation_is_runner_bound(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project_file = create_project_file_with_running(
        tmp_path, running_claims=[_parent_claim(0)]
    )

    with (
        patch(
            "sase.scripts.git_setup.resolve_git_ref",
            return_value=_resolved(project_file),
        ),
        patch.dict(os.environ, {"SASE_GIT_PRE_ALLOCATED": "0"}),
        patch(
            "sase.scripts.git_setup.ensure_workspace_checkout",
            return_value="/work/proj_10",
        ),
        patch("sase.scripts.git_setup.materialize_sdd_store") as materialize,
        patch(
            "sase.scripts.git_setup.claim_next_axe_workspace", return_value=10
        ) as claim_next,
        patch("sase.scripts.git_setup.claim_workspace") as claim,
    ):
        git_setup.main(git_ref="proj", n=None, release=True)

    claim_next.assert_called_once()
    assert claim_next.call_args.args[2] == os.getppid()
    claim.assert_not_called()
    materialize.assert_not_called()
    out = capsys.readouterr().out
    assert "workspace_num=10" in out
    assert "should_release=false" in out
    assert "runner_bound_workspace=true" in out


def test_pinned_n_does_not_adopt_parent_claim(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project_file = create_project_file_with_running(
        tmp_path, running_claims=[_parent_claim(12)]
    )
    claim_workspace = MagicMock(return_value=ClaimResult(success=True))

    with (
        patch(
            "sase.scripts.git_setup.resolve_git_ref",
            return_value=_resolved(project_file),
        ),
        patch.dict(os.environ, {"SASE_GIT_PRE_ALLOCATED": "0"}),
        patch(
            "sase.scripts.git_setup.ensure_workspace_checkout",
            return_value="/work/proj_17",
        ),
        patch("sase.scripts.git_setup.materialize_sdd_store") as materialize,
        patch("sase.scripts.git_setup.claim_next_axe_workspace") as claim_next,
        patch("sase.scripts.git_setup.claim_workspace", claim_workspace),
    ):
        git_setup.main(git_ref="proj", n=17, release=True)

    claim_next.assert_not_called()
    materialize.assert_not_called()
    claim_workspace.assert_called_once()
    assert claim_workspace.call_args.args[1] == 17
    out = capsys.readouterr().out
    assert "workspace_num=17" in out
    assert "should_release=true" in out


def test_pre_allocated_env_still_wins_over_parent_claim(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project_file = create_project_file_with_running(
        tmp_path, running_claims=[_parent_claim(12)]
    )
    workspace_dir = str(tmp_path / "prealloc")

    with (
        patch(
            "sase.scripts.git_setup.resolve_git_ref",
            return_value=_resolved(project_file),
        ),
        patch.dict(
            os.environ,
            {
                "SASE_GIT_PRE_ALLOCATED": "1",
                "SASE_GIT_WORKSPACE_NUM": "13",
                "SASE_GIT_WORKSPACE_DIR": workspace_dir,
            },
        ),
        patch("sase.scripts.git_setup.ensure_workspace_checkout") as checkout,
        patch("sase.scripts.git_setup.materialize_sdd_store") as materialize,
        patch("sase.scripts.git_setup.claim_next_axe_workspace") as claim_next,
        patch("sase.scripts.git_setup.claim_workspace") as claim,
    ):
        git_setup.main(git_ref="proj", n=None, release=True)

    claim_next.assert_not_called()
    claim.assert_not_called()
    checkout.assert_not_called()
    materialize.assert_not_called()
    out = capsys.readouterr().out
    assert "workspace_num=13" in out
    assert "should_release=false" in out
