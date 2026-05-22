"""Tests for ``sase workspace list`` and ``sase workspace path``."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.main.workspace_handler import handle_workspace_command
from sase.vcs_provider import VCS_DEFAULT_REVISION
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
        managed_dir = wp.checkout_dir.rstrip("/")
        with patch("sase.workspace_provider.utils.subprocess.run") as mock_run:
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
        assert not os.path.isdir(managed_dir)
        mock_run.assert_not_called()

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


class TestOpen:
    @pytest.mark.parametrize("clean", [False, True])
    def test_open_materializes_and_prepares_by_default(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
        clean: bool,
    ) -> None:
        project_name, _, primary = project_layout
        checkout = str(primary.parent / "managed" / "primary_42")
        args = make_args(
            workspace_subcommand="open",
            project=project_name,
            workspace_num=42,
            print_path=False,
            clean=clean,
        )

        with (
            patch(
                "sase.main.workspace_handler._resolve_checkout_path",
                return_value=checkout,
            ) as resolve_checkout_path,
            patch(
                "sase.axe.runner_utils.prepare_workspace", return_value=True
            ) as prepare_workspace,
            pytest.raises(SystemExit) as exc,
        ):
            handle_workspace_command(args)

        assert exc.value.code == 0
        resolve_checkout_path.assert_called_once()
        call_args = resolve_checkout_path.call_args
        assert call_args.args[1] == 42
        assert call_args.kwargs == {"materialize": True}
        prepare_workspace.assert_called_once_with(
            checkout,
            f"{project_name}-workspace-42",
            VCS_DEFAULT_REVISION,
            backup_suffix="workspace-open",
            project_basename=project_name,
        )
        assert capsys.readouterr().out.strip() == checkout

    def test_open_materialization_failure_returns_1(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, _ = project_layout
        args = make_args(
            workspace_subcommand="open",
            project=project_name,
            workspace_num=42,
            print_path=False,
            clean=True,
        )

        with (
            patch(
                "sase.main.workspace_handler._resolve_checkout_path",
                side_effect=RuntimeError("clone failed"),
            ),
            patch("sase.axe.runner_utils.prepare_workspace") as prepare_workspace,
            pytest.raises(SystemExit) as exc,
        ):
            handle_workspace_command(args)

        captured = capsys.readouterr()
        assert exc.value.code == 1
        assert "clone failed" in captured.err
        assert captured.out == ""
        prepare_workspace.assert_not_called()

    def test_open_preparation_failure_returns_1_without_path(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, primary = project_layout
        checkout = str(primary.parent / "managed" / "primary_42")
        args = make_args(
            workspace_subcommand="open",
            project=project_name,
            workspace_num=42,
            print_path=False,
            clean=True,
        )

        with (
            patch(
                "sase.main.workspace_handler._resolve_checkout_path",
                return_value=checkout,
            ),
            patch("sase.axe.runner_utils.prepare_workspace", return_value=False),
            pytest.raises(SystemExit) as exc,
        ):
            handle_workspace_command(args)

        assert exc.value.code == 1
        assert capsys.readouterr().out == ""
