"""Enqueue a retryable request when git fails, including linked-repo scope."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.agents_sync import _commit_publication_support as publication_support
from sase.agents_sync.commit_publication import publish_committed_agent_hood
from sase.agents_sync.models import TargetSelection
from sase.agents_sync.publication_outbox import (
    PUBLICATION_SCOPE_LINKED,
    PUBLICATION_SCOPE_REVISION,
    list_agent_publications,
)
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.repo_inventory import RepoInventory, RepoRecord
from tests.agents_sync.commit_publication_fixtures import setup_target


def _fail_git(
    cwd: Path,
    args: list[str],
    *,
    network: bool = False,
    op: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args, 1, "", "git is unavailable")


def test_committed_publication_records_a_retryable_request_when_git_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, _remote = setup_target(tmp_path)
    owner = AgentOwnerIdentity("alice", "athena")
    monkeypatch.setattr(
        publication_support,
        "resolve_sync_targets",
        lambda _projects: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(
        publication_support,
        "require_agent_owner_identity",
        lambda: owner,
    )

    outcome = publish_committed_agent_hood(
        "worker--code",
        "a" * 40,
        project="Project",
        commit_cwd=target.primary_checkout,
        artifacts_dir=tmp_path / "runs" / "run-1",
        run_id="run-1",
        git_runner=_fail_git,
    )

    # The synchronous publisher enqueues before it touches git, so a failed
    # sidecar attempt still leaves a durable request for `sase agent sync`.
    # Repository failures preserve attempts and the previous error.
    assert outcome.queued
    assert not outcome.published
    [request] = list_agent_publications("proj")
    assert request.global_agent == "alice.athena.worker"
    assert request.primary_revision == "a" * 40
    assert request.scope == PUBLICATION_SCOPE_REVISION
    assert request.commit_cwd == str(target.primary_checkout.resolve())
    assert request.artifacts_dir == str((tmp_path / "runs" / "run-1").resolve())
    assert request.run_id == "run-1"
    assert request.attempts == 0
    assert request.last_error is None


def test_linked_repo_commit_enqueues_linked_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, _remote = setup_target(tmp_path)
    owner = AgentOwnerIdentity("alice", "athena")
    linked = tmp_path / "sase-core"
    linked.mkdir()
    monkeypatch.setattr(
        publication_support,
        "resolve_sync_targets",
        lambda _projects: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(
        publication_support,
        "require_agent_owner_identity",
        lambda: owner,
    )
    monkeypatch.setattr(
        "sase.agents_sync._commit_publication_queue.collect_repo_inventory",
        lambda: RepoInventory(
            records=(
                RepoRecord(
                    name="sase-core",
                    kind="linked",
                    project="Project",
                    project_key="proj",
                    path=str(linked),
                    exists=True,
                    auto_clone=False,
                    description=None,
                    source="test",
                    env_name=None,
                ),
            )
        ),
    )

    outcome = publish_committed_agent_hood(
        "worker--code",
        "a" * 40,
        project="Project",
        commit_cwd=linked,
        git_runner=_fail_git,
    )

    assert outcome.queued
    [request] = list_agent_publications("proj")
    assert request.scope == PUBLICATION_SCOPE_LINKED
    assert request.primary_revision == "a" * 40
