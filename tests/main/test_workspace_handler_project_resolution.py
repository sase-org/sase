"""Tests for ``sase workspace`` project resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.main.workspace_handler import handle_workspace_command
from tests.main.workspace_handler_helpers import make_args


class TestWorkspaceProjectResolution:
    def test_missing_project_inference_exits(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Empty home with no projects directory and stub the inference
        # to ensure we don't accidentally pick up the dev's real projects.
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "sase.bead.project_name.infer_project_name_from_cwd",
            lambda cwd=None: None,
        )
        args = make_args(workspace_subcommand="list", project=None, json=False)
        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)
        assert exc.value.code == 2
        assert "infer project" in capsys.readouterr().err
