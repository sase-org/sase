"""Tests for sase.workspace_provider.utils module."""

import json
import os
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from sase.running_field import ClaimResult, WorkspaceClaimError
from sase.workspace_provider.utils import (
    _remote_points_at_path,
    ensure_git_clone_at,
    ensure_workspace_checkout,
    get_default_branch,
    non_interactive_git_env,
    parse_bare_repo_dir,
    parse_workspace_dir,
    reconcile_managed_checkout_origin,
    set_workspace_dir,
)


def _run_git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        env=non_interactive_git_env(),
        stdin=subprocess.DEVNULL,
    )
    return result.stdout.strip()


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

        assert _remote_points_at_path(
            "../primary-link", str(primary), cwd=str(checkout)
        )
        assert _remote_points_at_path(
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
                "sase.workspace_provider.utils._managed_origin_reconciliation_decision"
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

    @patch("sase.workspace_provider.utils.write_patch_atomic")
    @patch("sase.workspace_provider.utils.patch_lock")
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

    @patch("sase.workspace_provider.utils.write_patch_atomic")
    @patch("sase.workspace_provider.utils.patch_lock")
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
    def test_fresh_clone_raises_when_primary_origin_command_errors(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        def run(cmd: list[str], **_kwargs: object) -> MagicMock:
            if cmd == ["git", "remote", "get-url", "origin"]:
                return MagicMock(returncode=1, stdout="", stderr="config locked")
            raise AssertionError(f"unexpected command: {cmd}")

        mock_run.side_effect = run
        primary = tmp_path / "repo"
        primary.mkdir()
        target = tmp_path / "repo_2"

        with pytest.raises(RuntimeError, match="could not read origin URL"):
            ensure_git_clone_at(str(primary), 2, str(target))

        assert not target.exists()

    @patch("sase.workspace_provider.utils.subprocess.run")
    def test_reusable_clone_origin_pointing_at_primary_is_healed(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        primary = tmp_path / "repo"
        target = tmp_path / "repo_2"
        primary.mkdir()
        target.mkdir()
        primary_url = "git@github.com:u/r.git"
        target_origin = {"url": str(primary)}
        set_url_calls: list[list[str]] = []

        def run(cmd: list[str], *, cwd: str, **_kwargs: object) -> MagicMock:
            if cmd == ["git", "status"] and Path(cwd).resolve() == target.resolve():
                return MagicMock(returncode=0, stdout="", stderr="")
            if cmd == ["git", "remote", "get-url", "origin"]:
                if Path(cwd).resolve() == target.resolve():
                    return MagicMock(
                        returncode=0,
                        stdout=f"{target_origin['url']}\n",
                        stderr="",
                    )
                if Path(cwd).resolve() == primary.resolve():
                    return MagicMock(returncode=0, stdout=f"{primary_url}\n", stderr="")
            if cmd == ["git", "remote", "get-url", "--push", "--all", "origin"]:
                return MagicMock(
                    returncode=0,
                    stdout=f"{target_origin['url']}\n",
                    stderr="",
                )
            if cmd == ["git", "config", "--get-all", "remote.origin.pushurl"]:
                return MagicMock(returncode=1, stdout="", stderr="")
            if cmd[:4] == ["git", "remote", "set-url", "origin"]:
                set_url_calls.append(cmd)
                target_origin["url"] = cmd[4]
                return MagicMock(returncode=0, stdout="", stderr="")
            raise AssertionError(f"unexpected command: {cmd} cwd={cwd}")

        mock_run.side_effect = run

        result = ensure_git_clone_at(
            str(primary),
            2,
            str(target),
            assume_managed_checkout=True,
        )

        assert result == str(target)
        assert set_url_calls == [["git", "remote", "set-url", "origin", primary_url]]

    @patch("sase.workspace_provider.utils.subprocess.run")
    def test_reusable_clone_origin_already_matching_is_untouched(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        primary = tmp_path / "repo"
        target = tmp_path / "repo_2"
        primary.mkdir()
        target.mkdir()
        primary_url = "git@github.com:u/r.git"

        def run(cmd: list[str], *, cwd: str, **_kwargs: object) -> MagicMock:
            if cmd == ["git", "status"] and Path(cwd).resolve() == target.resolve():
                return MagicMock(returncode=0, stdout="", stderr="")
            if cmd == ["git", "remote", "get-url", "origin"]:
                return MagicMock(returncode=0, stdout=f"{primary_url}\n", stderr="")
            if cmd == ["git", "remote", "get-url", "--push", "--all", "origin"]:
                return MagicMock(returncode=0, stdout=f"{primary_url}\n", stderr="")
            if cmd == ["git", "config", "--get-all", "remote.origin.pushurl"]:
                return MagicMock(returncode=1, stdout="", stderr="")
            if cmd[:4] == ["git", "remote", "set-url", "origin"]:
                raise AssertionError("matching origin must not be rewritten")
            raise AssertionError(f"unexpected command: {cmd} cwd={cwd}")

        mock_run.side_effect = run

        assert ensure_git_clone_at(
            str(primary),
            2,
            str(target),
            assume_managed_checkout=True,
        ) == str(target)

    @patch("sase.workspace_provider.utils.subprocess.run")
    def test_reusable_clone_unrelated_local_bare_origin_is_untouched(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        primary = tmp_path / "repo"
        target = tmp_path / "repo_2"
        bare = tmp_path / "repo.git"
        primary.mkdir()
        target.mkdir()
        bare.mkdir()
        primary_url = "git@github.com:u/r.git"

        def run(cmd: list[str], *, cwd: str, **_kwargs: object) -> MagicMock:
            if cmd == ["git", "status"] and Path(cwd).resolve() == target.resolve():
                return MagicMock(returncode=0, stdout="", stderr="")
            if cmd == ["git", "remote", "get-url", "origin"]:
                if Path(cwd).resolve() == target.resolve():
                    return MagicMock(returncode=0, stdout=f"{bare}\n", stderr="")
                if Path(cwd).resolve() == primary.resolve():
                    return MagicMock(returncode=0, stdout=f"{primary_url}\n", stderr="")
            if cmd == ["git", "remote", "get-url", "--push", "--all", "origin"]:
                return MagicMock(returncode=0, stdout=f"{bare}\n", stderr="")
            if cmd == ["git", "config", "--get-all", "remote.origin.pushurl"]:
                return MagicMock(returncode=1, stdout="", stderr="")
            if cmd[:4] == ["git", "remote", "set-url", "origin"]:
                raise AssertionError("unrelated local bare origin must be preserved")
            raise AssertionError(f"unexpected command: {cmd} cwd={cwd}")

        mock_run.side_effect = run

        assert ensure_git_clone_at(
            str(primary),
            2,
            str(target),
            assume_managed_checkout=True,
        ) == str(target)

    @patch("sase.workspace_provider.utils.subprocess.run")
    def test_reusable_clone_explicit_push_url_pointing_at_primary_is_healed(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        primary = tmp_path / "repo"
        target = tmp_path / "repo_2"
        primary.mkdir()
        target.mkdir()
        primary_url = "git@github.com:u/r.git"
        push_url = {"url": str(primary)}
        set_push_url_calls: list[list[str]] = []

        def run(cmd: list[str], *, cwd: str, **_kwargs: object) -> MagicMock:
            if cmd == ["git", "status"] and Path(cwd).resolve() == target.resolve():
                return MagicMock(returncode=0, stdout="", stderr="")
            if cmd == ["git", "remote", "get-url", "origin"]:
                return MagicMock(returncode=0, stdout=f"{primary_url}\n", stderr="")
            if cmd == ["git", "remote", "get-url", "--push", "--all", "origin"]:
                return MagicMock(returncode=0, stdout=f"{push_url['url']}\n", stderr="")
            if cmd == ["git", "config", "--get-all", "remote.origin.pushurl"]:
                return MagicMock(returncode=0, stdout=f"{push_url['url']}\n", stderr="")
            if cmd[:5] == ["git", "remote", "set-url", "--push", "origin"]:
                set_push_url_calls.append(cmd)
                push_url["url"] = cmd[5]
                return MagicMock(returncode=0, stdout="", stderr="")
            if cmd[:4] == ["git", "remote", "set-url", "origin"]:
                raise AssertionError("fetch origin already canonical")
            raise AssertionError(f"unexpected command: {cmd} cwd={cwd}")

        mock_run.side_effect = run

        assert ensure_git_clone_at(
            str(primary),
            2,
            str(target),
            assume_managed_checkout=True,
        ) == str(target)
        assert set_push_url_calls == [
            [
                "git",
                "remote",
                "set-url",
                "--push",
                "origin",
                primary_url,
                str(primary),
            ]
        ]

    @patch("sase.workspace_provider.utils.subprocess.run")
    def test_reusable_clone_stale_origin_set_url_failure_raises(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        primary = tmp_path / "repo"
        target = tmp_path / "repo_2"
        primary.mkdir()
        target.mkdir()
        primary_url = "git@github.com:u/r.git"

        def run(cmd: list[str], *, cwd: str, **_kwargs: object) -> MagicMock:
            if cmd == ["git", "status"] and Path(cwd).resolve() == target.resolve():
                return MagicMock(returncode=0, stdout="", stderr="")
            if cmd == ["git", "remote", "get-url", "origin"]:
                if Path(cwd).resolve() == target.resolve():
                    return MagicMock(returncode=0, stdout=f"{primary}\n", stderr="")
                if Path(cwd).resolve() == primary.resolve():
                    return MagicMock(returncode=0, stdout=f"{primary_url}\n", stderr="")
            if cmd == ["git", "remote", "get-url", "--push", "--all", "origin"]:
                return MagicMock(returncode=0, stdout=f"{primary}\n", stderr="")
            if cmd == ["git", "config", "--get-all", "remote.origin.pushurl"]:
                return MagicMock(returncode=1, stdout="", stderr="")
            if cmd[:4] == ["git", "remote", "set-url", "origin"]:
                return MagicMock(returncode=1, stdout="", stderr="config locked")
            raise AssertionError(f"unexpected command: {cmd} cwd={cwd}")

        mock_run.side_effect = run

        with pytest.raises(RuntimeError, match="could not rewrite"):
            ensure_git_clone_at(
                str(primary),
                2,
                str(target),
                assume_managed_checkout=True,
            )

    @patch("sase.workspace_provider.utils.subprocess.run")
    def test_reusable_clone_stale_origin_requires_primary_origin(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        primary = tmp_path / "repo"
        target = tmp_path / "repo_2"
        primary.mkdir()
        target.mkdir()

        def run(cmd: list[str], *, cwd: str, **_kwargs: object) -> MagicMock:
            if cmd == ["git", "status"] and Path(cwd).resolve() == target.resolve():
                return MagicMock(returncode=0, stdout="", stderr="")
            if cmd == ["git", "remote", "get-url", "origin"]:
                if Path(cwd).resolve() == target.resolve():
                    return MagicMock(returncode=0, stdout=f"{primary}\n", stderr="")
                if Path(cwd).resolve() == primary.resolve():
                    return MagicMock(returncode=1, stdout="", stderr="no origin")
            if cmd == ["git", "remote", "get-url", "--push", "--all", "origin"]:
                return MagicMock(returncode=0, stdout=f"{primary}\n", stderr="")
            if cmd == ["git", "config", "--get-all", "remote.origin.pushurl"]:
                return MagicMock(returncode=1, stdout="", stderr="")
            raise AssertionError(f"unexpected command: {cmd} cwd={cwd}")

        mock_run.side_effect = run

        with pytest.raises(RuntimeError, match="primary checkout's origin"):
            ensure_git_clone_at(
                str(primary),
                2,
                str(target),
                assume_managed_checkout=True,
            )

    def test_reusable_clone_heals_push_destination_to_canonical_remote(
        self, tmp_path: Path
    ) -> None:
        bare = tmp_path / "remote.git"
        primary = tmp_path / "primary"
        target = tmp_path / "primary_2"

        _run_git(tmp_path, "init", "--bare", str(bare))
        _run_git(tmp_path, "init", str(primary))
        _run_git(primary, "config", "user.email", "test@example.com")
        _run_git(primary, "config", "user.name", "Test User")
        (primary / "README.md").write_text("initial\n", encoding="utf-8")
        _run_git(primary, "add", "README.md")
        _run_git(primary, "commit", "-m", "initial")
        _run_git(primary, "branch", "-M", "main")
        _run_git(primary, "remote", "add", "origin", str(bare))
        _run_git(primary, "push", "-u", "origin", "main")
        primary_head_before = _run_git(primary, "rev-parse", "HEAD")

        _run_git(tmp_path, "clone", str(primary), str(target))
        _run_git(target, "config", "user.email", "test@example.com")
        _run_git(target, "config", "user.name", "Test User")
        (target / "dirty.txt").write_text("left alone\n", encoding="utf-8")

        assert ensure_git_clone_at(
            str(primary),
            2,
            str(target),
            assume_managed_checkout=True,
        ) == str(target)
        assert _run_git(target, "remote", "get-url", "origin") == str(bare)
        assert (target / "dirty.txt").read_text(encoding="utf-8") == "left alone\n"

        (target / "feature.txt").write_text("feature\n", encoding="utf-8")
        _run_git(target, "add", "feature.txt")
        _run_git(target, "commit", "-m", "feature")
        worker_head = _run_git(target, "rev-parse", "HEAD")
        _run_git(target, "push", "origin", "main")

        assert _run_git(primary, "rev-parse", "HEAD") == primary_head_before
        assert _run_git(bare, "rev-parse", "refs/heads/main") == worker_head

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

    @patch("sase.workspace_provider.utils.subprocess.run")
    def test_fresh_clone_raises_when_primary_origin_returns_failure(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="fatal: could not read config\n",
        )
        primary = tmp_path / "repo"
        primary.mkdir()
        target = tmp_path / "repo_2"

        with pytest.raises(RuntimeError, match="Could not read primary.*origin"):
            ensure_git_clone_at(str(primary), 2, str(target))

        commands = [call.args[0] for call in mock_run.call_args_list]
        assert commands == [["git", "remote", "get-url", "origin"]]
        assert not target.exists()

    @patch("sase.workspace_provider.utils.subprocess.run")
    def test_reuse_heals_origin_that_points_at_primary_path(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        primary = tmp_path / "repo"
        target = tmp_path / "repo_2"
        primary.mkdir()
        target.mkdir()
        real_origin = "git@github.com:sase-org/sase.git"

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),  # target status
            MagicMock(returncode=0, stdout=str(primary) + "\n", stderr=""),
            MagicMock(returncode=0, stdout=real_origin + "\n", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),  # set-url
        ]

        result = ensure_git_clone_at(str(primary), 2, str(target))

        assert result == str(target)
        commands = [call.args[0] for call in mock_run.call_args_list]
        assert commands == [
            ["git", "status"],
            ["git", "remote", "get-url", "origin"],
            ["git", "remote", "get-url", "origin"],
            ["git", "remote", "set-url", "origin", real_origin],
        ]

    @patch("sase.workspace_provider.utils.subprocess.run")
    def test_reuse_matching_origin_is_untouched(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        primary = tmp_path / "repo"
        target = tmp_path / "repo_2"
        primary.mkdir()
        target.mkdir()
        real_origin = "git@github.com:sase-org/sase.git"

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),  # target status
            MagicMock(returncode=0, stdout=real_origin + "\n", stderr=""),
            MagicMock(returncode=0, stdout=real_origin + "\n", stderr=""),
        ]

        result = ensure_git_clone_at(str(primary), 2, str(target))

        assert result == str(target)
        commands = [call.args[0] for call in mock_run.call_args_list]
        assert commands == [
            ["git", "status"],
            ["git", "remote", "get-url", "origin"],
            ["git", "remote", "get-url", "origin"],
        ]


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
