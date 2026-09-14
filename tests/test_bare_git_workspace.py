"""Tests for sase.workspace_provider.plugins.bare_git_workspace."""

from unittest.mock import MagicMock, patch

import pytest

from sase.workspace_provider.plugins.bare_git_ref import ResolvedGitRef

_WS_MOD = "sase.workspace_provider.plugins.bare_git_workspace"


class TestWsResolveRef:
    def _make_plugin(self):  # type: ignore[no-untyped-def]
        from sase.workspace_provider.plugins.bare_git_workspace import (
            BareGitWorkspacePlugin,
        )

        return BareGitWorkspacePlugin()

    @pytest.mark.parametrize(
        ("ref", "expected_canonical_ref"),
        [
            ("myproj", None),
            ("my-feature", None),
            ("/repos/myproj.git", "myproj"),
        ],
    )
    def test_canonical_ref_only_for_bare_repo_paths(
        self,
        ref: str,
        expected_canonical_ref: str | None,
    ) -> None:
        resolved = ResolvedGitRef(
            project_file="/tmp/myproj.sase",
            project_name="myproj",
            primary_workspace_dir="/tmp/myproj/",
            bare_repo_dir="/repos/myproj.git",
            checkout_target="origin/main",
        )

        with patch(f"{_WS_MOD}.resolve_git_ref", return_value=resolved):
            result = self._make_plugin().ws_resolve_ref(ref, "git")

        assert result is not None
        assert result.project_name == "myproj"
        assert result.canonical_ref == expected_canonical_ref


class TestWsGetWorkspaceName:
    def _make_plugin(self):  # type: ignore[no-untyped-def]
        from sase.workspace_provider.plugins.bare_git_workspace import (
            BareGitWorkspacePlugin,
        )

        return BareGitWorkspacePlugin()

    @patch(f"{_WS_MOD}.subprocess.run")
    def test_remote_url(self, mock_run: MagicMock) -> None:
        """Extracts project name from remote.origin.url, stripping .git."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="https://github.com/org/my-project.git\n",
        )
        result = self._make_plugin().ws_get_workspace_name(cwd="/some/dir")
        assert result == "my-project"

    @patch(f"{_WS_MOD}.subprocess.run")
    def test_remote_url_no_git_suffix(self, mock_run: MagicMock) -> None:
        """Works when remote URL has no .git suffix."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="/repos/cool-project\n",
        )
        result = self._make_plugin().ws_get_workspace_name(cwd="/some/dir")
        assert result == "cool-project"

    @patch(f"{_WS_MOD}.subprocess.run")
    def test_falls_back_to_toplevel(self, mock_run: MagicMock) -> None:
        """Falls back to git rev-parse --show-toplevel when remote fails."""
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout="", stderr=""),  # remote fails
            MagicMock(returncode=0, stdout="/home/user/myrepo\n"),  # toplevel
        ]
        result = self._make_plugin().ws_get_workspace_name(cwd="/some/dir")
        assert result == "myrepo"

    @patch(f"{_WS_MOD}.subprocess.run")
    def test_strips_workspace_suffix(self, mock_run: MagicMock) -> None:
        """Strips _N workspace suffix from name."""
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout="", stderr=""),  # remote fails
            MagicMock(returncode=0, stdout="/home/user/sase_3\n"),  # toplevel
        ]
        result = self._make_plugin().ws_get_workspace_name(cwd="/some/dir")
        assert result == "sase"

    @patch(f"{_WS_MOD}.subprocess.run")
    def test_not_git_repo(self, mock_run: MagicMock) -> None:
        """Returns None when not in a git repo."""
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout="", stderr=""),  # remote fails
            MagicMock(returncode=128, stdout="", stderr=""),  # not a repo
        ]
        result = self._make_plugin().ws_get_workspace_name(cwd="/tmp")
        assert result is None

    @patch(f"{_WS_MOD}.subprocess.run")
    def test_hidden_git_root_name_is_not_returned(self, mock_run: MagicMock) -> None:
        """Treats a hidden git root basename as no recognized SASE project."""
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout="", stderr=""),  # remote fails
            MagicMock(returncode=0, stdout="/home/user/.sase\n"),  # toplevel
        ]
        result = self._make_plugin().ws_get_workspace_name(cwd="/home/user/.sase")
        assert result is None


class TestWsGetWorkspaceDirectory:
    def test_git_workspace_initializes_primary_sdd_before_checkout(self) -> None:
        from sase.workspace_provider.plugins.bare_git_workspace import (
            BareGitWorkspacePlugin,
        )

        plugin = BareGitWorkspacePlugin()
        with (
            patch("sase.sdd.files.ensure_bare_git_sdd_initialized") as ensure_sdd,
            patch(
                "sase.workspace_provider.utils.ensure_workspace_checkout",
                return_value="/tmp/project_10",
            ) as ensure_checkout,
        ):
            result = plugin.ws_get_workspace_directory(
                "git",
                10,
                "project",
                "/tmp/project",
            )

        assert result == "/tmp/project_10"
        ensure_sdd.assert_called_once_with(
            "/tmp/project",
            commit=True,
            push=True,
            raise_on_error=True,
        )
        ensure_checkout.assert_called_once_with("/tmp/project", 10)
