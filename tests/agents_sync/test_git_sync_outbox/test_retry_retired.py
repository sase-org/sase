"""Retry-retired outbox tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.agents_sync import git_sync
from sase.agents_sync.inventory import ProjectHoodInventory
from sase.agents_sync.models import (
    ProjectTarget,
    SyncOutcome,
    TargetSelection,
)
from sase.agents_sync.publication_outbox import (
    AgentPublicationOutboxItem,
    enqueue_agent_publication,
    list_agent_publications,
)
from sase.agents_sync.v2_models import V2PublicationCounts
from sase.core.agent_identity_facade import AgentOwnerIdentity

from tests.agents_sync.commit_publication_fixtures import git, setup_target
from tests.agents_sync.git_sync_fixtures import plant_fulfilled_publication, target
from tests.agents_sync.test_git_sync_outbox._helpers import retire_publication


def _stub_mocked_sync(
    monkeypatch: pytest.MonkeyPatch,
    sync_target: ProjectTarget,
    *,
    outcome: SyncOutcome | None = None,
    extra_targets: tuple[ProjectTarget, ...] = (),
) -> None:
    targets = (sync_target, *extra_targets)
    monkeypatch.setattr(
        git_sync,
        "resolve_sync_targets",
        lambda _projects: TargetSelection(targets, ()),
    )
    monkeypatch.setattr(
        git_sync,
        "require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )
    monkeypatch.setattr(
        git_sync,
        "_sync_project",
        lambda *_args, **_kwargs: (
            outcome
            or SyncOutcome(sync_target.project_key, sync_target.project, pulled=True)
        ),
    )
    monkeypatch.setattr(
        "sase.agents_sync.status.rewrite_agents_sync_status_after_sync",
        lambda _projects: None,
    )


def test_retry_retired_revives_and_acknowledges_a_legacy_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    sync_target = target(tmp_path, tmp_path / "remote.git", tmp_path / "sidecar")
    item = enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key=sync_target.project_key,
            project=sync_target.project,
            local_agent="foo",
            global_agent="alice.athena.foo",
            primary_revision="a" * 40,
            local_hood="foo",
        )
    )
    retire_publication(item)
    plant_fulfilled_publication(sync_target.sidecar_path)
    _stub_mocked_sync(monkeypatch, sync_target)

    [outcome] = git_sync.sync_agents(("proj",), retry_retired=True)

    assert outcome.error is None
    assert "retried 1 retired publication request" in outcome.diagnostics
    assert "legacy mismatch" in outcome.diagnostics[1]
    assert list_agent_publications("proj") == ()

    [repeat] = git_sync.sync_agents(("proj",), retry_retired=True)
    assert all("retried" not in line for line in repeat.diagnostics)
    assert list_agent_publications("proj") == ()


def test_retry_retired_does_not_ack_a_page_without_the_requested_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    sync_target = target(tmp_path, tmp_path / "remote.git", tmp_path / "sidecar")
    item = enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key=sync_target.project_key,
            project=sync_target.project,
            local_agent="foo",
            global_agent="alice.athena.foo",
            primary_revision="a" * 40,
            local_hood="foo",
        )
    )
    retire_publication(item)
    plant_fulfilled_publication(sync_target.sidecar_path, revision="b" * 40)
    _stub_mocked_sync(monkeypatch, sync_target)

    git_sync.sync_agents(("proj",), retry_retired=True)

    [remaining] = list_agent_publications("proj")
    assert remaining.logical_key == item.logical_key
    assert remaining.attempts == 1
    assert not remaining.terminal
    assert "did not materialize" in str(remaining.last_error)


def test_retry_retired_acknowledges_a_session_page_not_an_unrelated_readme(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    sync_target = target(tmp_path, tmp_path / "remote.git", tmp_path / "sidecar")
    item = enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key=sync_target.project_key,
            project=sync_target.project,
            local_agent="foo.bar",
            global_agent="alice.athena.foo.bar",
            primary_revision="a" * 40,
            local_hood="foo",
        )
    )
    retire_publication(item)
    decoy = sync_target.sidecar_path / "agents" / "alice.athena.foo.bar" / "README.md"
    decoy.parent.mkdir(parents=True)
    decoy.write_text("# unrelated preexisting run page\n")
    plant_fulfilled_publication(
        sync_target.sidecar_path,
        local_agent="foo.bar",
        global_agent="alice.athena.foo.bar",
        kind="session",
    )
    _stub_mocked_sync(monkeypatch, sync_target)

    git_sync.sync_agents(("proj",), retry_retired=True)

    assert list_agent_publications("proj") == ()


def test_retry_retired_handles_multiple_primary_revisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    sync_target = target(tmp_path, tmp_path / "remote.git", tmp_path / "sidecar")
    first = enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key=sync_target.project_key,
            project=sync_target.project,
            local_agent="foo",
            global_agent="alice.athena.foo",
            primary_revision="a" * 40,
            local_hood="foo",
        )
    )
    second = enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key=sync_target.project_key,
            project=sync_target.project,
            local_agent="foo",
            global_agent="alice.athena.foo",
            primary_revision="b" * 40,
            local_hood="foo",
        )
    )
    retire_publication(first)
    retire_publication(second, "second revision mismatch")
    plant_fulfilled_publication(
        sync_target.sidecar_path,
        extra_revisions=("b" * 40,),
    )
    _stub_mocked_sync(monkeypatch, sync_target)

    [outcome] = git_sync.sync_agents(("proj",), retry_retired=True)

    assert "retried 2 retired publication request" in outcome.diagnostics[0]
    assert list_agent_publications("proj") == ()


def test_retry_retired_leaves_failed_push_retryable_and_isolates_projects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    sync_target = target(tmp_path, tmp_path / "remote.git", tmp_path / "sidecar")
    item = enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key=sync_target.project_key,
            project=sync_target.project,
            local_agent="foo",
            global_agent="alice.athena.foo",
            primary_revision="a" * 40,
            local_hood="foo",
        )
    )
    other = enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key="other",
            project="Other",
            local_agent="bar",
            global_agent="alice.athena.bar",
            primary_revision="c" * 40,
            local_hood="bar",
        )
    )
    retire_publication(item)
    retire_publication(other, "other project failure")
    plant_fulfilled_publication(sync_target.sidecar_path)
    _stub_mocked_sync(
        monkeypatch,
        sync_target,
        outcome=SyncOutcome("proj", "Project", error="git push failed"),
    )

    [outcome] = git_sync.sync_agents(("proj",), retry_retired=True)

    assert outcome.error == "git push failed"
    [remaining] = list_agent_publications("proj")
    assert remaining.logical_key == item.logical_key
    assert not remaining.terminal
    assert remaining.attempts == 0
    [still_other] = list_agent_publications("other")
    assert still_other.terminal
    assert still_other.terminal_reason == "other project failure"


def test_retry_retired_does_not_clear_referenced_by_terminal_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agents_sync.referenced_by_outbox import (
        ReferencedByOutboxItem,
        enqueue_referenced_by_request,
        list_referenced_by_requests,
        update_referenced_by_requests,
    )

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    sync_target = target(tmp_path, tmp_path / "remote.git", tmp_path / "sidecar")
    item = enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key=sync_target.project_key,
            project=sync_target.project,
            local_agent="foo",
            global_agent="alice.athena.foo",
            primary_revision="a" * 40,
            local_hood="foo",
        )
    )
    cited = enqueue_referenced_by_request(
        ReferencedByOutboxItem(
            project_key="proj",
            project="Project",
            global_agent="alice.athena.worker",
            agent_url="https://example.test/agents/worker",
            primary_revision="a" * 40,
            sidecar_role="plans",
            provider="plan",
            artifact_id="plan:202608/example.md",
            repo_relpath="202608/example.md",
            identity_value=None,
            canonical_ref="plan:202608/example.md",
            destination="https://example.test/prompts/1",
            uses=1,
            published_date="2026-08-12",
        )
    )
    retire_publication(item)
    for _ in range(2):
        update_referenced_by_requests(
            "proj",
            (cited.logical_key,),
            error="write-back failed",
            increment_attempts=True,
            quarantine_threshold=2,
            terminal_reason="write-back failed",
        )
    plant_fulfilled_publication(sync_target.sidecar_path)
    _stub_mocked_sync(monkeypatch, sync_target)

    git_sync.sync_agents(("proj",), retry_retired=True)

    assert list_agent_publications("proj") == ()
    [still_cited] = list_referenced_by_requests("proj")
    assert still_cited.terminal
    assert still_cited.terminal_reason == "write-back failed"


def test_retry_retired_e2e_publishes_to_a_local_bare_remote(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    sync_target, remote = setup_target(tmp_path)
    item = enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key=sync_target.project_key,
            project=sync_target.project,
            local_agent="foo",
            global_agent="alice.athena.foo",
            primary_revision="a" * 40,
            local_hood="foo",
        )
    )
    retire_publication(item)
    monkeypatch.setattr(
        git_sync,
        "resolve_sync_targets",
        lambda _projects: TargetSelection((sync_target,), ()),
    )
    monkeypatch.setattr(
        git_sync,
        "require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )
    monkeypatch.setattr(
        git_sync,
        "build_project_hood_inventory",
        lambda *_args, **_kwargs: ProjectHoodInventory(
            AgentOwnerIdentity("alice", "athena"),
            "proj",
            (),
        ),
    )

    def reconcile(_target: ProjectTarget, repo: Path, **_kwargs: object):
        plant_fulfilled_publication(repo)
        (repo / "README.md").write_text("# Agents\n", encoding="utf-8")
        (repo / "schema.json").write_text("{}\n", encoding="utf-8")
        for directory in ("users", "families", "sessions"):
            (repo / directory).mkdir(exist_ok=True)
            (repo / directory / ".gitkeep").write_text("", encoding="utf-8")
        return V2PublicationCounts(hoods_published=1)

    monkeypatch.setattr(git_sync, "reconcile_agent_hoods", reconcile)
    monkeypatch.setattr(
        "sase.agents_sync.status.rewrite_agents_sync_status_after_sync",
        lambda _projects: None,
    )

    [outcome] = git_sync.sync_agents(("proj",), retry_retired=True)

    assert outcome.error is None
    assert outcome.pushed
    assert list_agent_publications("proj") == ()
    verify = tmp_path / "verify-retired"
    git(tmp_path, "clone", str(remote), str(verify))
    assert (verify / "agents" / "alice.athena.foo" / "README.md").is_file()
    assert "foo" in (verify / "agents" / "alice.athena.foo" / "README.md").read_text()
