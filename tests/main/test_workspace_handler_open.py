"""Tests for ``sase workspace open``."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.linked_repos import LINKED_REPOS_JSON_ENV, opened_linked_repo_records
from sase.main.workspace_handler import handle_workspace_command
from sase.main.workspace_handler_context import ProjectContext
from sase.sibling_repos import OPENED_SIBLINGS_FILENAME, opened_sibling_names
from sase.vcs_provider import VCS_DEFAULT_REVISION
from sase.workspace_provider.store import WorkspaceStore
from tests.main.workspace_handler_helpers import make_args, project_layout

__all__ = ["project_layout"]


class TestOpen:
    def _open_with_context(
        self,
        *,
        args: argparse.Namespace,
        ctx: ProjectContext,
        checkout: str,
    ) -> int:
        with (
            patch("sase.main.workspace_handler._resolve_project_context") as resolve,
            patch("sase.sdd.files.ensure_bare_git_sdd_initialized"),
            patch(
                "sase.main.workspace_handler._resolve_checkout_path",
                return_value=checkout,
            ),
            patch("sase.axe.runner_workspace.prepare_workspace", return_value=True),
            pytest.raises(SystemExit) as exc,
        ):
            resolve.return_value = ctx
            handle_workspace_command(args)
        return int(exc.value.code)

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
            reason="prepare workspace",
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
                "sase.axe.runner_workspace.prepare_workspace", return_value=True
            ) as prepare_workspace,
            patch("sase.linked_repos.clear_workspace_repos") as clear_repos,
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
        clear_repos.assert_not_called()
        assert capsys.readouterr().out.strip() == checkout

    def test_open_records_sibling_when_artifacts_dir_is_set(
        self,
        project_layout: tuple[str, str, Path],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _, project_file, primary = project_layout
        artifacts_dir = tmp_path / "artifacts"
        monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
        checkout = str(tmp_path / "managed" / "core_10")
        ctx = ProjectContext(
            project_name="core",
            project_file=project_file,
            primary_workspace_dir=str(primary),
            store=WorkspaceStore(str(primary)),
            is_sibling=True,
        )
        args = make_args(
            workspace_subcommand="open",
            project="core",
            reason="prepare workspace",
            workspace_num=10,
            print_path=False,
            clean=True,
        )

        code = self._open_with_context(args=args, ctx=ctx, checkout=checkout)

        assert code == 0
        assert capsys.readouterr().out.strip() == checkout
        assert opened_sibling_names(artifacts_dir) == {"core"}
        record = opened_linked_repo_records(artifacts_dir)["core"]
        assert record["reason"] == "prepare workspace"
        opened_at = datetime.fromisoformat(record["opened_at"])
        assert opened_at.tzinfo is not None
        assert opened_at.astimezone(UTC).tzinfo == UTC

    def test_open_records_configured_linked_repo_without_sibling_state(
        self,
        project_layout: tuple[str, str, Path],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _, project_file, primary = project_layout
        artifacts_dir = tmp_path / "artifacts"
        checkout = str(tmp_path / "managed" / "core_10")
        monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
        monkeypatch.setenv(
            LINKED_REPOS_JSON_ENV,
            json.dumps(
                [
                    {
                        "name": "core",
                        "workspace_dir": checkout,
                        "workspace_strategy": "suffix",
                    }
                ]
            ),
        )
        ctx = ProjectContext(
            project_name="core",
            project_file=project_file,
            primary_workspace_dir=str(primary),
            store=WorkspaceStore(str(primary)),
            is_sibling=False,
        )
        args = make_args(
            workspace_subcommand="open",
            project="core",
            reason="prepare linked workspace",
            workspace_num=10,
            print_path=False,
            clean=True,
        )

        code = self._open_with_context(args=args, ctx=ctx, checkout=checkout)

        assert code == 0
        assert capsys.readouterr().out.strip() == checkout
        record = opened_linked_repo_records(artifacts_dir)["core"]
        assert record["workspace_dir"] == checkout
        assert record["reason"] == "prepare linked workspace"

    def test_open_does_not_record_primary_when_artifacts_dir_is_set(
        self,
        project_layout: tuple[str, str, Path],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, project_file, primary = project_layout
        artifacts_dir = tmp_path / "artifacts"
        monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
        monkeypatch.setenv(
            LINKED_REPOS_JSON_ENV,
            json.dumps(
                [
                    {
                        "name": "core",
                        "workspace_dir": str(tmp_path / "managed" / "core_10"),
                        "workspace_strategy": "suffix",
                    }
                ]
            ),
        )
        checkout = str(tmp_path / "managed" / "primary_10")
        ctx = ProjectContext(
            project_name=project_name,
            project_file=project_file,
            primary_workspace_dir=str(primary),
            store=WorkspaceStore(str(primary)),
        )
        args = make_args(
            workspace_subcommand="open",
            project=project_name,
            reason="prepare workspace",
            workspace_num=10,
            print_path=False,
            clean=True,
        )

        code = self._open_with_context(args=args, ctx=ctx, checkout=checkout)

        assert code == 0
        assert capsys.readouterr().out.strip() == checkout
        assert opened_sibling_names(artifacts_dir) == set()

    def test_open_sibling_does_not_record_without_artifacts_dir(
        self,
        project_layout: tuple[str, str, Path],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _, project_file, primary = project_layout
        monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
        artifacts_dir = tmp_path / "artifacts"
        checkout = str(tmp_path / "managed" / "core_10")
        ctx = ProjectContext(
            project_name="core",
            project_file=project_file,
            primary_workspace_dir=str(primary),
            store=WorkspaceStore(str(primary)),
            is_sibling=True,
        )
        args = make_args(
            workspace_subcommand="open",
            project="core",
            reason="prepare workspace",
            workspace_num=10,
            print_path=False,
            clean=True,
        )

        code = self._open_with_context(args=args, ctx=ctx, checkout=checkout)

        assert code == 0
        assert capsys.readouterr().out.strip() == checkout
        assert not (artifacts_dir / OPENED_SIBLINGS_FILENAME).exists()

    def test_open_materialization_failure_returns_1(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, _ = project_layout
        args = make_args(
            workspace_subcommand="open",
            project=project_name,
            reason="prepare workspace",
            workspace_num=42,
            print_path=False,
            clean=True,
        )

        with (
            patch(
                "sase.main.workspace_handler._resolve_checkout_path",
                side_effect=RuntimeError("clone failed"),
            ),
            patch("sase.axe.runner_workspace.prepare_workspace") as prepare_workspace,
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
            reason="prepare workspace",
            workspace_num=42,
            print_path=False,
            clean=True,
        )

        with (
            patch(
                "sase.main.workspace_handler._resolve_checkout_path",
                return_value=checkout,
            ),
            patch("sase.axe.runner_workspace.prepare_workspace", return_value=False),
            pytest.raises(SystemExit) as exc,
        ):
            handle_workspace_command(args)

        assert exc.value.code == 1
        assert capsys.readouterr().out == ""

    def test_open_auto_initializes_bare_git_sdd_before_materializing(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, primary = project_layout
        checkout = str(primary.parent / "managed" / "primary_42")
        args = make_args(
            workspace_subcommand="open",
            project=project_name,
            reason="prepare workspace",
            workspace_num=42,
            print_path=False,
            clean=True,
        )

        with (
            patch("sase.sdd.files.ensure_bare_git_sdd_initialized") as ensure_sdd,
            patch(
                "sase.main.workspace_handler._resolve_checkout_path",
                return_value=checkout,
            ),
            patch("sase.axe.runner_workspace.prepare_workspace", return_value=True),
            pytest.raises(SystemExit) as exc,
        ):
            handle_workspace_command(args)

        assert exc.value.code == 0
        ensure_sdd.assert_called_once_with(
            str(primary),
            commit=True,
            push=True,
            raise_on_error=True,
        )
        assert capsys.readouterr().out.strip() == checkout

    @pytest.mark.parametrize("reason", ["", "   "])
    def test_open_blank_reason_returns_2_without_side_effects(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
        reason: str,
    ) -> None:
        project_name, _, _ = project_layout
        args = make_args(
            workspace_subcommand="open",
            project=project_name,
            reason=reason,
            workspace_num=42,
            print_path=False,
            clean=True,
        )

        with (
            patch(
                "sase.main.workspace_handler._resolve_project_context"
            ) as resolve_ctx,
            patch("sase.sdd.files.ensure_bare_git_sdd_initialized") as ensure_sdd,
            patch(
                "sase.main.workspace_handler._resolve_checkout_path"
            ) as resolve_checkout_path,
            patch("sase.axe.runner_workspace.prepare_workspace") as prepare_workspace,
            pytest.raises(SystemExit) as exc,
        ):
            handle_workspace_command(args)

        captured = capsys.readouterr()
        assert exc.value.code == 2
        assert captured.out == ""
        assert "reason" in captured.err
        resolve_ctx.assert_not_called()
        ensure_sdd.assert_not_called()
        resolve_checkout_path.assert_not_called()
        prepare_workspace.assert_not_called()
