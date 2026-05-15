"""Tests for ``sase workspace list`` and ``sase workspace path``."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.main.workspace_handler import handle_workspace_command
from sase.workspace_provider.registry import record_workspace
from sase.workspace_provider.store import WorkspaceStore
from tests.main.workspace_handler_helpers import make_args, project_layout

__all__ = ["project_layout"]


class TestList:
    def test_human_list_shows_primary(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, _ = project_layout
        args = make_args(workspace_subcommand="list", project=project_name, json=False)
        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert f"Project: {project_name}" in out
        assert "policy=absolute" in out
        # Primary checkout appears with role=primary
        assert "primary" in out

    def test_json_list_includes_registered_workspace(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, primary = project_layout
        store = WorkspaceStore(
            str(primary),
            config={
                "workspace": {
                    "root": str(primary.parent / "managed"),
                    "project_key": "demo-key",
                }
            },
        )
        record_workspace(store, store.resolve(10), role="claim")

        args = make_args(workspace_subcommand="list", project=project_name, json=True)
        with pytest.raises(SystemExit):
            handle_workspace_command(args)
        payload = json.loads(capsys.readouterr().out)
        nums = {row["workspace_num"] for row in payload["workspaces"]}
        assert 0 in nums
        assert 10 in nums
        assert payload["project"] == project_name
        assert payload["root_policy"] == "absolute"


class TestPath:
    def test_path_zero_prints_primary(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, primary = project_layout
        args = make_args(
            workspace_subcommand="path", project=project_name, workspace_num=0
        )
        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)
        assert exc.value.code == 0
        # Primary path is printed (resolution strips trailing slash).
        assert str(primary).rstrip("/") in capsys.readouterr().out

    def test_path_registered_managed_workspace(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, primary = project_layout
        store = WorkspaceStore(
            str(primary),
            config={
                "workspace": {
                    "root": str(primary.parent / "managed"),
                    "project_key": "demo-key",
                }
            },
        )
        wp = store.resolve(10)
        # Pretend the checkout already exists on disk so ``path`` returns
        # the materialized location without invoking ``git clone``.
        managed_dir = wp.checkout_dir.rstrip("/")
        os.makedirs(managed_dir, exist_ok=True)
        # Trick ensure_git_clone_at's "still valid" check into accepting
        # the directory by writing a .git directory.
        os.makedirs(os.path.join(managed_dir, ".git"), exist_ok=True)
        with patch("sase.workspace_provider.utils.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            record_workspace(store, wp, role="claim")
            args = make_args(
                workspace_subcommand="path",
                project=project_name,
                workspace_num=10,
            )
            with pytest.raises(SystemExit) as exc:
                handle_workspace_command(args)
        assert exc.value.code == 0
        out = capsys.readouterr().out.strip()
        assert out == managed_dir

    def test_path_unregistered_does_not_materialize(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, primary = project_layout
        args = make_args(
            workspace_subcommand="path", project=project_name, workspace_num=42
        )
        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)
        assert exc.value.code == 0
        out = capsys.readouterr().out.strip()
        # Resolved path is printed but no clone was performed.
        assert "_42" in out
        assert not os.path.isdir(out)
