"""Tests for ``sase workspace list`` and ``sase workspace path``."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.main.workspace_handler import handle_workspace_command
from sase.main.workspace_handler_context import ProjectContext
from sase.main.workspace_handler_list import resolve_checkout_path
from sase.linked_repos import LINKED_REPOS_JSON_ENV, opened_linked_repo_records
from sase.sibling_repos import OPENED_SIBLINGS_FILENAME, opened_sibling_names
from sase.vcs_provider import VCS_DEFAULT_REVISION
from sase.workspace_provider.registry import record_workspace
from sase.workspace_provider.store import WorkspaceStore
from tests._project_display_case import ProjectDisplayCase
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

    def test_human_list_uses_configured_label_but_json_keeps_identity(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        project_display_case: ProjectDisplayCase,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.delenv("XDG_STATE_HOME", raising=False)
        monkeypatch.delenv("SASE_WORKSPACE_ROOT", raising=False)
        layout = project_display_case.write_project_layout(
            tmp_path / "home" / ".sase" / "projects",
            workspace_dir=tmp_path / "primary",
        )
        fake_config = {
            "workspace": {
                "root": str(tmp_path / "managed"),
                "project_key": "demo-key",
                "cleanup_ttl_days": 1,
            }
        }
        monkeypatch.setattr(
            "sase.main.workspace_handler.load_merged_config",
            lambda: fake_config,
        )
        monkeypatch.setattr(
            "sase.config.core.load_merged_config",
            lambda: fake_config,
        )

        human_args = make_args(
            workspace_subcommand="list",
            project=project_display_case.project_key,
            json=False,
        )
        with pytest.raises(SystemExit, match="0"):
            handle_workspace_command(human_args)
        human = capsys.readouterr().out
        assert f"Project: {project_display_case.project_label}" in human
        assert project_display_case.project_key not in human

        json_args = make_args(
            workspace_subcommand="list",
            project=project_display_case.project_key,
            json=True,
        )
        with pytest.raises(SystemExit, match="0"):
            handle_workspace_command(json_args)
        payload = json.loads(capsys.readouterr().out)
        assert payload["project"] == project_display_case.project_key
        assert payload["project_key"] == "demo-key"
        assert payload["root_dir"] == str(tmp_path / "managed" / "demo-key")
        assert layout.project_file.name == f"{project_display_case.project_key}.sase"

    def test_list_does_not_auto_initialize_sdd(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, _ = project_layout
        args = make_args(workspace_subcommand="list", project=project_name, json=False)

        with (
            patch("sase.sdd.files.ensure_bare_git_sdd_initialized") as ensure_sdd,
            pytest.raises(SystemExit) as exc,
        ):
            handle_workspace_command(args)

        assert exc.value.code == 0
        assert capsys.readouterr().out
        ensure_sdd.assert_not_called()


class TestPath:
    def test_linked_repo_path_is_host_scoped(self, tmp_path: Path) -> None:
        host_primary = tmp_path / "main"
        linked_primary = tmp_path / "core"
        host_primary.mkdir()
        linked_primary.mkdir()
        ctx = ProjectContext(
            project_name="core",
            project_file=str(tmp_path / "core.sase"),
            primary_workspace_dir=str(linked_primary),
            store=WorkspaceStore(str(linked_primary)),
            is_sibling=True,
            is_configured_linked_repo=True,
            linked_host_primary_workspace_dir=str(host_primary),
        )

        path = resolve_checkout_path(
            ctx,
            10,
            materialize=False,
            load_config=lambda: {"workspace": {"root": "adjacent"}},
        )

        assert path == str(
            host_primary.with_name("main_10") / "sase" / "repos" / "linked" / "core"
        )

    def test_linked_repo_primary_passthrough(self, tmp_path: Path) -> None:
        linked_primary = tmp_path / "core"
        linked_primary.mkdir()
        ctx = ProjectContext(
            project_name="core",
            project_file=str(tmp_path / "core.sase"),
            primary_workspace_dir=str(linked_primary),
            store=WorkspaceStore(str(linked_primary)),
            is_sibling=True,
            is_configured_linked_repo=True,
        )

        path = resolve_checkout_path(
            ctx,
            1,
            materialize=False,
            load_config=lambda: {},
        )

        assert path == str(linked_primary)

    def test_sidecar_repo_path_stays_in_durable_namespace(self, tmp_path: Path) -> None:
        host_primary = tmp_path / "main"
        linked_primary = tmp_path / "main--plans"
        host_primary.mkdir()
        linked_primary.mkdir()
        ctx = ProjectContext(
            project_name="main--plans",
            project_file=str(tmp_path / "main--plans.sase"),
            primary_workspace_dir=str(linked_primary),
            store=WorkspaceStore(str(linked_primary)),
            is_sibling=True,
            is_configured_linked_repo=True,
            linked_host_primary_workspace_dir=str(host_primary),
        )

        path = resolve_checkout_path(
            ctx,
            10,
            materialize=False,
            load_config=lambda: {"workspace": {"root": "adjacent"}},
        )

        assert path == str(
            (tmp_path / "main_10" / "sase" / "repos" / "plans").resolve()
        )

    def test_linked_repo_numbered_path_requires_host_context(
        self, tmp_path: Path
    ) -> None:
        linked_primary = tmp_path / "core"
        linked_primary.mkdir()
        ctx = ProjectContext(
            project_name="core",
            project_file=str(tmp_path / "core.sase"),
            primary_workspace_dir=str(linked_primary),
            store=WorkspaceStore(str(linked_primary)),
            is_sibling=True,
            is_configured_linked_repo=True,
        )

        with pytest.raises(RuntimeError, match="host-scoped"):
            resolve_checkout_path(
                ctx,
                10,
                materialize=False,
                load_config=lambda: {},
            )

    def test_sibling_project_direct_path_uses_its_own_store(
        self, tmp_path: Path
    ) -> None:
        linked_primary = tmp_path / "core"
        linked_primary.mkdir()
        ctx = ProjectContext(
            project_name="core",
            project_file=str(tmp_path / "core.sase"),
            primary_workspace_dir=str(linked_primary),
            store=WorkspaceStore(
                str(linked_primary), config={"workspace": {"root": "adjacent"}}
            ),
            is_sibling=True,
        )

        path = resolve_checkout_path(
            ctx,
            10,
            materialize=False,
            load_config=lambda: {"workspace": {"root": "adjacent"}},
        )

        assert path == str(linked_primary.with_name("core_10"))

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

    def test_path_does_not_auto_initialize_sdd(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, _ = project_layout
        args = make_args(
            workspace_subcommand="path", project=project_name, workspace_num=0
        )
        with (
            patch("sase.sdd.files.ensure_bare_git_sdd_initialized") as ensure_sdd,
            pytest.raises(SystemExit) as exc,
        ):
            handle_workspace_command(args)

        assert exc.value.code == 0
        assert capsys.readouterr().out
        ensure_sdd.assert_not_called()


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
