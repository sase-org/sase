"""Tests for ensure_git_clone_at origin healing on reusable clones."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.workspace_provider.utils import (
    ensure_git_clone_at,
    non_interactive_git_env,
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


# ── ensure_git_clone_at reusable-clone origin healing ───────────────


class TestEnsureGitCloneAt:
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
