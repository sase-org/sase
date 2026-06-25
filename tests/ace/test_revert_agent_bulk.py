"""Bulk revert tests for :mod:`sase.ace.revert_agent`."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sase.ace.revert_agent import execute_agents_revert, preview_agents_revert
from tests.ace._revert_agent_helpers import (
    _add_bare_origin,
    _commit,
    _git,
    _init_repo,
    _msg,
    _repo,
    _target,
)


def test_bulk_preview_combined_newest_first(tmp_path: Path) -> None:
    repo = tmp_path / "ws"
    _init_repo(repo)
    _commit(repo, _msg("foo one", "foo"), {"a.txt": "a1\n"})
    _commit(repo, _msg("bar one", "bar"), {"b.txt": "b1\n"})
    _commit(repo, _msg("foo two", "foo"), {"a.txt": "a2\n"})
    _commit(repo, _msg("bar two", "bar"), {"b.txt": "b2\n"})

    preview = preview_agents_revert([_target(repo, "foo"), _target(repo, "bar")])

    assert preview.ok
    # Newest-first across the *combined* set, not per-agent concatenation.
    assert [c.subject for c in preview.commits] == [
        "bar two",
        "foo two",
        "bar one",
        "foo one",
    ]
    assert set(preview.matched_target_names) == {"foo", "bar"}
    assert preview.skipped_target_names == ()
    assert preview.target_count == 2


def test_bulk_preview_dedups_overlapping_family_matches(tmp_path: Path) -> None:
    repo = tmp_path / "ws"
    _init_repo(repo)
    _commit(repo, _msg("plan", "feat--plan"), {"p.txt": "p\n"})
    _commit(repo, _msg("code", "feat--code"), {"c.txt": "c\n"})

    # Both targets share family base "feat" so each matches both commits;
    # the combined set must still list each commit exactly once.
    targets = [
        _target(repo, "feat--plan", family_base="feat"),
        _target(repo, "feat--code", family_base="feat"),
    ]
    preview = preview_agents_revert(targets)

    assert preview.ok
    shas = [c.full_sha for c in preview.commits]
    assert len(shas) == len(set(shas)) == 2
    assert {c.subject for c in preview.commits} == {"plan", "code"}
    assert set(preview.matched_target_names) == {"feat--plan", "feat--code"}


def test_bulk_preview_reports_skipped_targets(tmp_path: Path) -> None:
    repo = tmp_path / "ws"
    _init_repo(repo)
    _commit(repo, _msg("foo one", "foo"), {"a.txt": "a1\n"})

    # "bar" has no tagged commits, so matched={foo}, skipped={bar}.
    preview = preview_agents_revert([_target(repo, "foo"), _target(repo, "bar")])

    assert preview.ok
    assert preview.matched_target_names == ("foo",)
    assert preview.skipped_target_names == ("bar",)


def test_bulk_preview_rejects_dirty_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "ws"
    _init_repo(repo)
    _commit(repo, _msg("foo", "foo"), {"a.txt": "a1\n"})
    (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    preview = preview_agents_revert([_target(repo, "foo")])

    assert not preview.ok
    assert preview.error is not None
    assert "uncommitted" in preview.error


def test_bulk_preview_rejects_non_git_workspace(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()

    preview = preview_agents_revert([_target(plain, "foo")])

    assert not preview.ok
    assert preview.error is not None
    assert "git" in preview.error.lower()


def test_bulk_preview_reports_when_no_tagged_commits(tmp_path: Path) -> None:
    repo = tmp_path / "ws"
    _init_repo(repo)
    _commit(repo, _msg("bar", "bar"), {"a.txt": "a1\n"})

    preview = preview_agents_revert([_target(repo, "foo")])

    assert not preview.ok
    assert preview.error is not None


def test_bulk_preview_rejects_mixed_workspaces(tmp_path: Path) -> None:
    repo1 = tmp_path / "ws1"
    repo2 = tmp_path / "ws2"
    _init_repo(repo1)
    _init_repo(repo2)
    _commit(repo1, _msg("foo", "foo"), {"a.txt": "a\n"})
    _commit(repo2, _msg("bar", "bar"), {"b.txt": "b\n"})

    preview = preview_agents_revert([_target(repo1, "foo"), _target(repo2, "bar")])

    assert not preview.ok
    assert preview.error is not None
    assert "multiple workspaces" in preview.error


def test_bulk_execute_single_commit_for_all(tmp_path: Path) -> None:
    repo = tmp_path / "ws"
    _init_repo(repo)
    _commit(repo, _msg("foo feature", "foo"), {"foo.txt": "foo\n"})
    _commit(repo, _msg("bar feature", "bar"), {"bar.txt": "bar\n"})
    art_foo = tmp_path / "art_foo"
    art_foo.mkdir()
    art_bar = tmp_path / "art_bar"
    art_bar.mkdir()

    preview = preview_agents_revert(
        [
            _target(repo, "foo", artifacts=str(art_foo)),
            _target(repo, "bar", artifacts=str(art_bar)),
        ]
    )
    assert preview.ok
    head_before = _git(repo, "rev-parse", "HEAD").strip()

    result = execute_agents_revert(preview)

    assert result.success, result.message
    assert result.pushed is False  # no origin remote
    assert not (repo / "foo.txt").exists()
    assert not (repo / "bar.txt").exists()
    assert _git(repo, "status", "--porcelain").strip() == ""
    # Exactly one revert commit for the whole marked set.
    assert _git(repo, "rev-list", "--count", f"{head_before}..HEAD").strip() == "1"
    assert set(result.agent_names) == {"foo", "bar"}
    assert len(result.reverted_shas) == 2
    # Per-agent artifacts written only after the revert commit succeeds.
    assert json.loads((art_foo / "revert_result.json").read_text())["agent_name"] == (
        "foo"
    )
    assert json.loads((art_bar / "revert_result.json").read_text())["agent_name"] == (
        "bar"
    )


def test_bulk_reverts_union_of_linked_repos(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    linked = tmp_path / "sase-core"
    _init_repo(primary)
    _init_repo(linked)
    _commit(primary, _msg("foo primary", "foo"), {"foo.txt": "foo\n"})
    _commit(linked, _msg("bar linked", "bar"), {"bar.txt": "bar\n"})
    art_foo = tmp_path / "art_foo"
    art_bar = tmp_path / "art_bar"
    art_foo.mkdir()
    art_bar.mkdir()

    preview = preview_agents_revert(
        [
            _target(primary, "foo", artifacts=str(art_foo)),
            _target(primary, "bar", artifacts=str(art_bar)),
        ],
        (_repo(primary, primary=True), _repo(linked, "sase-core")),
    )

    assert preview.ok
    assert preview.commit_count == 2
    assert [repo.repo_label for repo in preview.revertable_repos] == [
        "primary",
        "sase-core",
    ]
    assert set(preview.matched_target_names) == {"foo", "bar"}

    primary_head = _git(primary, "rev-parse", "HEAD").strip()
    linked_head = _git(linked, "rev-parse", "HEAD").strip()
    result = execute_agents_revert(preview)

    assert result.success is True, result.message
    assert result.complete is True
    assert set(result.agent_names) == {"foo", "bar"}
    assert not (primary / "foo.txt").exists()
    assert not (linked / "bar.txt").exists()
    assert _git(primary, "rev-list", "--count", f"{primary_head}..HEAD").strip() == "1"
    assert _git(linked, "rev-list", "--count", f"{linked_head}..HEAD").strip() == "1"
    assert json.loads((art_foo / "revert_result.json").read_text())["complete"] is True
    assert json.loads((art_bar / "revert_result.json").read_text())["complete"] is True


def test_bulk_execute_conflict_rolls_back_to_original_head(tmp_path: Path) -> None:
    repo = tmp_path / "ws"
    _init_repo(repo)
    _commit(repo, _msg("v1", "foo"), {"file.txt": "v1\n"})
    _commit(repo, _msg("v2", "foo"), {"file.txt": "v2\n"})
    # A later non-foo commit diverges the file so reverting foo conflicts.
    _commit(repo, _msg("v3", "bar"), {"file.txt": "v3\n"})

    preview = preview_agents_revert([_target(repo, "foo")])
    assert preview.ok
    head_before = _git(repo, "rev-parse", "HEAD").strip()

    result = execute_agents_revert(preview)

    assert not result.success
    assert result.error is not None
    # No partial revert commit or partial revert changes survive.
    assert _git(repo, "status", "--porcelain").strip() == ""
    assert _git(repo, "rev-parse", "HEAD").strip() == head_before
    assert (repo / "file.txt").read_text() == "v3\n"


def test_bulk_execute_commit_failure_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.ace.revert_agent as ra

    repo = tmp_path / "ws"
    _init_repo(repo)
    _commit(repo, _msg("foo feature", "foo"), {"foo.txt": "foo\n"})

    preview = preview_agents_revert([_target(repo, "foo")])
    assert preview.ok
    head_before = _git(repo, "rev-parse", "HEAD").strip()

    real_run_git = ra._run_git

    def fake_run_git(
        workspace_dir: str, args: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        # Inject a failure on the revert commit step; everything else (incl.
        # the rollback's revert --abort / reset --hard) runs for real.
        if args and args[0] == "commit":
            return subprocess.CompletedProcess(
                args, returncode=1, stdout="", stderr="boom"
            )
        return real_run_git(workspace_dir, args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(ra, "_run_git", fake_run_git)

    result = execute_agents_revert(preview)

    assert not result.success
    assert "rolled back" in result.message.lower()
    # The revert --no-commit changes were undone despite the failed commit.
    assert _git(repo, "status", "--porcelain").strip() == ""
    assert _git(repo, "rev-parse", "HEAD").strip() == head_before
    assert (repo / "foo.txt").read_text() == "foo\n"


def test_bulk_execute_pushes_to_bare_origin(tmp_path: Path) -> None:
    repo = tmp_path / "ws"
    _init_repo(repo)
    remote = tmp_path / "remote.git"
    _add_bare_origin(repo, remote)
    _commit(repo, _msg("foo feature", "foo"), {"foo.txt": "foo\n"})
    _commit(repo, _msg("bar feature", "bar"), {"bar.txt": "bar\n"})

    preview = preview_agents_revert([_target(repo, "foo"), _target(repo, "bar")])
    assert preview.ok
    head_before = _git(repo, "rev-parse", "HEAD").strip()

    result = execute_agents_revert(preview)

    assert result.success is True, result.message
    assert result.pushed is True
    # Exactly one local revert commit, and the remote branch tracks it.
    assert _git(repo, "rev-list", "--count", f"{head_before}..HEAD").strip() == "1"
    local_head = _git(repo, "rev-parse", "HEAD").strip()
    remote_head = _git(remote, "rev-parse", "main").strip()
    assert remote_head == local_head
