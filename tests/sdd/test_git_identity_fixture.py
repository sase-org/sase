from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


_REPO_ROOT = Path(__file__).resolve().parents[2]
_TARGET_NODE = (
    "tests/sdd/test_git_identity_fixture.py"
    "::test_test_created_repo_can_commit_without_local_identity"
)
_TEST_AUTHOR = "SASE Test <sase-test@example.invalid>"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_test_created_repo_can_commit_without_local_identity(tmp_path: Path) -> None:
    global_config = Path(os.environ["GIT_CONFIG_GLOBAL"])
    system_config = Path(os.environ["GIT_CONFIG_SYSTEM"])
    assert global_config == system_config
    assert global_config.is_file()

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "README.md").write_text("# test repo\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "commit through suite fixture")

    assert _git(repo, "log", "-1", "--format=%an <%ae>") == _TEST_AUTHOR
    assert _git(repo, "config", "--global", "--get", "user.email") == (
        "sase-test@example.invalid"
    )


def test_sdd_git_identity_survives_empty_home_subprocess(tmp_path: Path) -> None:
    home = tmp_path / "empty-home"
    xdg_config = tmp_path / "empty-xdg-config"
    home.mkdir()
    xdg_config.mkdir()
    blank_system_config = tmp_path / "blank-system-gitconfig"
    blank_system_config.write_text("", encoding="utf-8")

    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_")
        and key
        not in {
            "PYTEST_ADDOPTS",
            "PYTEST_CURRENT_TEST",
            "PYTEST_XDIST_WORKER",
            "SASE_PYTEST_TMP_REDIRECTED",
        }
    }
    env["HOME"] = str(home)
    env["XDG_CONFIG_HOME"] = str(xdg_config)
    env["GIT_CONFIG_SYSTEM"] = str(blank_system_config)
    # Nested pytest is not a tools/run_pytest session. Inheriting the parent's
    # redirect marker would activate the session leak guard against the shared
    # managed temp root and the parent's redirected TMPDIR, so live-host or
    # sibling-worker scratch fails this git-identity check even when the inner
    # test passed.
    env["SASE_TMP_LEAK_GUARD_DISABLED"] = "1"
    env["PYTHONPATH"] = (
        str(_REPO_ROOT)
        if not env.get("PYTHONPATH")
        else f"{_REPO_ROOT}{os.pathsep}{env['PYTHONPATH']}"
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:randomly",
            "--rootdir",
            str(_REPO_ROOT),
            _TARGET_NODE,
        ],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert result.returncode == 0, result.stdout + result.stderr
