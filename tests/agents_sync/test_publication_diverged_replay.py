"""Automatic index conflict recovery and parking for publication rebases."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agents_sync import git_sync, publication_job
from sase.agents_sync.git import run_git
from sase.agents_sync.publication_diverged_replay import (
    PUBLICATION_REBASE_FAILURE_STAGE,
    active_diverged_replay_marker,
    pull_agents_rebase_with_recovery,
    read_diverged_replay_marker,
)
from tests.agents_sync._publication_job_helpers import publication_item
from tests.agents_sync.git_sync_fixtures import (
    git,
    patch_payload_pass,
    setup_repo,
    target,
)


def _diverge_readme(tmp_path: Path, remote: Path, sidecar: Path) -> None:
    """Create local and upstream edits to the same regenerable index page."""

    (sidecar / "README.md").write_text("# Stale local index\n", encoding="utf-8")
    git(sidecar, "add", "README.md")
    git(sidecar, "commit", "-m", "stale local index")
    upstream = tmp_path / "upstream-index"
    git(tmp_path, "clone", str(remote), str(upstream))
    git(upstream, "config", "user.name", "Upstream")
    git(upstream, "config", "user.email", "upstream@example.test")
    (upstream / "README.md").write_text("# Current upstream index\n", encoding="utf-8")
    git(upstream, "add", "README.md")
    git(upstream, "commit", "-m", "current upstream index")
    git(upstream, "push")


def _diverge_owner_file(tmp_path: Path, remote: Path, sidecar: Path) -> str:
    """Create an unsafe owner-content conflict and return the local HEAD."""

    (sidecar / "conflict.txt").write_text("local owner data\n", encoding="utf-8")
    git(sidecar, "add", "conflict.txt")
    git(sidecar, "commit", "-m", "local owner data")
    local_head = git(sidecar, "rev-parse", "HEAD").stdout.strip()
    upstream = tmp_path / "upstream-owner"
    git(tmp_path, "clone", str(remote), str(upstream))
    git(upstream, "config", "user.name", "Upstream")
    git(upstream, "config", "user.email", "upstream@example.test")
    (upstream / "conflict.txt").write_text("upstream owner data\n", encoding="utf-8")
    git(upstream, "add", "conflict.txt")
    git(upstream, "commit", "-m", "upstream owner data")
    git(upstream, "push")
    return local_head


def test_regenerable_index_conflict_is_rebased_and_published(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    remote, _seed, sidecar = setup_repo(tmp_path)
    sync_target = target(tmp_path, remote, sidecar)
    _diverge_readme(tmp_path, remote, sidecar)
    patch_payload_pass(monkeypatch)

    outcome = git_sync._sync_project(sync_target, "athena", git_runner=run_git)

    assert outcome.error is None
    assert outcome.pushed
    assert git(sidecar, "rev-list", "--count", "@{upstream}..HEAD").stdout == "0\n"
    assert git(
        sidecar, "for-each-ref", "--format=%(refname)", "refs/sase/recovery"
    ).stdout.strip()
    verify = tmp_path / "verify-index"
    git(tmp_path, "clone", str(remote), str(verify))
    assert (verify / "README.md").read_text(encoding="utf-8") == "# Hoods\n"


def test_owner_content_conflict_is_parked_not_retried_and_notifies_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    remote, _seed, sidecar = setup_repo(tmp_path)
    sync_target = target(tmp_path, remote, sidecar)
    local_head = _diverge_owner_file(tmp_path, remote, sidecar)
    notifications: list[tuple[object, dict[str, object]]] = []
    monkeypatch.setattr(
        "sase.notifications.store.upsert_notification",
        lambda notification, **kwargs: notifications.append((notification, kwargs)),
    )

    result = pull_agents_rebase_with_recovery(
        sidecar,
        run_git,
        "test.publication.pull",
        project_key=sync_target.project_key,
    )

    marker = read_diverged_replay_marker(sync_target.project_key)
    assert result.process.returncode != 0
    assert result.failure_stage == PUBLICATION_REBASE_FAILURE_STAGE
    assert marker is not None
    assert marker.head == local_head
    assert marker.paths == ("conflict.txt",)
    assert git(sidecar, "rev-parse", "HEAD").stdout.strip() == local_head
    assert not (sidecar / ".git" / "rebase-merge").exists()
    assert len(notifications) == 1
    notification, kwargs = notifications[0]
    assert notification.dedup_key == (f"agent_publication_diverged:proj:{local_head}")
    assert kwargs["plus_one_note"] == "Still blocked on conflict.txt"

    bells: list[str] = []
    monkeypatch.setattr(
        publication_job,
        "list_project_records",
        lambda *_args, **_kwargs: [
            SimpleNamespace(
                project_name="proj", workspace_dir=str(tmp_path), is_project=True
            )
        ],
    )
    monkeypatch.setattr(
        publication_job,
        "resolve_sync_targets",
        lambda _keys, **_kwargs: SimpleNamespace(targets=(sync_target,), outcomes=()),
    )
    monkeypatch.setattr(
        publication_job,
        "active_agent_publications",
        lambda _key: (publication_item("alice.athena.worker", "a" * 40, created_at=1),),
    )
    monkeypatch.setattr(
        publication_job, "list_referenced_by_requests", lambda *_a, **_k: ()
    )
    monkeypatch.setattr(
        publication_job,
        "ring_publication_doorbell",
        lambda key, hint=None: bells.append(key),
    )
    monkeypatch.setattr(
        "sase.agents_sync._commit_publication_queue.drain_selected_agent_publications",
        lambda *_a, **_k: pytest.fail("parked project must not retry its pull"),
    )
    summary = publication_job.run_publication_job(work_budget_seconds=10)
    assert summary.errors == 0
    assert summary.deferred_projects == 1
    assert summary.project_stats["proj"]["last_outcome"] == "diverged_replay_parked"
    assert bells == []

    (sidecar / "new-owner-data.txt").write_text("new work\n", encoding="utf-8")
    git(sidecar, "add", "new-owner-data.txt")
    git(sidecar, "commit", "-m", "new local owner data")
    assert (
        active_diverged_replay_marker(
            sync_target.project_key,
            sidecar,
            run_git,
        )
        is None
    )
    assert read_diverged_replay_marker(sync_target.project_key) is None
