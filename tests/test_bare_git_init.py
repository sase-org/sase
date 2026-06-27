"""End-to-end tests for bare-git project initialization."""

import shutil
import subprocess
from pathlib import Path

import pytest

from sase.workspace_provider.plugins.bare_git_init import init_bare_git_project

_GIT_AVAILABLE = shutil.which("git") is not None


def _git(repo: Path | None, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.skipif(not _GIT_AVAILABLE, reason="git not available")
class TestInitBareGitProjectEndToEnd:
    """Real git operations in tmp dirs to verify full init flow."""

    def test_new_project_initial_commit_contains_generated_sdd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        bare = tmp_path / "demo.git"
        clone = tmp_path / "demo"

        project_file = init_bare_git_project(
            "demo",
            bare_dir=str(bare),
            clone_dir=str(clone),
        )

        assert project_file.endswith("demo.sase")
        assert (clone / "sdd" / "README.md").is_file()
        tree = _git(
            None,
            "--git-dir",
            str(bare),
            "ls-tree",
            "-r",
            "--name-only",
            "HEAD",
        ).stdout.splitlines()
        assert "sdd/README.md" in tree
        assert "sdd/assets/sdd-directory-map.png" in tree

    def test_existing_bare_project_commits_generated_sdd_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        bare = tmp_path / "existing.git"
        seed = tmp_path / "seed"
        clone = tmp_path / "registered"
        _git(None, "init", "--bare", str(bare))
        _git(None, "clone", str(bare), str(seed))
        _git(seed, "config", "user.email", "test@example.com")
        _git(seed, "config", "user.name", "Test User")
        (seed / "app.py").write_text("print('hi')\n", encoding="utf-8")
        _git(seed, "add", "app.py")
        _git(seed, "commit", "-m", "Seed")
        _git(seed, "push", "origin", "HEAD")

        init_bare_git_project(
            "demo",
            clone_dir=str(clone),
            existing_bare=str(bare),
        )

        assert (clone / "sdd" / "README.md").is_file()
        commit_message = _git(clone, "log", "-1", "--format=%B").stdout.strip()
        assert commit_message == "Initialize SDD\n\nSASE_TYPE=init"
        committed_paths = _git(
            clone,
            "show",
            "--name-only",
            "--format=",
            "HEAD",
        ).stdout.splitlines()
        assert committed_paths
        assert all(path.startswith("sdd/") for path in committed_paths)
        remote_tree = _git(
            None,
            "--git-dir",
            str(bare),
            "ls-tree",
            "-r",
            "--name-only",
            "HEAD",
        ).stdout.splitlines()
        assert "app.py" in remote_tree
        assert "sdd/README.md" in remote_tree
