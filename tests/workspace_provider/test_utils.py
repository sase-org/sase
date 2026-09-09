"""Tests for git env, path matching, and project-file helpers."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.workspace_provider._utils_git import remote_points_at_path
from sase.workspace_provider.utils import (
    get_default_branch,
    non_interactive_git_env,
    parse_bare_repo_dir,
    parse_workspace_dir,
    reconcile_managed_checkout_origin,
    set_workspace_dir,
)


# ── get_default_branch ─────────────────────────────────────────────


class TestGetDefaultBranch:
    @patch("sase.workspace_provider.utils.subprocess.run")
    def test_detects_main(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="refs/remotes/origin/main\n"
        )
        assert get_default_branch("/repo") == "origin/main"

    @patch("sase.workspace_provider.utils.subprocess.run")
    def test_fallback_on_failure(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert get_default_branch("/repo") == "origin/main"

    @patch("sase.workspace_provider.utils.subprocess.run")
    def test_fallback_on_exception(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = OSError("no git")
        assert get_default_branch("/repo") == "origin/main"


class TestNonInteractiveGitEnv:
    def test_sets_prompt_suppression_without_mutating_base(self) -> None:
        base = {"PATH": "/bin", "GIT_TERMINAL_PROMPT": "1"}

        env = non_interactive_git_env(base)

        assert env["PATH"] == "/bin"
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        assert env["GCM_INTERACTIVE"] == "never"
        assert env["SSH_ASKPASS"] == "/bin/false"
        assert env["SSH_ASKPASS_REQUIRE"] == "force"
        assert base["GIT_TERMINAL_PROMPT"] == "1"


class TestRemotePathMatching:
    def test_relative_file_and_symlink_paths_match_primary(
        self, tmp_path: Path
    ) -> None:
        primary = tmp_path / "primary"
        checkout = tmp_path / "checkout"
        symlink = tmp_path / "primary-link"
        primary.mkdir()
        checkout.mkdir()
        symlink.symlink_to(primary, target_is_directory=True)

        assert remote_points_at_path("../primary-link", str(primary), cwd=str(checkout))
        assert remote_points_at_path(
            f"file://{symlink}", str(primary), cwd=str(checkout)
        )


class TestManagedOriginReconciliation:
    def test_marker_without_registry_fails_before_core(self, tmp_path: Path) -> None:
        primary = tmp_path / "primary"
        checkout = tmp_path / "checkout"
        primary.mkdir()
        checkout.mkdir()
        marker_dir = checkout / ".sase"
        marker_dir.mkdir()
        (marker_dir / "checkout.json").write_text(
            json.dumps(
                {
                    "project_name": "repo",
                    "project_key": "org/repo",
                    "workspace_num": 2,
                    "primary_workspace_dir": str(primary),
                    "registry_path": str(tmp_path / "missing" / "registry.json"),
                    "schema_version": 1,
                }
            ),
            encoding="utf-8",
        )

        with (
            patch(
                "sase.workspace_provider._utils_origin._managed_origin_reconciliation_decision"
            ) as decide,
            pytest.raises(RuntimeError, match="workspace registry is missing"),
        ):
            reconcile_managed_checkout_origin(str(checkout))

        decide.assert_not_called()


# ── parse_workspace_dir ──────────────────────────────────────────────


class TestParseWorkspaceDir:
    def test_empty_value(self, tmp_path: Path) -> None:
        with tempfile.NamedTemporaryFile(
            dir=tmp_path, mode="w", suffix=".sase", delete=False
        ) as f:
            f.write("WORKSPACE_DIR:\nNAME: my-cl\n")
            f.flush()
            assert parse_workspace_dir(f.name) is None
            os.unlink(f.name)


# ── parse_bare_repo_dir ──────────────────────────────────────────────


class TestParseBareRepoDir:
    def test_missing_file(self) -> None:
        assert parse_bare_repo_dir("/nonexistent/path/file.sase") is None

    def test_empty_value(self, tmp_path: Path) -> None:
        with tempfile.NamedTemporaryFile(
            dir=tmp_path, mode="w", suffix=".sase", delete=False
        ) as f:
            f.write("BARE_REPO_DIR:\nNAME: my-cl\n")
            f.flush()
            assert parse_bare_repo_dir(f.name) is None
            os.unlink(f.name)


# ── set_workspace_dir ────────────────────────────────────────────────


class TestSetWorkspaceDir:
    def test_creates_directory(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            gp = os.path.join(d, "subdir", "proj.sase")
            assert set_workspace_dir(gp, "/repo/")
            assert os.path.exists(gp)

    @patch("sase.workspace_provider._utils_checkout.write_patch_atomic")
    @patch("sase.workspace_provider._utils_checkout.patch_lock")
    def test_updates_existing(
        self, mock_lock: MagicMock, mock_write: MagicMock, tmp_path: Path
    ) -> None:
        mock_lock.return_value.__enter__ = MagicMock()
        mock_lock.return_value.__exit__ = MagicMock(return_value=False)
        with tempfile.NamedTemporaryFile(
            dir=tmp_path, mode="w", suffix=".sase", delete=False
        ) as f:
            f.write("WORKSPACE_DIR: /old/\nNAME: cl\n")
            f.flush()
            assert set_workspace_dir(f.name, "/new/")
            mock_write.assert_called_once()
            written = mock_write.call_args[0][1]
            assert "WORKSPACE_DIR: /new/" in written
            assert "/old/" not in written
            os.unlink(f.name)

    @patch("sase.workspace_provider._utils_checkout.write_patch_atomic")
    @patch("sase.workspace_provider._utils_checkout.patch_lock")
    def test_inserts_before_running(
        self, mock_lock: MagicMock, mock_write: MagicMock, tmp_path: Path
    ) -> None:
        mock_lock.return_value.__enter__ = MagicMock()
        mock_lock.return_value.__exit__ = MagicMock(return_value=False)
        with tempfile.NamedTemporaryFile(
            dir=tmp_path, mode="w", suffix=".sase", delete=False
        ) as f:
            f.write("RUNNING:\n  #git 1 1234\nNAME: cl\n")
            f.flush()
            assert set_workspace_dir(f.name, "/repo/")
            written = mock_write.call_args[0][1]
            lines = written.splitlines()
            ws_idx = next(
                i for i, ln in enumerate(lines) if ln.startswith("WORKSPACE_DIR:")
            )
            run_idx = next(i for i, ln in enumerate(lines) if ln.startswith("RUNNING:"))
            assert ws_idx < run_idx
            os.unlink(f.name)
