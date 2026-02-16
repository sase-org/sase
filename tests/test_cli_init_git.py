"""Tests for the `sase init-git` CLI subcommand."""

import os
import shutil
import subprocess
from unittest.mock import patch

import pytest

from sase.main.parser import create_parser

_GIT_AVAILABLE = shutil.which("git") is not None


class TestInitGitArgParsing:
    """Verify argparse correctly parses all argument combinations."""

    def setup_method(self) -> None:
        self.parser = create_parser()

    def test_project_name_only(self) -> None:
        args = self.parser.parse_args(["init-git", "myproject"])
        assert args.command == "init-git"
        assert args.project_name == "myproject"
        assert args.bare_dir is None
        assert args.clone_dir is None
        assert args.existing is None

    def test_with_bare_dir(self) -> None:
        args = self.parser.parse_args(
            ["init-git", "myproject", "--bare-dir", "/tmp/bare.git"]
        )
        assert args.bare_dir == "/tmp/bare.git"

    def test_with_clone_dir(self) -> None:
        args = self.parser.parse_args(
            ["init-git", "myproject", "--clone-dir", "/tmp/clone"]
        )
        assert args.clone_dir == "/tmp/clone"

    def test_with_existing(self) -> None:
        args = self.parser.parse_args(
            ["init-git", "myproject", "--existing", "/tmp/existing.git"]
        )
        assert args.existing == "/tmp/existing.git"

    def test_all_options(self) -> None:
        args = self.parser.parse_args(
            [
                "init-git",
                "myproject",
                "--bare-dir",
                "/tmp/bare.git",
                "--clone-dir",
                "/tmp/clone",
                "--existing",
                "/tmp/existing.git",
            ]
        )
        assert args.project_name == "myproject"
        assert args.bare_dir == "/tmp/bare.git"
        assert args.clone_dir == "/tmp/clone"
        assert args.existing == "/tmp/existing.git"

    def test_missing_project_name(self) -> None:
        with pytest.raises(SystemExit):
            self.parser.parse_args(["init-git"])


class TestInitGitHandler:
    """Mock init_bare_git_project and verify the CLI handler calls it correctly."""

    @patch("sase.git_workspace.init_bare_git_project")
    def test_handler_calls_with_defaults(
        self, mock_init: object, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from unittest.mock import MagicMock

        mock_init = MagicMock(return_value="/home/user/.sase/projects/foo/foo.gp")

        with (
            patch("sase.git_workspace.init_bare_git_project", mock_init),
            pytest.raises(SystemExit) as exc_info,
        ):
            from sase.main.entry import main

            with patch("sys.argv", ["sase", "init-git", "foo"]):
                main()

        assert exc_info.value.code == 0
        mock_init.assert_called_once_with(
            project_name="foo",
            bare_dir=None,
            clone_dir=None,
            existing_bare=None,
        )
        captured = capsys.readouterr()
        assert "Initialized git project:" in captured.out
        assert "foo.gp" in captured.out

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

    def test_new_project_creates_bare_clone_and_gp(self, tmp_path: object) -> None:
        """init_bare_git_project with defaults creates bare repo, clone, and .gp file."""
        base = str(tmp_path)
        bare_dir = os.path.join(base, "repos", "testproj.git")
        clone_dir = os.path.join(base, "projects", "testproj")

        from sase.git_workspace import init_bare_git_project

        with (
            patch("sase.git_workspace._set_bare_repo_dir") as mock_set_bare,
            patch("sase.git_workspace.set_workspace_dir") as mock_set_ws,
        ):
            mock_set_bare.return_value = True

            result = init_bare_git_project(
                project_name="testproj",
                bare_dir=bare_dir,
                clone_dir=clone_dir,
            )

        # Bare repo was created
        assert os.path.isdir(bare_dir)
        git_check = subprocess.run(
            ["git", "--git-dir", bare_dir, "rev-parse", "--is-bare-repository"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert git_check.stdout.strip() == "true"

        # Clone was created
        assert os.path.isdir(clone_dir)
        assert os.path.isdir(os.path.join(clone_dir, ".git"))

        # Initial commit exists and was pushed
        log = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=clone_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "Initial commit" in log.stdout

        # _set_bare_repo_dir and set_workspace_dir were called
        mock_set_bare.assert_called_once_with(result, bare_dir)
        mock_set_ws.assert_called_once_with(result, clone_dir)

    def test_existing_bare_repo(self, tmp_path: object) -> None:
        """init_bare_git_project with --existing clones from an existing bare repo."""
        base = str(tmp_path)

        # Create a bare repo with content
        existing_bare = os.path.join(base, "existing.git")
        subprocess.run(
            ["git", "init", "--bare", existing_bare],
            capture_output=True,
            text=True,
            check=True,
        )

        # Create a temp clone, add a commit, push it
        temp_clone = os.path.join(base, "temp_clone")
        subprocess.run(
            ["git", "clone", existing_bare, temp_clone],
            capture_output=True,
            text=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=temp_clone,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=temp_clone,
            capture_output=True,
            check=True,
        )
        readme = os.path.join(temp_clone, "README.md")
        with open(readme, "w") as f:
            f.write("# Existing project\n")
        subprocess.run(
            ["git", "add", "README.md"],
            cwd=temp_clone,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Add README"],
            cwd=temp_clone,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "push", "origin", "HEAD"],
            cwd=temp_clone,
            capture_output=True,
            check=True,
        )

        # Now use init_bare_git_project with --existing
        clone_dir = os.path.join(base, "projects", "myproj")

        with (
            patch("sase.git_workspace._set_bare_repo_dir") as mock_set_bare,
            patch("sase.git_workspace.set_workspace_dir") as mock_set_ws,
        ):
            mock_set_bare.return_value = True

            from sase.git_workspace import init_bare_git_project

            result = init_bare_git_project(
                project_name="myproj",
                clone_dir=clone_dir,
                existing_bare=existing_bare,
            )

        # Clone was created from the existing bare
        assert os.path.isdir(clone_dir)
        assert os.path.isfile(os.path.join(clone_dir, "README.md"))

        # bare_dir arg to _set_bare_repo_dir should be the existing path
        mock_set_bare.assert_called_once_with(result, existing_bare)
        mock_set_ws.assert_called_once_with(result, clone_dir)

    def test_push_and_pull_work(self, tmp_path: object) -> None:
        """After init, push from clone works and a second clone can pull."""
        base = str(tmp_path)
        bare_dir = os.path.join(base, "repos", "pushtest.git")
        clone_dir = os.path.join(base, "projects", "pushtest")

        with (
            patch("sase.git_workspace._set_bare_repo_dir") as mock_set_bare,
            patch("sase.git_workspace.set_workspace_dir"),
        ):
            mock_set_bare.return_value = True

            from sase.git_workspace import init_bare_git_project

            init_bare_git_project(
                project_name="pushtest",
                bare_dir=bare_dir,
                clone_dir=clone_dir,
            )

        # Configure git user in the clone
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=clone_dir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=clone_dir,
            capture_output=True,
            check=True,
        )

        # Create a file and push
        test_file = os.path.join(clone_dir, "hello.txt")
        with open(test_file, "w") as f:
            f.write("hello\n")
        subprocess.run(
            ["git", "add", "hello.txt"],
            cwd=clone_dir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Add hello"],
            cwd=clone_dir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "push", "origin", "HEAD"],
            cwd=clone_dir,
            capture_output=True,
            check=True,
        )

        # Clone again and verify the file is there
        clone2 = os.path.join(base, "projects", "pushtest2")
        subprocess.run(
            ["git", "clone", bare_dir, clone2],
            capture_output=True,
            check=True,
        )
        assert os.path.isfile(os.path.join(clone2, "hello.txt"))

    def test_existing_non_bare_repo_raises(self, tmp_path: object) -> None:
        """Passing a non-bare repo as --existing raises RuntimeError."""
        base = str(tmp_path)
        non_bare = os.path.join(base, "not_bare")
        subprocess.run(
            ["git", "init", non_bare],
            capture_output=True,
            text=True,
            check=True,
        )

        from sase.git_workspace import init_bare_git_project

        with pytest.raises(RuntimeError, match="not a valid bare git repository"):
            init_bare_git_project(
                project_name="fail",
                clone_dir=os.path.join(base, "clone"),
                existing_bare=non_bare,
            )
