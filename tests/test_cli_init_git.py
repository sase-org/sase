"""Tests for the `sase init-git` CLI subcommand."""

import shutil
from unittest.mock import patch

import pytest

from sase.main.parser import create_parser

_GIT_AVAILABLE = shutil.which("git") is not None


class TestInitGitArgParsing:
    """Verify argparse correctly parses all argument combinations."""

    def setup_method(self) -> None:
        self.parser = create_parser()


class TestInitGitHandler:
    """Mock init_bare_git_project and verify the CLI handler calls it correctly."""

    @patch("sase.git_workspace.init_bare_git_project")
    def test_handler_passes_all_options(
        self, mock_init: object, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from unittest.mock import MagicMock

        mock_init = MagicMock(return_value="/tmp/proj.gp")

        with (
            patch("sase.git_workspace.init_bare_git_project", mock_init),
            pytest.raises(SystemExit) as exc_info,
        ):
            from sase.main.entry import main

            with patch(
                "sys.argv",
                [
                    "sase",
                    "init-git",
                    "bar",
                    "--bare-dir",
                    "/tmp/bare.git",
                    "--clone-dir",
                    "/tmp/clone",
                    "--existing",
                    "/tmp/existing.git",
                ],
            ):
                main()

        assert exc_info.value.code == 0
        mock_init.assert_called_once_with(
            project_name="bar",
            bare_dir="/tmp/bare.git",
            clone_dir="/tmp/clone",
            existing_bare="/tmp/existing.git",
        )


@pytest.mark.skipif(not _GIT_AVAILABLE, reason="git not available")
class TestInitGitEndToEnd:
    """Real git operations in tmp dirs to verify full init flow."""
