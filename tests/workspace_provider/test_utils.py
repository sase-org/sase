"""Tests for sase.workspace_provider.utils module."""

import os
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from sase.running_field import ClaimResult, WorkspaceClaimError
from sase.workspace_provider.utils import (
    ensure_git_clone_at,
    ensure_workspace_checkout,
    get_default_branch,
    non_interactive_git_env,
    parse_bare_repo_dir,
    parse_workspace_dir,
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
        clone_kwargs = mock_run.call_args_list[1].kwargs
        fetch_kwargs = mock_run.call_args_list[3].kwargs
        assert clone_kwargs["stdin"] is subprocess.DEVNULL
        assert clone_kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
        assert fetch_kwargs["stdin"] is subprocess.DEVNULL
        assert fetch_kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"

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
