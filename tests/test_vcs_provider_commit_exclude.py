"""Real-repo coverage for -x/--exclude commit staging."""

from __future__ import annotations

import subprocess
from pathlib import Path

from sase.bead.project import BEADS_DIRNAME
from sase.vcs_provider.plugins.bare_git import BareGitPlugin


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )


def _configure_user(cwd: Path) -> None:
    _git(cwd, "config", "user.email", "test@example.com")
    _git(cwd, "config", "user.name", "Test User")


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--initial-branch=master")
    _configure_user(repo)
    (repo / "tracked.txt").write_text("one\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "base")
    return repo


def test_create_commit_default_stages_modified_and_untracked(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    (repo / "tracked.txt").write_text("two\n", encoding="utf-8")
    (repo / "new_file.txt").write_text("new\n", encoding="utf-8")

    ok, err = BareGitPlugin().vcs_create_commit(
        {"message": "chore: stage all"}, str(repo)
    )

    assert ok is True, err
    assert _git(repo, "status", "--short").stdout == ""
    log = _git(repo, "show", "--stat", "HEAD").stdout
    assert "tracked.txt" in log
    assert "new_file.txt" in log


def test_create_commit_exclude_file_leaves_it_dirty(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    (repo / "tracked.txt").write_text("two\n", encoding="utf-8")
    (repo / "new_file.txt").write_text("new\n", encoding="utf-8")

    ok, err = BareGitPlugin().vcs_create_commit(
        {"message": "chore: exclude one file", "exclude": ["new_file.txt"]},
        str(repo),
    )

    assert ok is True, err
    assert "new_file.txt" in _git(repo, "status", "--short").stdout
    log = _git(repo, "show", "--stat", "HEAD").stdout
    assert "new_file.txt" not in log
    assert "tracked.txt" in log


def test_create_commit_exclude_directory_leaves_subtree_dirty(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    (repo / "keepout").mkdir()
    (repo / "keepout" / "a.txt").write_text("a\n", encoding="utf-8")
    (repo / "keepout" / "b.txt").write_text("b\n", encoding="utf-8")
    (repo / "tracked.txt").write_text("two\n", encoding="utf-8")

    ok, err = BareGitPlugin().vcs_create_commit(
        {"message": "chore: exclude dir", "exclude": ["keepout"]},
        str(repo),
    )

    assert ok is True, err
    status = _git(repo, "status", "--short", "--untracked-files=all").stdout
    assert "keepout/a.txt" in status
    assert "keepout/b.txt" in status
    log = _git(repo, "show", "--stat", "HEAD").stdout
    assert "keepout" not in log
    assert "tracked.txt" in log


def test_create_commit_exclude_unmatched_fails_before_any_commit(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    (repo / "tracked.txt").write_text("two\n", encoding="utf-8")
    before_head = _git(repo, "rev-parse", "HEAD").stdout.strip()

    ok, err = BareGitPlugin().vcs_create_commit(
        {"message": "chore: bad exclude", "exclude": ["does_not_exist.txt"]},
        str(repo),
    )

    assert ok is False
    assert err is not None and "does_not_exist.txt" in err
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == before_head
    assert "tracked.txt" in _git(repo, "status", "--short").stdout


def test_create_commit_exclude_covering_bead_store_is_refused(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    (repo / BEADS_DIRNAME).mkdir(parents=True)
    (repo / BEADS_DIRNAME / "issues.jsonl").write_text("{}\n", encoding="utf-8")
    (repo / "tracked.txt").write_text("two\n", encoding="utf-8")

    ok, err = BareGitPlugin().vcs_create_commit(
        {"message": "chore: exclude beads", "exclude": [BEADS_DIRNAME]},
        str(repo),
    )

    assert ok is False
    assert err is not None and "commit workflow owns this path" in err


def test_create_commit_exclude_covering_plan_path_is_refused(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    (repo / "sdd" / "plans" / "202608").mkdir(parents=True)
    plan_path = "sdd/plans/202608/my_plan.md"
    (repo / plan_path).write_text("plan\n", encoding="utf-8")
    (repo / "tracked.txt").write_text("two\n", encoding="utf-8")

    ok, err = BareGitPlugin().vcs_create_commit(
        {
            "message": "chore: exclude plan",
            "exclude": ["sdd/plans"],
            "_plan_path": plan_path,
        },
        str(repo),
    )

    assert ok is False
    assert err is not None and "commit workflow owns this path" in err


def test_create_pull_request_exclude_refused_before_branch_created(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    (repo / "tracked.txt").write_text("two\n", encoding="utf-8")
    before_branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    ok, err = BareGitPlugin().vcs_create_pull_request(
        {
            "name": "feat-x",
            "message": "feat: add feature",
            "exclude": ["does_not_exist.txt"],
        },
        str(repo),
    )

    assert ok is False
    assert err is not None and "does_not_exist.txt" in err
    assert (
        _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == before_branch
    )
