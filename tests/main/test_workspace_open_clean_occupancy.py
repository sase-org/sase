"""Occupancy guard coverage for ``sase workspace open-clean``."""

from __future__ import annotations

from dataclasses import replace
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.main.workspace_handler_list import prepare_opened_checkout
from sase.running_field import WorkspaceClaim
from sase.workspace_provider.occupant import new_occupant_record, write_occupant_record
from tests.main.repo_handler_helpers import project_context


def _project_file_with_claim(tmp_path: Path, claim: WorkspaceClaim) -> str:
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", delete=False, suffix=".sase"
    ) as f:
        f.write("# Test Project\n\nRUNNING:\n")
        f.write(claim.to_line() + "\n")
        f.write("NAME: Test Feature\nDESCRIPTION:\n  Test\nSTATUS: Ready\n")
        return f.name


def test_open_clean_refuses_when_checkout_is_occupied(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace_dir = tmp_path / "workspace-7"
    workspace_dir.mkdir()
    other_pid = os.getppid()

    project_file = _project_file_with_claim(
        tmp_path,
        WorkspaceClaim(
            workspace_num=7,
            workflow="ace(run)-other",
            cl_name="feature",
            pid=other_pid,
            artifacts_timestamp="ts",
        ),
    )
    ctx = replace(project_context(tmp_path), project_file=project_file)
    write_occupant_record(
        str(workspace_dir),
        new_occupant_record(
            pid=other_pid,
            workflow="ace(run)-other",
            project=ctx.project_name,
            workspace_num=7,
            agent_name="rival-agent",
        ),
    )

    with (
        patch("sase.sdd.files.ensure_bare_git_sdd_initialized"),
        patch("sase.axe.runner_workspace.prepare_workspace") as prepare,
    ):
        result = prepare_opened_checkout(
            ctx,
            7,
            reason="test",
            resolve_checkout=lambda ctx, workspace_num, *, materialize: str(
                workspace_dir
            ),
            preparation="runner",
        )

    assert result is None
    assert "rival-agent" in capsys.readouterr().err
    prepare.assert_not_called()
