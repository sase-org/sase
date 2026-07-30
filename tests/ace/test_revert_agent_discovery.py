"""Discovery and preview tests for :mod:`sase.ace.revert_agent`."""

from __future__ import annotations

from pathlib import Path

from sase.ace.revert_agent import _discover_agent_commits, preview_agent_revert
from sase.ace.revert_agent_discovery import discover_bulk_commits
from tests.ace._revert_agent_helpers import (
    _commit,
    _init_repo,
    _msg,
    _msg_prefixed,
    _target,
)


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


def test_discover_matches_legacy_and_prefixed_tags(tmp_path: Path) -> None:
    """Discovery finds both legacy ``AGENT=`` and new ``SASE_AGENT=`` commits."""
    repo = tmp_path / "ws"
    _init_repo(repo)
    _commit(repo, _msg("legacy", "foo"), {"a.txt": "a1\n"})
    _commit(repo, _msg_prefixed("prefixed", "foo"), {"b.txt": "b1\n"})

    commits = _discover_agent_commits(str(repo), "foo")

    subjects = [c.subject for c in commits]
    assert subjects == ["prefixed", "legacy"]
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


def test_discover_lane_tagged_commits_match_family_members(tmp_path: Path) -> None:
    """A lane tag reverts through the family base without naming a member."""
    repo = tmp_path / "ws"
    _init_repo(repo)
    _commit(repo, _msg("lane", "feat"), {"l.txt": "l\n"})
    _commit(repo, _msg("legacy member", "feat--plan"), {"p.txt": "p\n"})
    _commit(repo, _msg("other lane", "other"), {"o.txt": "o\n"})

    family = _discover_agent_commits(str(repo), "feat--code", family_base="feat")

    # Both the lane spelling and the legacy member spelling belong to the lane.
    assert {c.subject for c in family} == {"lane", "legacy member"}


def test_discover_bulk_dedupes_lane_commits_across_family_and_member(
    tmp_path: Path,
) -> None:
    """Selecting a family container and one member reverts each commit once."""
    repo = tmp_path / "ws"
    _init_repo(repo)
    _commit(repo, _msg("lane", "feat"), {"l.txt": "l\n"})
    _commit(repo, _msg("legacy member", "feat--code"), {"c.txt": "c\n"})

    commits, matched = discover_bulk_commits(
        str(repo),
        (
            _target(repo, "feat", family_base="feat"),
            _target(repo, "feat--code", family_base="feat"),
        ),
    )

    assert [c.subject for c in commits] == ["legacy member", "lane"]
    assert len({c.full_sha for c in commits}) == 2
    assert matched == {"feat", "feat--code"}


def test_discover_includes_sdd_paths(tmp_path: Path) -> None:
    repo = tmp_path / "ws"
    _init_repo(repo)
    _commit(
        repo,
        _msg("plan files", "foo"),
        {"sdd/plans/t.md": "# plan\n", "src/x.py": "x = 1\n"},
    )

    commits = _discover_agent_commits(str(repo), "foo")

    assert len(commits) == 1
    assert "sdd/plans/t.md" in commits[0].changed_paths
    assert commits[0].sdd_paths == ("sdd/plans/t.md",)


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
