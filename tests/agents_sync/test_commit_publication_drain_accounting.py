"""Scoped failure accounting and bounded selection for commit drains."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase._interruptions import PublicationDrainTimedOut
from sase.agents_sync import (
    _commit_publication_drain as publication_drain,
    _commit_publication_locked as publication_locked,
    _commit_publication_support as publication_support,
)
from sase.agents_sync.commit_publication import publish_committed_agent_hood
from sase.agents_sync.git import run_git
from sase.agents_sync.models import TargetSelection
from sase.agents_sync.publication_outbox import (
    AgentPublicationOutboxItem,
    enqueue_agent_publication,
    list_agent_publications,
)
from sase.agents_sync.v2_io import owner_manifest_path, v2_json_bytes
from sase.agents_sync.v2_models import (
    V2OwnerHoodEntry,
    V2OwnerManifest,
    V2ProjectIdentity,
    V2PublicationCounts,
)
from sase.core.agent_identity_facade import AgentOwnerIdentity
from tests.agents_sync.commit_publication_fixtures import setup_target
from tests.agents_sync.git_sync_fixtures import plant_fulfilled_publication


def _configure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, owner: AgentOwnerIdentity
):
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, _remote = setup_target(tmp_path)
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
        "sase.agents_sync.publication_completion.publication_request_fulfilled",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "sase.agents_sync.prompt_archive.deferred.restore_deferred_prompt_archives",
        lambda *_args, **_kwargs: {},
    )
    return target


def _enqueue(project: str, hood: str, revision: str) -> AgentPublicationOutboxItem:
    return enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key="proj",
            project=project,
            local_agent=f"{hood}--code",
            global_agent=f"alice.athena.{hood}--code",
            primary_revision=revision,
            local_hood=hood,
        )
    )


def test_record_failure_repository_preserves_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target, _remote = setup_target(tmp_path)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    for hood, revision in (("good", "a" * 40), ("bad", "b" * 40)):
        _enqueue("Project", hood, revision)
    before = {
        item.logical_key: item.attempts for item in list_agent_publications("proj")
    }

    outcome = publication_drain._record_failure(
        target,
        "git pull --rebase failed: network is unavailable",
        scope="repository",
        stage="pull_rebase",
    )

    assert outcome.queued
    assert outcome.error is not None
    after = list_agent_publications("proj")
    assert len(after) == 2
    for item in after:
        assert item.attempts == before[item.logical_key]
        assert item.last_error is None


def test_lock_busy_does_not_charge_agent_publication_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target, _remote = setup_target(tmp_path)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    _enqueue("Project", "worker", "a" * 40)

    outcome = publication_drain._record_failure(
        target,
        "agents sync lock is busy",
        scope="repository",
        stage="acquire_lock",
    )

    [remaining] = list_agent_publications("proj")
    assert outcome.queued
    assert remaining.attempts == 0
    assert remaining.last_error is None


def test_scanner_timeout_unwinds_drain_and_leaves_request_queued(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    _configure(monkeypatch, tmp_path, owner)
    _enqueue("Project", "worker", "a" * 40)

    def timeout_binding(*_args, **_kwargs):
        raise PublicationDrainTimedOut("scanner alarm")

    monkeypatch.setattr(
        "sase.core.rust.require_rust_binding",
        lambda name: timeout_binding,
    )

    def publish_until_scanner(*_args, **_kwargs):
        from sase.agents_sync.publication_protection import scan_publication_bytes

        scan_publication_bytes(b"prompt text", max_bytes=1024)

    monkeypatch.setattr(
        publication_drain, "publish_queued_locked", publish_until_scanner
    )

    outcome = publication_drain.drain_agent_publications("proj")

    [remaining] = list_agent_publications("proj", include_quarantined=False)
    assert outcome.error == "scanner alarm"
    assert remaining.attempts == 0
    assert remaining.logical_key == ("alice.athena.worker--code", "a" * 40)


def test_record_failure_hood_charges_only_attempted_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target, _remote = setup_target(tmp_path)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    good_key = ("alice.athena.good--code", "a" * 40)
    bad_key = ("alice.athena.bad--code", "b" * 40)
    _enqueue("Project", "good", "a" * 40)
    _enqueue("Project", "bad", "b" * 40)

    outcome = publication_drain._record_failure(
        target,
        "agent-hood publication did not complete within 120s",
        (bad_key,),
        scope="hood",
        stage="hood_publish:bad",
    )

    assert outcome.queued
    remaining = {item.logical_key: item for item in list_agent_publications("proj")}
    assert remaining[good_key].attempts == 0
    assert remaining[good_key].last_error is None
    assert remaining[bad_key].attempts == 1
    assert remaining[bad_key].last_error is not None


def test_commit_drain_prefers_new_request_and_caps_at_25(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    target = _configure(monkeypatch, tmp_path, owner)
    for index in range(30):
        _enqueue("Project", f"hood{index % 3}", f"{index:040x}")
    new_item = _enqueue("Project", "fresh", "f" * 40)

    def publish(_target, repo, _agent, **_kwargs):
        manifest = V2OwnerManifest(
            owner,
            V2ProjectIdentity("proj", "Project"),
            tuple(
                (hood, V2OwnerHoodEntry("d" * 64, ("README.md",), 1, 1))
                for hood in ("hood0", "hood1", "hood2", "fresh")
            ),
        )
        path = repo / owner_manifest_path(owner)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(v2_json_bytes(manifest.to_json_dict()))
        return V2PublicationCounts(hoods_published=1)

    monkeypatch.setattr(publication_locked, "publish_agent_hood", publish)

    result = publication_locked.publish_queued_locked(
        target, owner, run_git, preferred_key=new_item.logical_key
    )

    assert result.error is None
    assert result.drained == 25
    remaining = list_agent_publications("proj")
    assert len(remaining) == 6
    assert new_item.logical_key not in {item.logical_key for item in remaining}


def test_completion_gate_withholds_unfulfilled_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    target, _remote = setup_target(tmp_path)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
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
    _enqueue("Project", "foo", "a" * 40)
    _enqueue("Project", "bar", "b" * 40)

    def publish(_target, repo, agent, **_kwargs):
        hood = agent.split("--", 1)[0]
        if hood == "foo":
            plant_fulfilled_publication(
                repo,
                owner=owner,
                local_agent="foo--code",
                global_agent="alice.athena.foo--code",
                revision="a" * 40,
                local_hood="foo",
            )
        manifest = V2OwnerManifest(
            owner,
            V2ProjectIdentity("proj", "Project"),
            (
                ("foo", V2OwnerHoodEntry("d" * 64, ("README.md",), 1, 1)),
                ("bar", V2OwnerHoodEntry("e" * 64, ("README.md",), 1, 1)),
            ),
        )
        path = repo / owner_manifest_path(owner)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(v2_json_bytes(manifest.to_json_dict()))
        return V2PublicationCounts(hoods_published=1)

    monkeypatch.setattr(publication_locked, "publish_agent_hood", publish)

    outcome = publish_committed_agent_hood(
        "bar--code", "b" * 40, project="Project", git_runner=run_git
    )

    assert outcome.queued
    remaining = {item.logical_key for item in list_agent_publications("proj")}
    assert ("alice.athena.bar--code", "b" * 40) in remaining


def test_cleanup_after_success_does_not_resurrect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    target = _configure(monkeypatch, tmp_path, owner)
    _enqueue("Project", "foo", "a" * 40)

    def publish(_target, repo, _agent, **_kwargs):
        manifest = V2OwnerManifest(
            owner,
            V2ProjectIdentity("proj", "Project"),
            (("foo", V2OwnerHoodEntry("d" * 64, ("README.md",), 1, 1)),),
        )
        path = repo / owner_manifest_path(owner)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(v2_json_bytes(manifest.to_json_dict()))
        return V2PublicationCounts(hoods_published=1)

    monkeypatch.setattr(publication_locked, "publish_agent_hood", publish)

    from sase.agents_sync import git_sync

    original_clean = git_sync.clean_publication_worktree
    calls = 0

    def clean(repo, runner):
        nonlocal calls
        calls += 1
        if calls == 1:
            return original_clean(repo, runner)
        return "archive cleanup failed"

    monkeypatch.setattr(git_sync, "clean_publication_worktree", clean)

    result = publication_locked.publish_queued_locked(target, owner, run_git)

    assert result.drained == 1
    assert result.error is not None and "archive cleanup failed" in result.error
    assert result.error_keys == ()
    assert list_agent_publications("proj") == ()


def _enqueue_named(
    *,
    local_agent: str,
    global_agent: str,
    local_hood: str,
    revision: str,
) -> AgentPublicationOutboxItem:
    return enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key="proj",
            project="Project",
            local_agent=local_agent,
            global_agent=global_agent,
            primary_revision=revision,
            local_hood=local_hood,
        )
    )


def _remaining(project_key: str = "proj") -> dict[tuple[str, str], object]:
    return {item.logical_key: item for item in list_agent_publications(project_key)}


def test_mixed_hood_parks_blocked_sibling_without_charging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync.publication_snapshot import RUN_WITHHELD_BLOCKED

    owner = AgentOwnerIdentity("alice", "athena")
    target = _configure(monkeypatch, tmp_path, owner)
    clean = _enqueue_named(
        local_agent="foo.clean",
        global_agent="alice.athena.foo.clean",
        local_hood="foo",
        revision="a" * 40,
    )
    blocked = _enqueue_named(
        local_agent="foo.blocked",
        global_agent="alice.athena.foo.blocked",
        local_hood="foo",
        revision="b" * 40,
    )

    def publish(_target, repo, _agent, **_kwargs):
        plant_fulfilled_publication(
            repo,
            owner=owner,
            local_agent="foo.clean",
            global_agent="alice.athena.foo.clean",
            revision="a" * 40,
            local_hood="foo",
        )
        manifest = V2OwnerManifest(
            owner,
            V2ProjectIdentity("proj", "Project"),
            (("foo", V2OwnerHoodEntry("d" * 64, ("README.md",), 1, 1)),),
        )
        path = repo / owner_manifest_path(owner)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(v2_json_bytes(manifest.to_json_dict()))
        return V2PublicationCounts(
            hoods_published=1,
            withheld_runs=(("alice.athena.foo.blocked", "blocked"),),
        )

    monkeypatch.setattr(publication_locked, "publish_agent_hood", publish)
    result = publication_locked.publish_queued_locked(target, owner, run_git)

    remaining = _remaining()
    assert clean.logical_key not in remaining
    parked = remaining[blocked.logical_key]
    assert parked.attempts == 0
    assert parked.terminal is False
    assert parked.quarantined is False
    assert parked.last_error == RUN_WITHHELD_BLOCKED
    assert "did not materialize" not in (parked.last_error or "")
    assert RUN_WITHHELD_BLOCKED in result.item_errors


def test_fully_blocked_hood_is_parked_not_retired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync.publication_snapshot import HOOD_WITHHELD_BLOCKED

    owner = AgentOwnerIdentity("alice", "athena")
    target = _configure(monkeypatch, tmp_path, owner)
    request = _enqueue_named(
        local_agent="foo",
        global_agent="alice.athena.foo",
        local_hood="foo",
        revision="a" * 40,
    )

    def publish(_target, repo, _agent, **_kwargs):
        manifest = V2OwnerManifest(
            owner,
            V2ProjectIdentity("proj", "Project"),
            (("other", V2OwnerHoodEntry("d" * 64, ("README.md",), 1, 1)),),
        )
        path = repo / owner_manifest_path(owner)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(v2_json_bytes(manifest.to_json_dict()))
        return V2PublicationCounts(withheld_hoods=(("foo", "blocked"),))

    monkeypatch.setattr(publication_locked, "publish_agent_hood", publish)
    publication_locked.publish_queued_locked(target, owner, run_git)

    parked = _remaining()[request.logical_key]
    assert parked.attempts == 0
    assert parked.terminal is False
    assert parked.quarantined is False
    assert parked.terminal_reason is None
    assert parked.last_error == HOOD_WITHHELD_BLOCKED
    assert "did not materialize" not in (parked.last_error or "")


def test_unverified_sibling_retries_without_charging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync.publication_snapshot import RUN_WITHHELD_UNVERIFIED

    owner = AgentOwnerIdentity("alice", "athena")
    target = _configure(monkeypatch, tmp_path, owner)
    clean = _enqueue_named(
        local_agent="foo.clean",
        global_agent="alice.athena.foo.clean",
        local_hood="foo",
        revision="a" * 40,
    )
    unverified = _enqueue_named(
        local_agent="foo.probe",
        global_agent="alice.athena.foo.probe",
        local_hood="foo",
        revision="c" * 40,
    )

    def publish(_target, repo, _agent, **_kwargs):
        plant_fulfilled_publication(
            repo,
            owner=owner,
            local_agent="foo.clean",
            global_agent="alice.athena.foo.clean",
            revision="a" * 40,
            local_hood="foo",
        )
        manifest = V2OwnerManifest(
            owner,
            V2ProjectIdentity("proj", "Project"),
            (("foo", V2OwnerHoodEntry("d" * 64, ("README.md",), 1, 1)),),
        )
        path = repo / owner_manifest_path(owner)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(v2_json_bytes(manifest.to_json_dict()))
        return V2PublicationCounts(
            hoods_published=1,
            withheld_runs=(("alice.athena.foo.probe", "unverified"),),
        )

    monkeypatch.setattr(publication_locked, "publish_agent_hood", publish)
    publication_locked.publish_queued_locked(target, owner, run_git)

    remaining = _remaining()
    assert clean.logical_key not in remaining
    parked = remaining[unverified.logical_key]
    assert parked.attempts == 0
    assert parked.terminal is False
    assert parked.quarantined is False
    assert parked.last_error == RUN_WITHHELD_UNVERIFIED


def test_fully_unverified_hood_retries_without_charging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync.publication_snapshot import HOOD_WITHHELD_UNVERIFIED

    owner = AgentOwnerIdentity("alice", "athena")
    target = _configure(monkeypatch, tmp_path, owner)
    request = _enqueue_named(
        local_agent="probe",
        global_agent="alice.athena.probe",
        local_hood="probe",
        revision="d" * 40,
    )

    def publish(_target, _repo, _agent, **_kwargs):
        return V2PublicationCounts(withheld_hoods=(("probe", "unverified"),))

    monkeypatch.setattr(publication_locked, "publish_agent_hood", publish)
    publication_locked.publish_queued_locked(target, owner, run_git)

    parked = _remaining()[request.logical_key]
    assert parked.attempts == 0
    assert parked.terminal is False
    assert parked.quarantined is False
    assert parked.last_error == HOOD_WITHHELD_UNVERIFIED


def test_second_drain_does_not_publish_blocked_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync import publication_protection as protection
    from sase.agents_sync.inventory import ProjectHoodInventory
    from sase.agents_sync.publication_snapshot import RUN_WITHHELD_BLOCKED
    from tests.agents_sync.publication_fixtures import _run
    from tests.agents_sync.test_transcript_publication_protection import (
        MARKER,
        _install_marker_scanner,
    )

    _install_marker_scanner(monkeypatch)
    owner = AgentOwnerIdentity("alice", "athena")
    target = _configure(monkeypatch, tmp_path, owner)
    monkeypatch.setattr(protection, "sase_home", lambda: tmp_path / "state")
    monkeypatch.setattr(
        protection, "sase_projects_dir", lambda: tmp_path / "state" / "projects"
    )
    blocked_run = _run(
        "foo.blocked",
        "22",
        commit=True,
        output_variables={"note": MARKER.decode()},
    )
    inventory = ProjectHoodInventory(owner, "proj", (blocked_run,))
    monkeypatch.setattr(
        publication_locked,
        "build_project_hood_inventory",
        lambda *_args, **_kwargs: inventory,
    )
    request = _enqueue_named(
        local_agent="foo.blocked",
        global_agent="alice.athena.foo.blocked",
        local_hood="foo",
        revision="b" * 40,
    )
    first = publication_locked.publish_queued_locked(target, owner, run_git)
    second = publication_locked.publish_queued_locked(target, owner, run_git)

    remaining = _remaining()[request.logical_key]
    assert remaining.attempts == 0
    assert remaining.terminal is False
    assert remaining.last_error == RUN_WITHHELD_BLOCKED
    assert "did not materialize" not in first.item_errors
    assert "did not materialize" not in second.item_errors
    blobs = {
        path.read_bytes()
        for path in target.sidecar_path.rglob("*")
        if path.is_file() and ".git" not in path.parts
    }
    assert not any(MARKER in content for content in blobs)
    assert not (target.sidecar_path / "agents" / "alice.athena.foo.blocked").exists()
