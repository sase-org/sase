"""Tests for the Agents-tab revert backend (:mod:`sase.ace.revert_agent`)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from sase.ace.revert_agent import (
    _discover_agent_commits,
    execute_agent_revert,
    preview_agent_revert,
)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "sase@localhost")
    _git(repo, "config", "user.name", "sase")
    # A base commit so tagged commits are never the root commit.
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "base")


def _commit(repo: Path, message: str, files: dict[str, str]) -> str:
    for rel, content in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        _git(repo, "add", rel)
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD").strip()


def _msg(subject: str, agent: str) -> str:
    return f"{subject}\n\nAGENT={agent}\nTYPE=sdd"


def test_discover_exact_tag_matching(tmp_path: Path) -> None:
    repo = tmp_path / "ws"
    _init_repo(repo)
    _commit(repo, _msg("foo one", "foo"), {"a.txt": "a1\n"})
    _commit(repo, _msg("bar one", "bar"), {"b.txt": "b1\n"})
    _commit(repo, _msg("foo two", "foo"), {"a.txt": "a2\n"})

    commits = _discover_agent_commits(str(repo), "foo")

    subjects = [c.subject for c in commits]
    # Newest-first, exact AGENT=foo only (bar excluded).
    assert subjects == ["foo two", "foo one"]
    assert all(c.agent_tag == "foo" for c in commits)


def test_discover_family_matching(tmp_path: Path) -> None:
    repo = tmp_path / "ws"
    _init_repo(repo)
    _commit(repo, _msg("plan", "feat--plan"), {"p.txt": "p\n"})
    _commit(repo, _msg("code", "feat--code"), {"c.txt": "c\n"})
    _commit(repo, _msg("other", "other--plan"), {"o.txt": "o\n"})

    family = _discover_agent_commits(str(repo), "feat--plan", family_base="feat")
    exact = _discover_agent_commits(str(repo), "feat--plan")

    assert {c.subject for c in family} == {"plan", "code"}
    assert {c.subject for c in exact} == {"plan"}


def test_discover_includes_sdd_paths(tmp_path: Path) -> None:
    repo = tmp_path / "ws"
    _init_repo(repo)
    _commit(
        repo,
        _msg("plan files", "foo"),
        {"sdd/tales/t.md": "# plan\n", "src/x.py": "x = 1\n"},
    )

    commits = _discover_agent_commits(str(repo), "foo")

    assert len(commits) == 1
    assert "sdd/tales/t.md" in commits[0].changed_paths
    assert commits[0].sdd_paths == ("sdd/tales/t.md",)


def test_preview_rejects_dirty_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "ws"
    _init_repo(repo)
    _commit(repo, _msg("foo", "foo"), {"a.txt": "a1\n"})
    (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    preview = preview_agent_revert(str(repo), "foo")

    assert not preview.ok
    assert preview.error is not None
    assert "uncommitted" in preview.error


def test_preview_rejects_non_git_workspace(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()

    preview = preview_agent_revert(str(plain), "foo")

    assert not preview.ok
    assert preview.error is not None
    assert "git" in preview.error.lower()


def test_preview_reports_when_no_tagged_commits(tmp_path: Path) -> None:
    repo = tmp_path / "ws"
    _init_repo(repo)
    _commit(repo, _msg("bar", "bar"), {"a.txt": "a1\n"})

    preview = preview_agent_revert(str(repo), "foo")

    assert not preview.ok
    assert preview.error is not None
    assert "foo" in preview.error


def test_execute_successful_revert(tmp_path: Path) -> None:
    repo = tmp_path / "ws"
    _init_repo(repo)
    _commit(
        repo,
        _msg("add feature", "foo"),
        {"feature.txt": "feature\n", "sdd/tales/t.md": "# plan\n"},
    )
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    preview = preview_agent_revert(str(repo), "foo")
    assert preview.ok
    shas = tuple(c.full_sha for c in preview.commits)

    head_before = _git(repo, "rev-parse", "HEAD").strip()
    result = execute_agent_revert(
        str(repo), shas, agent_name="foo", artifacts_dir=str(artifacts)
    )

    assert result.success, result.message
    assert result.pushed is False  # no origin remote
    # The created files are gone and a single revert commit was added.
    assert not (repo / "feature.txt").exists()
    assert not (repo / "sdd" / "tales" / "t.md").exists()
    assert _git(repo, "status", "--porcelain").strip() == ""
    head_after = _git(repo, "rev-parse", "HEAD").strip()
    assert head_after != head_before
    assert _git(repo, "rev-list", "--count", f"{head_before}..HEAD").strip() == "1"
    # Result artifact recorded.
    saved = json.loads((artifacts / "revert_result.json").read_text())
    assert saved["agent_name"] == "foo"
    assert saved["reverted_shas"] == list(shas)


def test_execute_conflict_aborts_cleanly(tmp_path: Path) -> None:
    repo = tmp_path / "ws"
    _init_repo(repo)
    _commit(repo, _msg("v1", "foo"), {"file.txt": "v1\n"})
    _commit(repo, _msg("v2", "foo"), {"file.txt": "v2\n"})
    # A later non-foo commit diverges the file so reverting foo conflicts.
    _commit(repo, _msg("v3", "bar"), {"file.txt": "v3\n"})

    preview = preview_agent_revert(str(repo), "foo")
    assert preview.ok
    shas = tuple(c.full_sha for c in preview.commits)
    head_before = _git(repo, "rev-parse", "HEAD").strip()

    result = execute_agent_revert(str(repo), shas, agent_name="foo")

    assert not result.success
    assert result.error is not None
    # Repo left clean and unchanged (no partial revert commit).
    assert _git(repo, "status", "--porcelain").strip() == ""
    assert _git(repo, "rev-parse", "HEAD").strip() == head_before
    assert (repo / "file.txt").read_text() == "v3\n"


def test_execute_rejects_dirty_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "ws"
    _init_repo(repo)
    sha = _commit(repo, _msg("foo", "foo"), {"a.txt": "a1\n"})
    (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    result = execute_agent_revert(str(repo), (sha,), agent_name="foo")

    assert not result.success
    assert result.error == "dirty worktree"


def test_execute_rejects_missing_commit(tmp_path: Path) -> None:
    repo = tmp_path / "ws"
    _init_repo(repo)

    result = execute_agent_revert(str(repo), ("0" * 40,), agent_name="foo")

    assert not result.success
    assert result.error == "missing commits"
