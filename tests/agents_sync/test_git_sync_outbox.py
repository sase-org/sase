from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sase.agents_sync import git_sync
from sase.agents_sync.models import (
    ProjectTarget,
    SyncOutcome,
    TargetSelection,
)
from sase.agents_sync.publication_outbox import (
    AgentPublicationOutboxItem,
    enqueue_agent_publication,
    list_agent_publications,
    update_agent_publications,
)
from sase.core.agent_identity_facade import AgentOwnerIdentity

from tests.agents_sync.git_sync_fixtures import target


def test_all_project_sync_isolates_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = target(tmp_path / "one", tmp_path / "one.git", tmp_path / "one-sidecar")
    second = target(tmp_path / "two", tmp_path / "two.git", tmp_path / "two-sidecar")
    first = ProjectTarget(
        "one",
        "One",
        first.primary_checkout,
        first.primary_roots,
        first.sidecar_path,
        first.remote_url,
    )
    second = ProjectTarget(
        "two",
        "Two",
        second.primary_checkout,
        second.primary_roots,
        second.sidecar_path,
        second.remote_url,
    )
    monkeypatch.setattr(
        git_sync,
        "resolve_sync_targets",
        lambda _projects: TargetSelection((first, second), ()),
    )
    monkeypatch.setattr(
        git_sync,
        "require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )
    monkeypatch.setattr(
        git_sync,
        "_sync_project",
        lambda target, *_args, **_kwargs: (
            (_ for _ in ()).throw(RuntimeError("broken"))
            if target.project_key == "one"
            else SyncOutcome("two", "Two", pulled=True)
        ),
    )
    monkeypatch.setattr(
        "sase.agents_sync.status.rewrite_agents_sync_status_after_sync",
        lambda _projects: None,
    )

    outcomes = git_sync.sync_agents()

    assert [outcome.project_key for outcome in outcomes] == ["one", "two"]
    assert outcomes[0].error == "agents sync failed: broken"
    assert outcomes[1].pulled is True


def test_full_sync_acknowledges_publication_outbox_after_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    sync_target = target(tmp_path, tmp_path / "remote.git", tmp_path / "sidecar")
    published_page = (
        sync_target.sidecar_path / "agents" / "alice.athena.foo" / "README.md"
    )
    published_page.parent.mkdir(parents=True)
    published_page.write_text("# foo\n")
    enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key=sync_target.project_key,
            project=sync_target.project,
            local_agent="foo",
            global_agent="alice.athena.foo",
            primary_revision="a" * 40,
            local_hood="foo",
        )
    )
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
        "_sync_project",
        lambda *_args, **_kwargs: SyncOutcome("proj", "Project", pulled=True),
    )
    monkeypatch.setattr(
        "sase.agents_sync.status.rewrite_agents_sync_status_after_sync",
        lambda _projects: None,
    )

    assert git_sync.sync_agents() == (SyncOutcome("proj", "Project", pulled=True),)
    assert list_agent_publications("proj") == ()


def test_full_sync_keeps_outbox_request_when_agent_page_did_not_materialize(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    sync_target = target(tmp_path, tmp_path / "remote.git", tmp_path / "sidecar")
    item = enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key=sync_target.project_key,
            project=sync_target.project,
            local_agent="missing",
            global_agent="alice.athena.missing",
            primary_revision="a" * 40,
            local_hood="missing",
        )
    )
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
        "_sync_project",
        lambda *_args, **_kwargs: SyncOutcome("proj", "Project", pulled=True),
    )
    monkeypatch.setattr(
        "sase.agents_sync.status.rewrite_agents_sync_status_after_sync",
        lambda _projects: None,
    )

    assert git_sync.sync_agents() == (SyncOutcome("proj", "Project", pulled=True),)
    remaining = list_agent_publications("proj")
    assert len(remaining) == 1
    assert remaining[0].logical_key == item.logical_key
    assert remaining[0].attempts == 1
    assert remaining[0].last_error == (
        "published agent page for 'alice.athena.missing' did not materialize "
        "during full sync"
    )

    [second] = git_sync.sync_agents()
    assert second == replace(
        SyncOutcome("proj", "Project", pulled=True),
        diagnostics=second.diagnostics,
    )
    assert "retired as unpublishable" in second.diagnostics[0]
    [retired] = list_agent_publications("proj")
    assert retired.attempts == 2
    assert retired.terminal
    assert retired.terminal_reason == retired.last_error
    assert not retired.quarantined
    assert list_agent_publications("proj", include_quarantined=False) == ()


def test_drop_retired_removes_only_retired_requests_and_reports_them(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    sync_target = target(tmp_path, tmp_path / "remote.git", tmp_path / "sidecar")
    published_page = (
        sync_target.sidecar_path / "agents" / "alice.athena.foo" / "README.md"
    )
    published_page.parent.mkdir(parents=True)
    published_page.write_text("# foo\n")
    active = enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key=sync_target.project_key,
            project=sync_target.project,
            local_agent="foo",
            global_agent="alice.athena.foo",
            primary_revision="a" * 40,
            local_hood="foo",
        )
    )
    doomed = enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key=sync_target.project_key,
            project=sync_target.project,
            local_agent="lt",
            global_agent="alice.athena.lt",
            primary_revision="b" * 40,
            local_hood="lt",
        )
    )
    terminal_error = "hood 'lt' has no publishable runs"
    for _ in range(2):
        update_agent_publications(
            sync_target.project_key,
            (doomed.logical_key,),
            error=terminal_error,
            increment_attempts=True,
            quarantine_threshold=3,
            terminal_reason=terminal_error,
        )
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
        "_sync_project",
        lambda *_args, **_kwargs: SyncOutcome("proj", "Project", pulled=True),
    )
    monkeypatch.setattr(
        "sase.agents_sync.status.rewrite_agents_sync_status_after_sync",
        lambda _projects: None,
    )

    [outcome] = git_sync.sync_agents(drop_retired=True)

    assert outcome.error is None
    assert outcome.diagnostics[0] == "dropped 1 retired publication request"
    assert terminal_error in outcome.diagnostics[1]
    assert "alice.athena.lt" in outcome.diagnostics[1]
    # The active request published during the same sync, so only the retired
    # one had to be dropped explicitly.
    assert list_agent_publications("proj") == ()
    assert active.logical_key != doomed.logical_key


def test_sync_without_drop_retired_keeps_and_reports_retired_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    sync_target = target(tmp_path, tmp_path / "remote.git", tmp_path / "sidecar")
    doomed = enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key=sync_target.project_key,
            project=sync_target.project,
            local_agent="lt",
            global_agent="alice.athena.lt",
            primary_revision="b" * 40,
            local_hood="lt",
        )
    )
    terminal_error = "hood 'lt' has no publishable runs"
    for _ in range(2):
        update_agent_publications(
            sync_target.project_key,
            (doomed.logical_key,),
            error=terminal_error,
            increment_attempts=True,
            quarantine_threshold=3,
            terminal_reason=terminal_error,
        )
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
        "_sync_project",
        lambda *_args, **_kwargs: SyncOutcome("proj", "Project", pulled=True),
    )
    monkeypatch.setattr(
        "sase.agents_sync.status.rewrite_agents_sync_status_after_sync",
        lambda _projects: None,
    )

    [outcome] = git_sync.sync_agents()

    assert len(list_agent_publications("proj")) == 1
    assert len(outcome.diagnostics) == 1
    assert "retired as unpublishable" in outcome.diagnostics[0]
    assert "sase agent sync --drop-retired" in outcome.diagnostics[0]
