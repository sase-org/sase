"""Single-agent execution tests for :mod:`sase.ace.revert_agent`."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sase.ace.revert_agent import RevertRepo, execute_agent_revert, preview_agent_revert
from sase.ace.revert_agent_git import run_git
from tests.ace._revert_agent_helpers import (
    _add_bare_origin,
    _commit,
    _git,
    _init_repo,
    _msg,
    _repo,
)


def test_execute_successful_revert(tmp_path: Path) -> None:
    repo = tmp_path / "ws"
    _init_repo(repo)
    _commit(
        repo,
        _msg("add feature", "foo"),
        {"feature.txt": "feature\n", "sdd/plans/t.md": "# plan\n"},
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
    assert not (repo / "sdd" / "plans" / "t.md").exists()
    assert _git(repo, "status", "--porcelain").strip() == ""
    head_after = _git(repo, "rev-parse", "HEAD").strip()
    assert head_after != head_before
    assert _git(repo, "rev-list", "--count", f"{head_before}..HEAD").strip() == "1"
    # Result artifact recorded.
    saved = json.loads((artifacts / "revert_result.json").read_text())
    assert saved["agent_name"] == "foo"
    assert saved["reverted_shas"] == list(shas)
    assert saved["complete"] is True


def test_revert_git_runner_recovers_stale_index_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "ws"
    _init_repo(repo)
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    lock = repo / ".git" / "index.lock"
    lock.write_text("stale", encoding="utf-8")
    monkeypatch.setenv("SASE_GIT_LOCK_RETRY_DELAYS", "0.001,0.001")

    result = run_git(str(repo), ["add", "feature.txt"])

    assert result.returncode == 0
    assert not lock.exists()
    assert _git(repo, "diff", "--cached", "--name-only").strip() == "feature.txt"


def test_execute_reverts_primary_and_linked_repos(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    linked = tmp_path / "sase-core"
    _init_repo(primary)
    _init_repo(linked)
    _commit(primary, _msg("primary feature", "foo"), {"primary.txt": "p\n"})
    _commit(linked, _msg("linked feature", "foo"), {"linked.txt": "l\n"})
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    preview = preview_agent_revert(
        (_repo(primary, primary=True), _repo(linked, "sase-core")),
        "foo",
    )

    assert preview.ok
    assert preview.commit_count == 2
    assert [repo.repo_label for repo in preview.revertable_repos] == [
        "primary",
        "sase-core",
    ]
    primary_head = _git(primary, "rev-parse", "HEAD").strip()
    linked_head = _git(linked, "rev-parse", "HEAD").strip()

    result = execute_agent_revert(preview, artifacts_dir=str(artifacts))

    assert result.success is True, result.message
    assert result.complete is True
    assert len(result.repo_outcomes) == 2
    assert not (primary / "primary.txt").exists()
    assert not (linked / "linked.txt").exists()
    assert _git(primary, "rev-list", "--count", f"{primary_head}..HEAD").strip() == "1"
    assert _git(linked, "rev-list", "--count", f"{linked_head}..HEAD").strip() == "1"
    saved = json.loads((artifacts / "revert_result.json").read_text())
    assert saved["complete"] is True
    assert saved["reverted_shas"] == list(result.reverted_shas)
    assert [repo["repo_label"] for repo in saved["repos"]] == [
        "primary",
        "sase-core",
    ]


def test_execute_discards_dirty_external_clone_without_moving_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_VCS_PROVIDER", "bare_git")
    external = tmp_path / "external" / "gh" / "pallets" / "click"
    artifacts = tmp_path / "artifacts"
    _init_repo(external)
    artifacts.mkdir()
    (external / "README.md").write_text("dirty\n", encoding="utf-8")
    (external / "scratch.py").write_text("temporary\n", encoding="utf-8")
    head_before = _git(external, "rev-parse", "HEAD").strip()
    preview = preview_agent_revert(
        (
            RevertRepo(
                "gh:pallets/click",
                str(external),
                repo_kind="external",
                source_agent_names=("foo",),
            ),
        ),
        "foo",
    )

    assert preview.ok
    assert preview.commit_count == 0
    assert preview.revertable_repos[0].discard_local_changes is True

    result = execute_agent_revert(preview, artifacts_dir=str(artifacts))

    assert result.success, result.message
    assert result.reverted_shas == ()
    assert result.repo_outcomes[0].discarded_local_changes is True
    assert _git(external, "rev-parse", "HEAD").strip() == head_before
    assert _git(external, "status", "--porcelain").strip() == ""
    assert (external / "README.md").read_text(encoding="utf-8") == "base\n"
    assert not (external / "scratch.py").exists()
    saved = json.loads((artifacts / "revert_result.json").read_text())
    assert saved["reverted_shas"] == []
    assert saved["repos"][0]["repo_kind"] == "external"
    assert saved["repos"][0]["discarded_local_changes"] is True


def test_execute_reverts_linked_only_commits(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    linked = tmp_path / "sase-core"
    _init_repo(primary)
    _init_repo(linked)
    _commit(primary, _msg("other primary", "bar"), {"primary.txt": "p\n"})
    _commit(linked, _msg("linked feature", "foo"), {"linked.txt": "l\n"})

    primary_head = _git(primary, "rev-parse", "HEAD").strip()
    preview = preview_agent_revert(
        (_repo(primary, primary=True), _repo(linked, "sase-core")),
        "foo",
    )

    assert preview.ok
    assert preview.commit_count == 1
    assert [repo.repo_label for repo in preview.revertable_repos] == ["sase-core"]

    result = execute_agent_revert(preview)

    assert result.success is True, result.message
    assert _git(primary, "rev-parse", "HEAD").strip() == primary_head
    assert not (linked / "linked.txt").exists()


def test_dirty_linked_repo_is_blocked_but_primary_reverts(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    linked = tmp_path / "sase-core"
    _init_repo(primary)
    _init_repo(linked)
    _commit(primary, _msg("primary feature", "foo"), {"primary.txt": "p\n"})
    _commit(linked, _msg("linked feature", "foo"), {"linked.txt": "l\n"})
    (linked / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    preview = preview_agent_revert(
        (_repo(primary, primary=True), _repo(linked, "sase-core")),
        "foo",
    )

    assert preview.ok
    assert preview.commit_count == 1
    assert len(preview.blocked_repos) == 1
    blocked = preview.blocked_repos[0]
    assert blocked.repo_label == "sase-core"
    assert blocked.commit_count == 1
    assert blocked.blocked_reason is not None
    assert "uncommitted" in blocked.blocked_reason

    result = execute_agent_revert(preview, artifacts_dir=str(artifacts))

    assert result.success is False
    assert result.complete is False
    assert len(result.reverted_shas) == 1
    assert not (primary / "primary.txt").exists()
    assert (linked / "linked.txt").exists()
    assert (linked / "dirty.txt").exists()
    saved = json.loads((artifacts / "revert_result.json").read_text())
    assert saved["complete"] is False
    linked_outcome = next(
        repo for repo in saved["repos"] if repo["repo_label"] == "sase-core"
    )
    assert linked_outcome["skipped_reason"]


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
    assert result.error is not None
    assert "uncommitted" in result.error


def test_execute_rejects_missing_commit(tmp_path: Path) -> None:
    repo = tmp_path / "ws"
    _init_repo(repo)

    result = execute_agent_revert(str(repo), ("0" * 40,), agent_name="foo")

    assert not result.success
    assert result.error is not None
    assert "no longer exist" in result.error


def test_execute_pushes_to_bare_origin(tmp_path: Path) -> None:
    repo = tmp_path / "ws"
    _init_repo(repo)
    remote = tmp_path / "remote.git"
    _add_bare_origin(repo, remote)
    _commit(repo, _msg("add feature", "foo"), {"feature.txt": "feature\n"})

    preview = preview_agent_revert(str(repo), "foo")
    assert preview.ok
    shas = tuple(c.full_sha for c in preview.commits)

    result = execute_agent_revert(str(repo), shas, agent_name="foo")

    assert result.success is True, result.message
    assert result.pushed is True
    # The remote branch now points at the local revert commit.
    local_head = _git(repo, "rev-parse", "HEAD").strip()
    remote_head = _git(remote, "rev-parse", "main").strip()
    assert remote_head == local_head


def test_execute_no_origin_records_skip_reason(tmp_path: Path) -> None:
    repo = tmp_path / "ws"
    _init_repo(repo)
    _commit(repo, _msg("add feature", "foo"), {"feature.txt": "feature\n"})
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    preview = preview_agent_revert(str(repo), "foo")
    shas = tuple(c.full_sha for c in preview.commits)

    result = execute_agent_revert(
        str(repo), shas, agent_name="foo", artifacts_dir=str(artifacts)
    )

    assert result.success is True
    assert result.pushed is False
    saved = json.loads((artifacts / "revert_result.json").read_text())
    assert saved["pushed"] is False
    assert saved["push_skipped_reason"] == "no origin remote"
    assert "push_error" not in saved


def test_execute_push_failure_after_local_revert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.ace.revert_agent as ra

    repo = tmp_path / "ws"
    _init_repo(repo)
    remote = tmp_path / "remote.git"
    _add_bare_origin(repo, remote)
    _commit(repo, _msg("add feature", "foo"), {"feature.txt": "feature\n"})
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    preview = preview_agent_revert(str(repo), "foo")
    assert preview.ok
    shas = tuple(c.full_sha for c in preview.commits)
    head_before = _git(repo, "rev-parse", "HEAD").strip()

    real_run_git = ra._run_git

    def fake_run_git(
        workspace_dir: str, args: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        # Fail only the push; the local revert commit is created for real.
        if args and args[0] == "push":
            return subprocess.CompletedProcess(
                args, returncode=1, stdout="", stderr="remote rejected"
            )
        return real_run_git(workspace_dir, args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(ra, "_run_git", fake_run_git)

    result = execute_agent_revert(
        str(repo), shas, agent_name="foo", artifacts_dir=str(artifacts)
    )

    # The push failed, so the operation is not a success...
    assert result.success is False
    assert result.pushed is False
    assert result.error is not None and "push" in result.error.lower()
    # ...but the local revert commit was preserved (not rolled back).
    assert result.reverted_shas == shas
    assert _git(repo, "status", "--porcelain").strip() == ""
    head_after = _git(repo, "rev-parse", "HEAD").strip()
    assert head_after != head_before
    assert _git(repo, "rev-list", "--count", f"{head_before}..HEAD").strip() == "1"
    # The message points at the recovery path.
    assert "locally" in result.message.lower()
    assert "push" in result.message.lower()
    # The artifact records the local revert plus the push failure detail.
    saved = json.loads((artifacts / "revert_result.json").read_text())
    assert saved["reverted_shas"] == list(shas)
    assert saved["pushed"] is False
    assert "remote rejected" in saved["push_error"]
