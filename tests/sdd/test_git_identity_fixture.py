from __future__ import annotations

from collections.abc import Mapping
import getpass
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
_CHILD_BASETEMP_NAME = "nested-pytest-basetemp"
_CHILD_TMPDIR_NAME = "nested-pytest-tmpdir"
_NESTED_TIMEOUT_SECONDS = 180
_INHERITED_TEMP_MARKER = "unrelated sibling scratch\n"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _copy_parent_env() -> dict[str, str]:
    return {
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


def _isolate_nested_pytest_temp(env: dict[str, str], tmp_path: Path) -> Path:
    """Give the nested pytest private temp dirs owned by the outer ``tmp_path``.

    An explicit ``--basetemp`` skips pytest's numbered-directory cleanup of
    ``pytest-*`` and ``garbage-*`` entries under an inherited temp root. The
    child's ``TMPDIR`` / ``TEMP`` / ``TMP`` / ``PYTEST_DEBUG_TEMPROOT`` are
    redirected to a separate private directory so inherited overrides cannot
    restore that shared cleanup. Outer pytest owns cleanup of both
    directories, including failure retention. Parent ``os.environ`` is not
    mutated.
    """
    child_tmpdir = tmp_path / _CHILD_TMPDIR_NAME
    child_tmpdir.mkdir()
    env["TMPDIR"] = str(child_tmpdir)
    env["TEMP"] = str(child_tmpdir)
    env["TMP"] = str(child_tmpdir)
    env["PYTEST_DEBUG_TEMPROOT"] = str(child_tmpdir)
    return tmp_path / _CHILD_BASETEMP_NAME


def _empty_home_identity_env(
    tmp_path: Path,
    extra_env: Mapping[str, str] | None = None,
) -> tuple[dict[str, str], Path]:
    home = tmp_path / "empty-home"
    xdg_config = tmp_path / "empty-xdg-config"
    home.mkdir()
    xdg_config.mkdir()
    blank_system_config = tmp_path / "blank-system-gitconfig"
    blank_system_config.write_text("", encoding="utf-8")

    env = _copy_parent_env()
    if extra_env:
        env.update(extra_env)
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
    child_basetemp = _isolate_nested_pytest_temp(env, tmp_path)
    return env, child_basetemp


def _run_empty_home_identity_child(
    tmp_path: Path,
    extra_env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env, child_basetemp = _empty_home_identity_env(tmp_path, extra_env)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:randomly",
            "--rootdir",
            str(_REPO_ROOT),
            "--basetemp",
            str(child_basetemp),
            _TARGET_NODE,
        ],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=_NESTED_TIMEOUT_SECONDS,
    )


def _pytest_temp_user() -> str:
    try:
        return getpass.getuser() or "unknown"
    except (ImportError, OSError, KeyError):
        return "unknown"


def _seed_old_pytest_numbered_dir(root: Path) -> list[Path]:
    """Seed numbered dirs that default pytest temp-root cleanup would remove.

    This project's ``tmp_path_retention_count`` keeps one numbered session.
    A newer ``pytest-1`` decoy makes ``pytest-0`` a cleanup candidate once a
    nested pytest without ``--basetemp`` joins the same root.
    """
    markers: list[Path] = []
    for name in dict.fromkeys((_pytest_temp_user(), "unknown")):
        owner = root / f"pytest-of-{name}"
        old_dir = owner / "pytest-0"
        newer_dir = owner / "pytest-1"
        old_dir.mkdir(parents=True)
        newer_dir.mkdir(parents=True)
        (newer_dir / "newer-session").write_text("keep-count decoy\n", encoding="utf-8")
        marker = old_dir / "KEEP_ME"
        marker.write_text(_INHERITED_TEMP_MARKER, encoding="utf-8")
        markers.append(marker)
    return markers


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


def test_test_created_repo_never_forks_background_maintenance(tmp_path: Path) -> None:
    """A commit must not fork a detached ``git maintenance`` that races copies.

    The detached run creates and removes ``.git/objects/maintenance.lock`` while a
    test is still copying or listing the repository it just committed to.
    """
    assert (
        subprocess.run(
            ["git", "config", "--global", "--get", "maintenance.auto"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        == "false"
    )

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "README.md").write_text("# test repo\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    trace = tmp_path / "trace2.jsonl"
    subprocess.run(
        ["git", "commit", "-q", "-m", "commit under trace"],
        cwd=repo,
        check=True,
        env={**os.environ, "GIT_TRACE2_EVENT": str(trace)},
    )

    assert trace.read_text(encoding="utf-8").strip()
    assert '"maintenance"' not in trace.read_text(encoding="utf-8")


def test_sdd_git_identity_survives_empty_home_subprocess(tmp_path: Path) -> None:
    inherited_tmpdir = tmp_path / "inherited-tmpdir"
    inherited_debug = tmp_path / "inherited-debug-temproot"
    markers = (
        *_seed_old_pytest_numbered_dir(inherited_tmpdir),
        *_seed_old_pytest_numbered_dir(inherited_debug),
    )

    result = _run_empty_home_identity_child(
        tmp_path,
        extra_env={
            "TMPDIR": str(inherited_tmpdir),
            "TEMP": str(inherited_tmpdir),
            "TMP": str(inherited_tmpdir),
            "PYTEST_DEBUG_TEMPROOT": str(inherited_debug),
        },
    )

    assert result.returncode == 0, result.stdout + result.stderr
    for marker in markers:
        assert marker.is_file()
        assert marker.read_text(encoding="utf-8") == _INHERITED_TEMP_MARKER
        assert not (marker.parent.parent / "pytest-2").exists()
    child_basetemp = tmp_path / _CHILD_BASETEMP_NAME
    # Inner tmp_path is removed after a passing test; the session identity
    # config is created with tmp_path_factory.mktemp and stays under --basetemp.
    assert any(child_basetemp.rglob("gitconfig"))
