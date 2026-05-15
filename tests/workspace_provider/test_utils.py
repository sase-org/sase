"""Tests for sase.workspace_provider.utils module."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.workspace_provider.utils import (
    ensure_git_clone,
    ensure_git_clone_at,
    ensure_workspace_checkout,
    get_default_branch,
    parse_bare_repo_dir,
    parse_workspace_dir,
    resolve_workspace_path,
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


# ── parse_workspace_dir ──────────────────────────────────────────────


class TestParseWorkspaceDir:
    def test_empty_value(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sase", delete=False) as f:
            f.write("WORKSPACE_DIR:\nNAME: my-cl\n")
            f.flush()
            assert parse_workspace_dir(f.name) is None
            os.unlink(f.name)


# ── parse_bare_repo_dir ──────────────────────────────────────────────


class TestParseBareRepoDir:
    def test_missing_file(self) -> None:
        assert parse_bare_repo_dir("/nonexistent/path/file.sase") is None

    def test_empty_value(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sase", delete=False) as f:
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

    @patch("sase.workspace_provider.utils.write_changespec_atomic")
    @patch("sase.workspace_provider.utils.changespec_lock")
    def test_updates_existing(
        self, mock_lock: MagicMock, mock_write: MagicMock
    ) -> None:
        mock_lock.return_value.__enter__ = MagicMock()
        mock_lock.return_value.__exit__ = MagicMock(return_value=False)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sase", delete=False) as f:
            f.write("WORKSPACE_DIR: /old/\nNAME: cl\n")
            f.flush()
            assert set_workspace_dir(f.name, "/new/")
            mock_write.assert_called_once()
            written = mock_write.call_args[0][1]
            assert "WORKSPACE_DIR: /new/" in written
            assert "/old/" not in written
            os.unlink(f.name)

    @patch("sase.workspace_provider.utils.write_changespec_atomic")
    @patch("sase.workspace_provider.utils.changespec_lock")
    def test_inserts_before_running(
        self, mock_lock: MagicMock, mock_write: MagicMock
    ) -> None:
        mock_lock.return_value.__enter__ = MagicMock()
        mock_lock.return_value.__exit__ = MagicMock(return_value=False)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sase", delete=False) as f:
            f.write("RUNNING:\n  #hg 1 1234\nNAME: cl\n")
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


class TestEnsureGitClone:
    def test_primary_exists(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            result = ensure_git_clone(d, 1)
            assert result == d

    def test_primary_missing(self) -> None:
        with pytest.raises(RuntimeError, match="does not exist"):
            ensure_git_clone("/nonexistent/dir/", 1)

    @patch("sase.workspace_provider.utils.subprocess.run")
    def test_secondary_creates(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="https://github.com/u/r.git\n"
        )
        with tempfile.TemporaryDirectory() as d:
            primary = os.path.join(d, "repo") + "/"
            os.makedirs(primary)
            result = ensure_git_clone(primary, 2)
            expected = os.path.join(d, "repo") + "_2/"
            assert result == expected
            # Should have called: get-url, clone, set-url, fetch
            assert mock_run.call_count == 4

    @patch("sase.workspace_provider.utils.subprocess.run")
    def test_secondary_fails(self, mock_run: MagicMock) -> None:
        import subprocess as sp

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="https://github.com/u/r.git\n"),  # get-url
            sp.CalledProcessError(1, "git", stderr="fatal error"),  # clone fails
        ]
        with tempfile.TemporaryDirectory() as d:
            primary = os.path.join(d, "repo") + "/"
            os.makedirs(primary)
            with pytest.raises(RuntimeError, match="git clone failed"):
                ensure_git_clone(primary, 2)


# ── ensure_git_clone_at (Phase 2 target-aware materializer) ──────────


class TestEnsureGitCloneAt:
    def test_primary_validated_at_explicit_target(self, tmp_path: Path) -> None:
        primary = tmp_path / "repo"
        primary.mkdir()
        # workspace_num=0 (new PRIMARY identity) returns the supplied target
        result = ensure_git_clone_at(str(primary), 0, str(primary))
        assert result == str(primary)

    def test_legacy_primary_num_one(self, tmp_path: Path) -> None:
        primary = tmp_path / "repo"
        primary.mkdir()
        result = ensure_git_clone_at(str(primary), 1, str(primary))
        assert result == str(primary)

    def test_primary_missing_raises(self) -> None:
        with pytest.raises(RuntimeError, match="does not exist"):
            ensure_git_clone_at("/nonexistent/dir", 0, "/nonexistent/dir")

    @patch("sase.workspace_provider.utils.subprocess.run")
    def test_creates_clone_at_explicit_target(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="https://github.com/u/r.git\n"
        )
        primary = tmp_path / "repo"
        primary.mkdir()
        target = tmp_path / "managed" / "repo_10"  # parent doesn't exist
        result = ensure_git_clone_at(str(primary) + "/", 10, str(target) + "/")
        assert result == str(target) + "/"
        # Parent should have been created
        assert target.parent.is_dir()
        # 4 subprocess calls: get-url, clone, set-url, fetch
        assert mock_run.call_count == 4

    @patch("sase.workspace_provider.utils.subprocess.run")
    def test_corrupt_target_is_replaced(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        # First call: git status on existing target — non-zero (corrupt)
        # Then: get-url, clone, set-url, fetch
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout=""),  # git status fails
            MagicMock(returncode=0, stdout="https://github.com/u/r.git\n"),  # get-url
            MagicMock(returncode=0, stdout=""),  # clone
            MagicMock(returncode=0, stdout=""),  # set-url
            MagicMock(returncode=0, stdout=""),  # fetch
        ]
        primary = tmp_path / "repo"
        primary.mkdir()
        target = tmp_path / "repo_2"
        target.mkdir()
        # Drop a junk file so we can confirm shutil.rmtree ran
        (target / "stale.txt").write_text("garbage")

        result = ensure_git_clone_at(str(primary) + "/", 2, str(target) + "/")
        assert result == str(target) + "/"
        assert not (target / "stale.txt").exists()
        assert mock_run.call_count == 5


# ── resolve_workspace_path / ensure_workspace_checkout ──────────────


class TestResolveWorkspacePath:
    def test_adjacent_matches_legacy_concat(self, tmp_path: Path) -> None:
        primary = str(tmp_path / "proj")
        config = {"workspace": {"root": "adjacent", "project_key": "k"}}
        path = resolve_workspace_path(primary, 5, config=config, env={})
        from sase.workspace_provider.utils import _get_git_clone_dir

        assert path.checkout_dir == _get_git_clone_dir(primary, 5)

    def test_xdg_state_places_under_managed_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        monkeypatch.delenv("SASE_WORKSPACE_ROOT", raising=False)
        config = {"workspace": {"root": "xdg-state", "project_key": "k"}}
        path = resolve_workspace_path("/home/u/work/proj", 10, config=config)
        expected_root = tmp_path / "sase" / "workspaces" / "k"
        assert path.checkout_dir.startswith(str(expected_root))
        assert path.checkout_dir.endswith("proj_10/")


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


# ── direct callers route through shared helper ──────────────────────


class TestDirectCallersUseSharedHelper:
    """Acceptance: direct callers go through ``ensure_workspace_checkout``."""

    def test_git_setup_uses_ensure_workspace_checkout(self) -> None:
        from sase.scripts import git_setup

        assert hasattr(git_setup, "ensure_workspace_checkout")
        # And no longer imports the legacy compat wrapper
        assert not hasattr(git_setup, "ensure_git_clone")

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
