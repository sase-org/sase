"""Tests for sase.workspace_provider.plugins.bare_git_* modules."""

import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.workspace_provider.plugins.bare_git_ref import (
    ResolvedGitRef,
    resolve_git_ref,
    set_bare_repo_dir,
)
from sase.workspace_provider.plugins.bare_git_init import init_bare_git_project

_REF_MOD = "sase.workspace_provider.plugins.bare_git_ref"
_INIT_MOD = "sase.workspace_provider.plugins.bare_git_init"


# ── set_bare_repo_dir ───────────────────────────────────────────────


class TestSetBareRepoDir:
    def test_creates_directory(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            gp = os.path.join(d, "subdir", "proj.sase")
            assert set_bare_repo_dir(gp, "/repos/proj.git")
            assert os.path.exists(gp)

    @patch(f"{_REF_MOD}.write_patch_atomic")
    @patch(f"{_REF_MOD}.patch_lock")
    def test_updates_existing(
        self, mock_lock: MagicMock, mock_write: MagicMock, tmp_path: Path
    ) -> None:
        mock_lock.return_value.__enter__ = MagicMock()
        mock_lock.return_value.__exit__ = MagicMock(return_value=False)
        with tempfile.NamedTemporaryFile(
            dir=tmp_path, mode="w", suffix=".sase", delete=False
        ) as f:
            f.write("BARE_REPO_DIR: /old/repo.git\nNAME: cl\n")
            f.flush()
            assert set_bare_repo_dir(f.name, "/new/repo.git")
            mock_write.assert_called_once()
            written = mock_write.call_args[0][1]
            assert "BARE_REPO_DIR: /new/repo.git" in written
            assert "/old/repo.git" not in written
            os.unlink(f.name)

    @patch(f"{_REF_MOD}.write_patch_atomic")
    @patch(f"{_REF_MOD}.patch_lock")
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
            assert set_bare_repo_dir(f.name, "/repos/proj.git")
            written = mock_write.call_args[0][1]
            lines = written.splitlines()
            bare_idx = next(
                i for i, ln in enumerate(lines) if ln.startswith("BARE_REPO_DIR:")
            )
            run_idx = next(i for i, ln in enumerate(lines) if ln.startswith("RUNNING:"))
            assert bare_idx < run_idx
            os.unlink(f.name)


# ── resolve_git_ref ──────────────────────────────────────────────────


class TestResolveGitRef:
    @patch(f"{_REF_MOD}.get_default_branch", return_value="origin/main")
    def test_project_shorthand(self, mock_branch: MagicMock) -> None:
        with tempfile.TemporaryDirectory() as d:
            with patch(f"{_REF_MOD}.Path.home", return_value=Path(d)):
                proj_dir = os.path.join(d, ".sase", "projects", "myproj")
                os.makedirs(proj_dir)
                gp = os.path.join(proj_dir, "myproj.sase")
                with open(gp, "w") as f:
                    f.write(
                        "WORKSPACE_DIR: /work/myproj/\n"
                        "BARE_REPO_DIR: /repos/myproj.git\n"
                        "NAME: cl\n"
                    )

                result = resolve_git_ref("myproj")
                assert isinstance(result, ResolvedGitRef)
                assert result.project_name == "myproj"
                assert result.primary_workspace_dir == "/work/myproj/"
                assert result.bare_repo_dir == "/repos/myproj.git"
                assert result.checkout_target == "origin/main"

    @patch(f"{_REF_MOD}.get_default_branch", return_value="origin/main")
    @patch(f"{_INIT_MOD}.init_bare_git_project")
    @patch(f"{_REF_MOD}.find_all_patches")
    def test_patch_name(
        self,
        mock_find: MagicMock,
        mock_init: MagicMock,
        mock_branch: MagicMock,
    ) -> None:
        with tempfile.TemporaryDirectory() as d:
            gp = os.path.join(d, "proj.sase")
            with open(gp, "w") as f:
                f.write(
                    "WORKSPACE_DIR: /work/proj/\n"
                    "BARE_REPO_DIR: /repos/proj.git\n"
                    "NAME: my-feature\n"
                )

            cs = MagicMock()
            cs.name = "my-feature"
            cs.file_path = gp
            cs.project_basename = "proj"
            mock_find.return_value = [cs]

            with patch(
                f"{_REF_MOD}.Path.home",
                return_value=Path("/nonexistent"),
            ):
                result = resolve_git_ref("my-feature")
                assert result.checkout_target == "origin/my-feature"
                assert result.project_name == "proj"
                assert result.bare_repo_dir == "/repos/proj.git"
                mock_init.assert_not_called()

    @patch(f"{_REF_MOD}.find_all_patches", return_value=[])
    def test_empty_project_name_not_initialized(self, mock_find: MagicMock) -> None:
        with patch(
            f"{_REF_MOD}.Path.home",
            return_value=Path("/nonexistent"),
        ):
            with pytest.raises(ValueError, match="empty ref"):
                resolve_git_ref("")

    @patch(f"{_REF_MOD}.find_all_patches", return_value=[])
    @patch(f"{_INIT_MOD}.init_bare_git_project")
    def test_hidden_project_name_not_auto_initialized(
        self,
        mock_init: MagicMock,
        mock_find: MagicMock,
    ) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            hidden_dir = home / ".sase" / "projects" / ".sase"
            hidden_dir.mkdir(parents=True)
            (hidden_dir / ".sase.sase").write_text("", encoding="utf-8")

            with patch(f"{_REF_MOD}.Path.home", return_value=home):
                with pytest.raises(ValueError, match="invalid SASE project name"):
                    resolve_git_ref(".sase")

        mock_find.assert_called_once()
        mock_init.assert_not_called()

    @patch(f"{_REF_MOD}.get_default_branch", return_value="origin/main")
    @patch(f"{_REF_MOD}.find_all_patches", return_value=[])
    @patch(f"{_INIT_MOD}.init_bare_git_project")
    def test_home_project_without_bare_repo_auto_initializes(
        self,
        mock_init: MagicMock,
        mock_find: MagicMock,
        mock_branch: MagicMock,
    ) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            project_file = home / ".sase" / "projects" / "home" / "home.sase"
            bare_dir = home / ".sase" / "repos" / "home.git"
            workspace_dir = str(home / "projects" / "git" / "home") + "/"
            project_file.parent.mkdir(parents=True)
            project_file.write_text("NAME: home\n", encoding="utf-8")

            def init_project(project_name: str) -> str:
                assert project_name == "home"
                project_file.write_text(
                    f"BARE_REPO_DIR: {bare_dir}\nWORKSPACE_DIR: {workspace_dir}\n",
                    encoding="utf-8",
                )
                return str(project_file)

            mock_init.side_effect = init_project

            with patch(f"{_REF_MOD}.Path.home", return_value=home):
                result = resolve_git_ref("home")

            assert result == ResolvedGitRef(
                project_file=str(project_file),
                project_name="home",
                primary_workspace_dir=workspace_dir,
                bare_repo_dir=str(bare_dir),
                checkout_target="origin/main",
            )
            mock_find.assert_called_once()
            mock_init.assert_called_once_with("home")
            mock_branch.assert_called_once_with(workspace_dir)

    @patch(f"{_REF_MOD}.get_default_branch", return_value="origin/main")
    @patch(f"{_REF_MOD}.find_all_patches", return_value=[])
    @patch(f"{_INIT_MOD}.init_bare_git_project")
    def test_missing_project_name_auto_initializes(
        self,
        mock_init: MagicMock,
        mock_find: MagicMock,
        mock_branch: MagicMock,
    ) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            project_file = home / ".sase" / "projects" / "newproj" / "newproj.sase"
            bare_dir = home / ".sase" / "repos" / "newproj.git"
            workspace_dir = str(home / "projects" / "git" / "newproj") + "/"

            def init_project(project_name: str) -> str:
                assert project_name == "newproj"
                project_file.parent.mkdir(parents=True)
                project_file.write_text(
                    f"BARE_REPO_DIR: {bare_dir}\nWORKSPACE_DIR: {workspace_dir}\n",
                    encoding="utf-8",
                )
                return str(project_file)

            mock_init.side_effect = init_project

            with patch(f"{_REF_MOD}.Path.home", return_value=home):
                result = resolve_git_ref("newproj")

            assert result == ResolvedGitRef(
                project_file=str(project_file),
                project_name="newproj",
                primary_workspace_dir=workspace_dir,
                bare_repo_dir=str(bare_dir),
                checkout_target="origin/main",
            )
            mock_find.assert_called_once()
            mock_init.assert_called_once_with("newproj")
            mock_branch.assert_called_once_with(workspace_dir)

            from sase.core.project_lifecycle_facade import list_project_records

            records = list_project_records(
                home / ".sase" / "projects",
                "enabled",
                projects_only=True,
            )
            assert len(records) == 1
            assert records[0].project_name == "newproj"
            assert records[0].is_project is True
            assert records[0].vcs_kind == "git"

    @patch(f"{_REF_MOD}.get_default_branch", return_value="origin/main")
    @patch(f"{_REF_MOD}.find_all_patches", return_value=[])
    @patch(f"{_INIT_MOD}.init_bare_git_project")
    def test_existing_project_without_bare_repo_auto_initializes(
        self,
        mock_init: MagicMock,
        mock_find: MagicMock,
        mock_branch: MagicMock,
    ) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            project_dir = home / ".sase" / "projects" / "plainproj"
            project_file = project_dir / "plainproj.sase"
            bare_dir = home / ".sase" / "repos" / "plainproj.git"
            workspace_dir = str(home / "projects" / "git" / "plainproj") + "/"
            project_dir.mkdir(parents=True)
            project_file.write_text(
                "WORKSPACE_DIR: /work/plainproj/\nNAME: cl\n",
                encoding="utf-8",
            )

            def init_project(project_name: str) -> str:
                assert project_name == "plainproj"
                project_file.write_text(
                    f"BARE_REPO_DIR: {bare_dir}\nWORKSPACE_DIR: {workspace_dir}\n",
                    encoding="utf-8",
                )
                return str(project_file)

            mock_init.side_effect = init_project

            with patch(f"{_REF_MOD}.Path.home", return_value=home):
                result = resolve_git_ref("plainproj")

            assert result == ResolvedGitRef(
                project_file=str(project_file),
                project_name="plainproj",
                primary_workspace_dir=workspace_dir,
                bare_repo_dir=str(bare_dir),
                checkout_target="origin/main",
            )

            mock_find.assert_called_once()
            mock_init.assert_called_once_with("plainproj")
            mock_branch.assert_called_once_with(workspace_dir)

    @patch(f"{_REF_MOD}.find_all_patches", return_value=[])
    @patch(f"{_INIT_MOD}.init_bare_git_project")
    def test_project_with_bare_repo_without_workspace_is_not_initialized(
        self,
        mock_init: MagicMock,
        mock_find: MagicMock,
    ) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            project_dir = home / ".sase" / "projects" / "home"
            project_dir.mkdir(parents=True)
            (project_dir / "home.sase").write_text(
                "BARE_REPO_DIR: /repos/home.git\nNAME: home\n",
                encoding="utf-8",
            )

            with patch(f"{_REF_MOD}.Path.home", return_value=home):
                with pytest.raises(
                    ValueError,
                    match="Project 'home' has BARE_REPO_DIR but WORKSPACE_DIR is not set",
                ):
                    resolve_git_ref("home")

            mock_find.assert_not_called()
            mock_init.assert_not_called()

    @patch(f"{_REF_MOD}.get_default_branch", return_value="origin/main")
    @patch(f"{_INIT_MOD}.init_bare_git_project")
    def test_bare_repo_path_strips_git_suffix(
        self,
        mock_init: MagicMock,
        mock_branch: MagicMock,
    ) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            project_file = home / ".sase" / "projects" / "foo" / "foo.sase"
            clone_dir = str(home / "projects" / "git" / "foo") + "/"

            def init_project(
                project_name: str,
                *,
                existing_bare: str,
                clone_dir: str,
            ) -> str:
                assert project_name == "foo"
                assert existing_bare == "/repos/foo.git"
                project_file.parent.mkdir(parents=True)
                project_file.write_text(
                    f"BARE_REPO_DIR: {existing_bare}\nWORKSPACE_DIR: {clone_dir}\n",
                    encoding="utf-8",
                )
                return str(project_file)

            mock_init.side_effect = init_project
            with patch(f"{_REF_MOD}.Path.home", return_value=home):
                result = resolve_git_ref("/repos/foo.git")
                assert result.project_name == "foo"
                assert result.primary_workspace_dir == clone_dir
                assert result.bare_repo_dir == "/repos/foo.git"
                mock_branch.assert_called_once_with(clone_dir)

    def test_invalid_empty_basename(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            with patch(f"{_REF_MOD}.Path.home", return_value=Path(d)):
                with pytest.raises(ValueError, match="Cannot derive project name"):
                    resolve_git_ref("/.git")

    @patch(f"{_INIT_MOD}.init_bare_git_project")
    def test_bare_repo_path_hidden_basename_is_rejected(
        self,
        mock_init: MagicMock,
    ) -> None:
        with tempfile.TemporaryDirectory() as d:
            with patch(f"{_REF_MOD}.Path.home", return_value=Path(d)):
                with pytest.raises(ValueError, match="invalid SASE project name"):
                    resolve_git_ref("/repos/.sase.git")

        mock_init.assert_not_called()


# ── init_bare_git_project ────────────────────────────────────────────


class TestInitBareGitProject:
    def test_git_runner_removes_persistent_index_lock_after_retries(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from sase.git_lock_retry import ENV_GIT_LOCK_RETRY_DELAYS
        from sase.workspace_provider.plugins.bare_git_init import _run_git

        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        tracked = tmp_path / "tracked.txt"
        tracked.write_text("content\n", encoding="utf-8")
        lock_path = tmp_path / ".git" / "index.lock"
        lock_path.touch()
        monkeypatch.setenv(ENV_GIT_LOCK_RETRY_DELAYS, "0.001")

        result = _run_git(["add", "tracked.txt"], cwd=tmp_path)

        assert result.returncode == 0
        assert not lock_path.exists()

    @patch(f"{_INIT_MOD}.set_workspace_dir", return_value=True)
    @patch(f"{_INIT_MOD}.set_bare_repo_dir", return_value=True)
    @patch(f"{_INIT_MOD}.subprocess.run")
    def test_new_project(
        self,
        mock_run: MagicMock,
        mock_set_bare: MagicMock,
        mock_set_ws: MagicMock,
    ) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as d:
            with patch(f"{_INIT_MOD}.Path.home", return_value=Path(d)):
                bare_dir = os.path.join(d, "repos", "test.git")
                clone_dir = os.path.join(d, "projects", "test") + "/"
                result = init_bare_git_project(
                    "test", bare_dir=bare_dir, clone_dir=clone_dir
                )
                assert result.endswith("test.sase")
                # git init --bare, git clone, git config email,
                # git config name, git add generated SDD files, git commit, git push
                assert mock_run.call_count == 7
                commit_calls = [
                    call.args[0]
                    for call in mock_run.call_args_list
                    if "commit" in call.args[0] and "-m" in call.args[0]
                ]
                assert commit_calls
                message = commit_calls[0][commit_calls[0].index("-m") + 1]
                assert message == "Initial commit\n\nSASE_TYPE=init"
                mock_set_bare.assert_called_once()
                mock_set_ws.assert_called_once()

    @patch(f"{_INIT_MOD}.set_workspace_dir", return_value=True)
    @patch(f"{_INIT_MOD}.set_bare_repo_dir", return_value=True)
    @patch(f"{_INIT_MOD}.subprocess.run")
    def test_existing_bare(
        self,
        mock_run: MagicMock,
        mock_set_bare: MagicMock,
        mock_set_ws: MagicMock,
    ) -> None:
        # First call: git rev-parse --is-bare-repository → true
        # Second call: git show-ref --quiet → has refs
        # Third call: git clone
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="true\n", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),
        ]
        with tempfile.TemporaryDirectory() as d:
            with (
                patch(f"{_INIT_MOD}.Path.home", return_value=Path(d)),
                patch("sase.sdd.files.ensure_bare_git_sdd_initialized") as ensure_sdd,
            ):
                existing = os.path.join(d, "existing.git")
                os.makedirs(existing)
                clone_dir = os.path.join(d, "clone") + "/"
                result = init_bare_git_project(
                    "test", clone_dir=clone_dir, existing_bare=existing
                )
                assert result.endswith("test.sase")
                assert mock_run.call_count == 3
                # bare_dir should be the existing path
                mock_set_bare.assert_called_once_with(result, existing)
                ensure_sdd.assert_called_once_with(
                    clone_dir,
                    commit=True,
                    push=True,
                    raise_on_error=True,
                )

    @patch(f"{_INIT_MOD}.subprocess.run")
    def test_invalid_existing_bare(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="false\n", stderr="")
        with tempfile.TemporaryDirectory() as d:
            with patch(f"{_INIT_MOD}.Path.home", return_value=Path(d)):
                existing = os.path.join(d, "some", "dir")
                os.makedirs(existing)
                with pytest.raises(RuntimeError, match="not a valid bare"):
                    init_bare_git_project(
                        "test",
                        clone_dir=os.path.join(d, "clone") + "/",
                        existing_bare=existing,
                    )

    @patch(f"{_INIT_MOD}.subprocess.run")
    def test_hidden_project_name_is_rejected_before_git_commands(
        self, mock_run: MagicMock
    ) -> None:
        with tempfile.TemporaryDirectory() as d:
            with patch(f"{_INIT_MOD}.Path.home", return_value=Path(d)):
                with pytest.raises(ValueError, match="invalid SASE project name"):
                    init_bare_git_project(
                        ".sase",
                        bare_dir=os.path.join(d, ".sase.git"),
                        clone_dir=os.path.join(d, ".sase") + "/",
                    )

        mock_run.assert_not_called()


# ── ws_get_workspace_name ─────────────────────────────────────────

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
