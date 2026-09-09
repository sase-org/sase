"""Tests for ensure_workspace_checkout and its direct callers."""

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from sase.running_field import ClaimResult, WorkspaceClaimError
from sase.workspace_provider.utils import ensure_workspace_checkout


# ── ensure_workspace_checkout ───────────────────────────────────────


class TestEnsureWorkspaceCheckout:
    @patch("sase.workspace_provider.utils.subprocess.run")
    def test_adjacent_compat_matches_ensure_git_clone(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="https://github.com/u/r.git\n"
        )
        primary = str(tmp_path / "repo") + "/"
        os.makedirs(primary)
        config = {"workspace": {"root": "adjacent"}}
        result = ensure_workspace_checkout(primary, 2, config=config, env={})
        expected = str(tmp_path / "repo") + "_2/"
        assert result == expected

    @patch("sase.workspace_provider.utils.subprocess.run")
    def test_materialized_checkout_syncs_workspace_sdd_clone(
        self,
        mock_run: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="https://github.com/u/r.git\n"
        )
        primary = str(tmp_path / "repo") + "/"
        os.makedirs(primary)
        config = {"workspace": {"root": "adjacent"}}
        calls: list[tuple[str, int]] = []
        monkeypatch.setattr(
            "sase.sdd.store.ensure_workspace_sdd_clone",
            lambda workspace_dir, workspace_num: calls.append(
                (workspace_dir, workspace_num)
            ),
        )

        result = ensure_workspace_checkout(primary, 2, config=config, env={})

        assert result == str(tmp_path / "repo") + "_2/"
        assert calls == [(result, 2)]

    @patch("sase.workspace_provider.utils.subprocess.run")
    def test_xdg_state_materializes_under_managed_root(
        self,
        mock_run: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="https://github.com/u/r.git\n"
        )
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        monkeypatch.delenv("SASE_WORKSPACE_ROOT", raising=False)
        primary = str(tmp_path / "repo") + "/"
        os.makedirs(primary)
        config = {"workspace": {"root": "xdg-state", "project_key": "k"}}
        result = ensure_workspace_checkout(primary, 10, config=config)
        expected_root = tmp_path / "state" / "sase" / "workspaces" / "k"
        assert result.startswith(str(expected_root))
        assert result.endswith("repo_10/")

    @patch("sase.workspace_provider.utils.subprocess.run")
    def test_omitted_config_uses_xdg_state_default(
        self,
        mock_run: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="https://github.com/u/r.git\n"
        )
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        monkeypatch.delenv("SASE_WORKSPACE_ROOT", raising=False)
        primary = str(tmp_path / "repo") + "/"
        os.makedirs(primary)

        with (
            patch("sase.config.core.CONFIG_DIR", tmp_path / "empty_config"),
            patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
            patch("sase.config.core._load_plugin_configs", return_value=[]),
        ):
            result = ensure_workspace_checkout(primary, 10)

        expected_root = tmp_path / "state" / "sase" / "workspaces"
        assert result.startswith(str(expected_root))
        assert result.endswith("repo_10/")


# ── direct callers route through shared helper ──────────────────────


class TestDirectCallersUseSharedHelper:
    """Acceptance: direct callers go through ``ensure_workspace_checkout``."""

    def test_git_setup_uses_ensure_workspace_checkout(self) -> None:
        from sase.scripts import git_setup

        assert hasattr(git_setup, "ensure_workspace_checkout")
        # And no longer imports the legacy compat wrapper
        assert not hasattr(git_setup, "ensure_git_clone")

    def test_git_setup_preallocated_workspace_reconciles_origin(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.scripts import git_setup

        primary_dir = tmp_path / "proj"
        workspace_dir = tmp_path / "proj_12"
        primary_dir.mkdir()
        workspace_dir.mkdir()
        resolved = SimpleNamespace(
            project_name="proj",
            project_file="/tmp/proj/proj.sase",
            primary_workspace_dir=str(primary_dir),
            checkout_target="main",
        )
        monkeypatch.setenv("SASE_GIT_PRE_ALLOCATED", "1")
        monkeypatch.setenv("SASE_GIT_WORKSPACE_NUM", "12")
        monkeypatch.setenv("SASE_GIT_WORKSPACE_DIR", str(workspace_dir))

        with (
            patch("sase.scripts.git_setup.resolve_git_ref", return_value=resolved),
            patch(
                "sase.scripts.git_setup.reconcile_managed_checkout_origin",
            ) as mock_reconcile,
        ):
            git_setup.main(git_ref="proj", n=None, release=True)

        mock_reconcile.assert_called_once_with(
            str(workspace_dir),
            primary_workspace_dir=str(primary_dir),
            assume_managed_checkout=True,
        )

    def test_git_setup_failed_explicit_claim_blocks_launch(self) -> None:
        from sase.scripts import git_setup

        resolved = SimpleNamespace(
            project_name="proj",
            project_file="/tmp/proj/proj.sase",
            primary_workspace_dir="/tmp/proj",
            checkout_target="main",
        )

        with (
            patch("sase.scripts.git_setup.resolve_git_ref", return_value=resolved),
            patch(
                "sase.scripts.git_setup.ensure_workspace_checkout",
                return_value="/tmp/proj_12",
            ),
            patch(
                "sase.scripts.git_setup.claim_workspace",
                return_value=ClaimResult(
                    success=False,
                    error="project is disabled; enable before launching work",
                ),
            ),
        ):
            with pytest.raises(
                WorkspaceClaimError,
                match="project is disabled; enable before launching work",
            ):
                git_setup.main(git_ref="proj", n=12, release=True)

    def test_crs_starter_uses_ensure_workspace_checkout(self) -> None:
        import inspect

        from sase.ace.scheduler.workflows_runner import starter

        source = inspect.getsource(starter)
        assert "ensure_workspace_checkout" in source
        # The legacy import is gone from the local import block
        assert "ensure_git_clone" not in source

    def test_running_field_fallback_uses_ensure_workspace_checkout(self) -> None:
        import inspect

        from sase.running_field import _workspace

        source = inspect.getsource(_workspace.get_workspace_directory)
        assert "ensure_workspace_checkout" in source
        assert "ensure_git_clone" not in source
