"""Regression coverage for bounding a stalled post-push agent-hood drain."""

from __future__ import annotations

from pathlib import Path
import time

import pytest

from sase.agents_sync import commit_publication, git_sync
from sase.agents_sync.commit_publication import publish_committed_agent_hood
from sase.agents_sync.git import run_git
from sase.agents_sync.models import TargetSelection
from sase.agents_sync.publication_outbox import list_agent_publications
from sase.agents_sync.v2_io import owner_manifest_path, v2_json_bytes
from sase.agents_sync.v2_models import (
    V2OwnerHoodEntry,
    V2OwnerManifest,
    V2ProjectIdentity,
    V2PublicationCounts,
)
from sase.core.agent_identity_facade import AgentOwnerIdentity
from tests.agents_sync.commit_publication_fixtures import setup_target


def _publish_readme(owner: AgentOwnerIdentity):
    def publish(_target, repo, _agent, **_kwargs):
        (repo / "README.md").write_text("# Published hood\n")
        (repo / "schema.json").write_text("{}\n")
        (repo / "families").mkdir(exist_ok=True)
        (repo / "families" / ".gitkeep").write_text("")
        manifest = V2OwnerManifest(
            owner,
            V2ProjectIdentity("proj", "Project"),
            (("foo", V2OwnerHoodEntry("d" * 64, ("README.md",), 1, 1)),),
        )
        path = repo / owner_manifest_path(owner)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(v2_json_bytes(manifest.to_json_dict()))
        return V2PublicationCounts(hoods_published=1)

    return publish


def _configure_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    owner: AgentOwnerIdentity,
):
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, remote = setup_target(tmp_path)
    monkeypatch.setattr(
        commit_publication,
        "resolve_sync_targets",
        lambda _projects: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(
        commit_publication,
        "require_agent_owner_identity",
        lambda: owner,
    )
    return target, remote


def test_blocked_render_is_bounded_and_leaves_the_request_queued(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    target, _remote = _configure_target(monkeypatch, tmp_path, owner)

    def blocked_render(*_args, **_kwargs):
        time.sleep(30)  # sase-test-wait: exceeds the drain timeout
        raise AssertionError("blocked render should have been interrupted")

    monkeypatch.setattr(commit_publication, "publish_agent_hood", blocked_render)
    monkeypatch.setattr(
        commit_publication,
        "_configured_publication_drain_timeout",
        lambda: 0.2,
    )

    started = time.perf_counter()
    outcome = publish_committed_agent_hood(
        "foo--code",
        "a" * 40,
        project="Project",
        git_runner=run_git,
    )
    elapsed = time.perf_counter() - started

    assert elapsed < 5.0
    assert outcome.queued
    assert not outcome.published
    assert outcome.error is not None and "did not complete within" in outcome.error

    queued = list_agent_publications("proj")
    assert len(queued) == 1
    assert queued[0].attempts == 1

    lock_path = (
        git_sync.agents_git_dir(target.sidecar_path, run_git) / "sase-agents-sync.lock"
    )
    with git_sync.bounded_agents_lock(lock_path, 1.0) as acquired:
        assert acquired, "stalled drain must release sase-agents-sync.lock"


def test_after_a_blocked_render_a_later_drain_retries_and_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    _configure_target(monkeypatch, tmp_path, owner)

    def blocked_render(*_args, **_kwargs):
        time.sleep(30)  # sase-test-wait: exceeds the drain timeout

    monkeypatch.setattr(commit_publication, "publish_agent_hood", blocked_render)
    monkeypatch.setattr(
        commit_publication,
        "_configured_publication_drain_timeout",
        lambda: 0.2,
    )

    first = publish_committed_agent_hood(
        "foo--code",
        "a" * 40,
        project="Project",
        git_runner=run_git,
    )
    assert first.queued and not first.published
    assert len(list_agent_publications("proj")) == 1

    monkeypatch.setattr(
        commit_publication, "publish_agent_hood", _publish_readme(owner)
    )
    monkeypatch.setattr(
        commit_publication,
        "_configured_publication_drain_timeout",
        lambda: 5.0,
    )

    second = publish_committed_agent_hood(
        "foo--code",
        "a" * 40,
        project="Project",
        git_runner=run_git,
    )
    assert second.published and not second.error
    assert list_agent_publications("proj") == ()
