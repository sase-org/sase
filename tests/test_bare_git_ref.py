"""Tests for sase.workspace_provider.plugins.bare_git_ref.resolve_git_ref."""

import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.workspace_provider.plugins.bare_git_ref import ResolvedGitRef, resolve_git_ref
from sase.workspace_provider.utils import ProjectProviderMismatchError

_REF_MOD = "sase.workspace_provider.plugins.bare_git_ref"
_INIT_MOD = "sase.workspace_provider.plugins.bare_git_init"


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

    @patch(f"{_REF_MOD}.find_all_patches", return_value=[])
    @patch(f"{_INIT_MOD}.init_bare_git_project")
    def test_project_spec_without_workspace_dir_raises_provider_mismatch(
        self,
        mock_init: MagicMock,
        mock_find: MagicMock,
    ) -> None:
        """An existing spec with no WORKSPACE_DIR at all isn't bare-git yet.

        Previously this silently fell through to auto-init, converting
        whatever the spec actually was into a bare-git project. It must now
        fail loudly instead, unchanged, exactly like a spec for a real
        other-provider project (regression test for
        bare_git_project_clobber).
        """
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            project_file = home / ".sase" / "projects" / "home" / "home.sase"
            project_file.parent.mkdir(parents=True)
            original_content = "NAME: home\n"
            project_file.write_text(original_content, encoding="utf-8")

            with patch(f"{_REF_MOD}.Path.home", return_value=home):
                with pytest.raises(ProjectProviderMismatchError):
                    resolve_git_ref("home")

            assert project_file.read_text(encoding="utf-8") == original_content
            assert not (home / ".sase" / "repos").exists()
            assert not (home / "projects" / "git").exists()
            mock_find.assert_not_called()
            mock_init.assert_not_called()

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

    @patch(f"{_REF_MOD}.find_all_patches", return_value=[])
    @patch(f"{_INIT_MOD}.init_bare_git_project")
    def test_existing_project_with_unmaterialized_workspace_raises_provider_mismatch(
        self,
        mock_init: MagicMock,
        mock_find: MagicMock,
    ) -> None:
        """A spec whose WORKSPACE_DIR was never actually checked out.

        Regression test for bare_git_project_clobber: this is structurally
        identical to a real other-provider project's spec that has lost its
        BARE_REPO_DIR (e.g. a GitHub project's ``WORKSPACE_DIR`` pointing at
        its real checkout, whose origin is a github/https URL rather than a
        local path). Both must raise rather than silently convert the spec
        into a bare-git project.
        """
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            project_dir = home / ".sase" / "projects" / "plainproj"
            project_file = project_dir / "plainproj.sase"
            project_dir.mkdir(parents=True)
            original_content = "WORKSPACE_DIR: /work/plainproj/\nNAME: cl\n"
            project_file.write_text(original_content, encoding="utf-8")

            with patch(f"{_REF_MOD}.Path.home", return_value=home):
                with pytest.raises(ProjectProviderMismatchError):
                    resolve_git_ref("plainproj")

            assert project_file.read_text(encoding="utf-8") == original_content
            assert not (home / ".sase" / "repos").exists()
            assert not (home / "projects" / "git").exists()
            mock_find.assert_not_called()
            mock_init.assert_not_called()

    @patch(f"{_REF_MOD}.get_default_branch", return_value="origin/main")
    @patch(f"{_REF_MOD}.find_all_patches", return_value=[])
    @patch(f"{_INIT_MOD}.init_bare_git_project")
    def test_bare_git_project_missing_bare_repo_dir_still_heals(
        self,
        mock_init: MagicMock,
        mock_find: MagicMock,
        mock_branch: MagicMock,
    ) -> None:
        """A bare-git project that merely lost BARE_REPO_DIR still auto-heals.

        Distinguishes the dff269e3a healing case from the new
        provider-mismatch guard: this checkout's origin is a local
        filesystem path, so ``is_bare_git_project`` still recognizes it as
        bare-git even without the BARE_REPO_DIR field, and today's
        missing-project init path is left free to repair it.
        """
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            project_dir = home / ".sase" / "projects" / "recovering"
            project_file = project_dir / "recovering.sase"
            bare_dir = home / ".sase" / "repos" / "recovering.git"
            workspace_dir = str(home / "projects" / "git" / "recovering") + "/"
            checkout = home / "checkout"

            subprocess.run(["git", "init", "-q", str(checkout)], check=True)
            subprocess.run(
                ["git", "remote", "add", "origin", "/some/local/bare.git"],
                cwd=checkout,
                check=True,
            )

            project_dir.mkdir(parents=True)
            project_file.write_text(
                f"WORKSPACE_DIR: {checkout}/\nNAME: cl\n",
                encoding="utf-8",
            )

            def init_project(project_name: str) -> str:
                assert project_name == "recovering"
                project_file.write_text(
                    f"BARE_REPO_DIR: {bare_dir}\nWORKSPACE_DIR: {workspace_dir}\n",
                    encoding="utf-8",
                )
                return str(project_file)

            mock_init.side_effect = init_project

            with patch(f"{_REF_MOD}.Path.home", return_value=home):
                result = resolve_git_ref("recovering")

            assert result == ResolvedGitRef(
                project_file=str(project_file),
                project_name="recovering",
                primary_workspace_dir=workspace_dir,
                bare_repo_dir=str(bare_dir),
                checkout_target="origin/main",
            )
            mock_find.assert_called_once()
            mock_init.assert_called_once_with("recovering")
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

    @patch(f"{_REF_MOD}.find_all_patches", return_value=[])
    @patch(f"{_INIT_MOD}.init_bare_git_project")
    def test_claimed_project_name_raises_provider_mismatch(
        self,
        mock_init: MagicMock,
        mock_find: MagicMock,
        tmp_path: Path,
    ) -> None:
        from sase.core.paths import sase_projects_dir

        checkout = tmp_path / "github" / "sase"
        checkout.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(checkout)], check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/org/sase.git"],
            cwd=checkout,
            check=True,
        )
        project_dir = sase_projects_dir() / "gh_org__sase"
        project_dir.mkdir(parents=True)
        project_file = project_dir / "gh_org__sase.sase"
        project_file.write_text(
            f"WORKSPACE_DIR: {checkout}/\nPROJECT_NAME: sase\nNAME: c\n",
            encoding="utf-8",
        )

        with pytest.raises(
            ProjectProviderMismatchError, match="not a bare-git project"
        ):
            resolve_git_ref("sase")

        assert not (sase_projects_dir() / "sase").exists()
        mock_find.assert_not_called()
        mock_init.assert_not_called()

    @patch(f"{_REF_MOD}.get_default_branch", return_value="origin/main")
    @patch(f"{_REF_MOD}.find_all_patches", return_value=[])
    @patch(f"{_INIT_MOD}.init_bare_git_project")
    def test_claimed_alias_resolves_canonical_bare_git_project(
        self,
        mock_init: MagicMock,
        mock_find: MagicMock,
        mock_branch: MagicMock,
        tmp_path: Path,
    ) -> None:
        from sase.core.paths import sase_projects_dir

        project_dir = sase_projects_dir() / "demo"
        project_dir.mkdir(parents=True)
        project_file = project_dir / "demo.sase"
        project_file.write_text(
            "WORKSPACE_DIR: /work/demo/\n"
            "BARE_REPO_DIR: /repos/demo.git\n"
            "PROJECT_ALIASES: nick\n"
            "NAME: c\n",
            encoding="utf-8",
        )

        result = resolve_git_ref("nick")

        assert result.project_name == "demo"
        assert result.bare_repo_dir == "/repos/demo.git"
        assert result.primary_workspace_dir == "/work/demo/"
        mock_init.assert_not_called()
        mock_find.assert_not_called()
        mock_branch.assert_called_once_with("/work/demo/")

    @patch(f"{_INIT_MOD}.init_bare_git_project")
    def test_bare_repo_path_claimed_name_raises_provider_mismatch(
        self,
        mock_init: MagicMock,
        tmp_path: Path,
    ) -> None:
        from sase.core.paths import sase_projects_dir

        checkout = tmp_path / "github" / "sase"
        checkout.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(checkout)], check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/org/sase.git"],
            cwd=checkout,
            check=True,
        )
        project_dir = sase_projects_dir() / "gh_org__sase"
        project_dir.mkdir(parents=True)
        (project_dir / "gh_org__sase.sase").write_text(
            f"WORKSPACE_DIR: {checkout}/\nPROJECT_NAME: sase\nNAME: c\n",
            encoding="utf-8",
        )

        with pytest.raises(
            ProjectProviderMismatchError, match="not a bare-git project"
        ):
            resolve_git_ref("/repos/sase.git")

        mock_init.assert_not_called()
