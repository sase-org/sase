"""End-to-end tests for bare-git project initialization."""

import shutil
import subprocess
from pathlib import Path

import pytest

from sase.workspace_provider.plugins.bare_git_init import (
    _run_git,
    init_bare_git_project,
)
from sase.workspace_provider.plugins.bare_git_ref import resolve_git_ref
from sase.workspace_provider.utils import ProjectProviderMismatchError

_GIT_AVAILABLE = shutil.which("git") is not None


def _git(repo: Path | None, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _configure_identity(repo: Path) -> None:
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")


def _commit_file(repo: Path, path: str, content: str, message: str) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git(repo, "add", path)
    _git(repo, "commit", "-m", message)


def _workspace_value(path: Path) -> str:
    return str(path) + "/"


def _isolate_sase_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SASE_HOME", str(home / ".sase"))
    return home


def _make_clone_with_history(clone: Path, bare: Path) -> None:
    _git(None, "init", str(clone))
    _configure_identity(clone)
    _commit_file(clone, "README.md", "main\n", "Main")
    _git(clone, "branch", "-M", "main")
    _git(clone, "checkout", "-b", "feature")
    _commit_file(clone, "feature.txt", "feature\n", "Feature")
    _git(clone, "checkout", "main")
    _git(clone, "remote", "add", "origin", str(bare))


def _seed_bare_with_history(tmp_path: Path, bare: Path) -> None:
    seed = tmp_path / f"{bare.stem}-seed"
    _git(None, "init", "--bare", str(bare))
    _git(None, "clone", str(bare), str(seed))
    _configure_identity(seed)
    _commit_file(seed, "app.py", "print('hi')\n", "Seed")
    _git(seed, "branch", "-M", "main")
    _git(seed, "push", "origin", "main")
    _git(None, "--git-dir", str(bare), "symbolic-ref", "HEAD", "refs/heads/main")


def _assert_project_spec(project_file: str, bare: Path, clone: Path) -> None:
    content = Path(project_file).read_text(encoding="utf-8")
    assert f"BARE_REPO_DIR: {bare}\n" in content
    assert f"WORKSPACE_DIR: {_workspace_value(clone)}\n" in content


@pytest.mark.skipif(not _GIT_AVAILABLE, reason="git not available")
class TestInitBareGitProjectEndToEnd:
    """Real git operations in tmp dirs to verify full init flow."""

    def test_new_project_initial_commit_contains_generated_sdd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _isolate_sase_home(tmp_path, monkeypatch)
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
        _isolate_sase_home(tmp_path, monkeypatch)
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

    def test_matching_clone_rebuilds_missing_bare_repo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _isolate_sase_home(tmp_path, monkeypatch)
        bare = tmp_path / "recovered.git"
        clone = tmp_path / "surviving"
        _make_clone_with_history(clone, bare)
        main_before = _git(clone, "rev-parse", "main").stdout.strip()
        feature_before = _git(clone, "rev-parse", "feature").stdout.strip()

        project_file = init_bare_git_project(
            "recovered",
            bare_dir=str(bare),
            clone_dir=str(clone),
        )

        assert _git(None, "--git-dir", str(bare), "rev-parse", "main").stdout.strip()
        assert (
            _git(None, "--git-dir", str(bare), "rev-parse", "main").stdout.strip()
            == main_before
        )
        assert (
            _git(None, "--git-dir", str(bare), "rev-parse", "feature").stdout.strip()
            == feature_before
        )
        assert (
            _git(
                None, "--git-dir", str(bare), "symbolic-ref", "--short", "HEAD"
            ).stdout.strip()
            == "main"
        )
        assert _git(clone, "rev-parse", "main").stdout.strip() == main_before
        _assert_project_spec(project_file, bare, clone)

    def test_matching_clone_rebuilds_empty_bare_repo_retry_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _isolate_sase_home(tmp_path, monkeypatch)
        bare = tmp_path / "retry.git"
        clone = tmp_path / "surviving"
        _git(None, "init", "--bare", str(bare))
        _make_clone_with_history(clone, bare)
        main_before = _git(clone, "rev-parse", "main").stdout.strip()

        project_file = init_bare_git_project(
            "retry",
            bare_dir=str(bare),
            clone_dir=str(clone),
        )

        assert (
            _git(None, "--git-dir", str(bare), "rev-parse", "main").stdout.strip()
            == main_before
        )
        _assert_project_spec(project_file, bare, clone)

    def test_matching_clone_with_populated_bare_repo_is_adopted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _isolate_sase_home(tmp_path, monkeypatch)
        bare = tmp_path / "adopt.git"
        clone = tmp_path / "adopt"
        _seed_bare_with_history(tmp_path, bare)
        _git(None, "clone", str(bare), str(clone))
        clone_count = _git(clone, "rev-list", "--count", "HEAD").stdout.strip()
        bare_count = _git(
            None, "--git-dir", str(bare), "rev-list", "--count", "HEAD"
        ).stdout.strip()

        project_file = init_bare_git_project(
            "adopt",
            bare_dir=str(bare),
            clone_dir=str(clone),
        )

        assert _git(clone, "rev-list", "--count", "HEAD").stdout.strip() == clone_count
        assert (
            _git(
                None, "--git-dir", str(bare), "rev-list", "--count", "HEAD"
            ).stdout.strip()
            == bare_count
        )
        assert not (clone / "sdd").exists()
        _assert_project_spec(project_file, bare, clone)

    def test_populated_bare_repo_missing_clone_is_cloned_without_initial_commit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _isolate_sase_home(tmp_path, monkeypatch)
        bare = tmp_path / "populated.git"
        clone = tmp_path / "materialized"
        _seed_bare_with_history(tmp_path, bare)

        init_bare_git_project(
            "populated",
            bare_dir=str(bare),
            clone_dir=str(clone),
        )

        subjects = _git(clone, "log", "--format=%s").stdout.splitlines()
        assert "Seed" in subjects
        assert "Initialize SDD" in subjects
        assert "Initial commit" not in subjects

    def test_conflict_non_git_non_empty_clone_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _isolate_sase_home(tmp_path, monkeypatch)
        bare = tmp_path / "conflict.git"
        clone = tmp_path / "conflict"
        clone.mkdir()
        (clone / "notes.txt").write_text("not a repo\n", encoding="utf-8")

        with pytest.raises(RuntimeError, match="not a git checkout"):
            init_bare_git_project(
                "conflict",
                bare_dir=str(bare),
                clone_dir=str(clone),
            )

    def test_conflict_clone_origin_points_elsewhere(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _isolate_sase_home(tmp_path, monkeypatch)
        expected = tmp_path / "expected.git"
        other = tmp_path / "other.git"
        clone = tmp_path / "wrong-origin"
        _make_clone_with_history(clone, other)

        with pytest.raises(RuntimeError, match="origin .* expected"):
            init_bare_git_project(
                "wrong-origin",
                bare_dir=str(expected),
                clone_dir=str(clone),
            )

    def test_conflict_bare_path_is_not_bare_repo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _isolate_sase_home(tmp_path, monkeypatch)
        bare = tmp_path / "not-bare.git"
        clone = tmp_path / "clone"
        bare.mkdir()
        (bare / "file.txt").write_text("not bare\n", encoding="utf-8")

        with pytest.raises(RuntimeError, match="not a valid bare git repository"):
            init_bare_git_project(
                "not-bare",
                bare_dir=str(bare),
                clone_dir=str(clone),
            )

    def test_path_ref_with_missing_clone_materializes_clone_and_spec(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _isolate_sase_home(tmp_path, monkeypatch)
        bare = tmp_path / "pathdemo.git"
        _seed_bare_with_history(tmp_path, bare)

        result = resolve_git_ref(str(bare))

        clone = home / "projects" / "git" / "pathdemo"
        assert result.project_name == "pathdemo"
        assert result.bare_repo_dir == str(bare)
        assert result.primary_workspace_dir == _workspace_value(clone)
        assert (clone / "app.py").is_file()
        _assert_project_spec(result.project_file, bare, clone)

    def test_existing_non_bare_git_project_spec_raises_provider_mismatch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression test for bare_git_project_clobber.

        A GitHub-style project spec (a real checkout whose origin is a
        hosted URL, no BARE_REPO_DIR) must not be silently converted into a
        bare-git project by ``init_bare_git_project``'s default-path
        destination colliding with the existing spec. This is the same
        guard exercised through ``resolve_git_ref`` in
        ``test_bare_git_workspace.py``, verified here at the
        ``init_bare_git_project`` call site directly (defense in depth for
        Mode 4's bare-repo-path dispatch, which calls this function too).
        """
        home = _isolate_sase_home(tmp_path, monkeypatch)
        project_dir = home / ".sase" / "projects" / "gh_acme__widget"
        project_file = project_dir / "gh_acme__widget.sase"
        checkout = home / "projects" / "github" / "acme" / "widget"
        project_dir.mkdir(parents=True)
        _git(None, "init", "-q", str(checkout))
        _git(checkout, "remote", "add", "origin", "https://github.com/acme/widget.git")
        original_content = f"WORKSPACE_DIR: {checkout}/\nPROJECT_NAME: widget\n"
        project_file.write_text(original_content, encoding="utf-8")

        with pytest.raises(ProjectProviderMismatchError):
            init_bare_git_project("gh_acme__widget")

        assert project_file.read_text(encoding="utf-8") == original_content
        assert not (home / ".sase" / "repos").exists()
        assert not (home / "projects" / "git").exists()


def test_run_git_error_includes_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(
        cmd: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(
            128,
            cmd,
            output="",
            stderr="fatal: destination path already exists",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError) as exc_info:
        _run_git(["clone", "/src.git", "/dst"])

    message = str(exc_info.value)
    assert "git clone /src.git /dst" in message
    assert "fatal: destination path already exists" in message
