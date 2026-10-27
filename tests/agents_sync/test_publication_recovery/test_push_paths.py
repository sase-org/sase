"""Snapshot, pre-stage, and end-to-end push-path recovery tests."""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess

import pytest

from sase.agents_sync import publication_recovery as recovery
from sase.agents_sync.publication_protection import (
    PublicationProtectionScope,
    lookup_publication_content_record,
    publication_content_retry_allowed,
    record_publication_push_rejection,
)
from tests.agents_sync.test_publication_recovery._helpers import (
    CLEAN_REL,
    TOKEN,
    commit,
    gh013_stderr,
    git,
    isolate_protection,
    scope_for,
    setup_repo,
    tip,
    upstream_tip,
)


def _gated_run(prompt_bytes: bytes):
    from sase.agents_sync.inventory_models import InventoryRun
    from sase.core.agent_identity_facade import AgentOwnerIdentity
    from sase.agents_sync.v2_models import V2ProjectIdentity

    owner = AgentOwnerIdentity("alice", "athena")
    project = V2ProjectIdentity("proj", "Project")
    run = InventoryRun(
        "run-1",
        "worker",
        "alice.athena.worker",
        "completed",
        "2026-07-23T12:00:00+00:00",
        "2026-07-23T12:01:00+00:00",
        None,
        (("model", "gpt"),),
        (),
        prompt_bytes,
        b"clean chat\n",
        None,
        None,
        (),
        "20260723120000",
    )
    return run, owner, project


def test_snapshot_regeneration_withholds_rejection_blocked_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync.publication_snapshot import _gate_run_files

    isolate_protection(monkeypatch, tmp_path)
    scope = PublicationProtectionScope(
        project_key="proj", repository_identity="https://example.test/sidecar.git"
    )
    prompt_bytes = b"ordinary prompt the remote rejected\n"
    digest = hashlib.sha256(prompt_bytes).hexdigest()
    destination = "agents/alice.athena.worker/prompt.md"
    assert (
        record_publication_push_rejection(
            scope.project_key,
            repository_identity=scope.repository_identity,
            relative_destination=destination,
            sha256=digest,
            classification=recovery.REJECTED_SECRET_SCAN,
        )
        is not None
    )

    run, owner, project = _gated_run(prompt_bytes)
    payload: dict[str, bytes] = {}
    gated = _gate_run_files(run, owner, project, payload, scope=scope)

    assert gated.record is not None
    assert destination not in payload
    assert "prompt" in gated.blocked_kinds
    assert any("blocked" in note for note in gated.notes)


def test_snapshot_regeneration_publishes_unblocked_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync.publication_snapshot import _gate_run_files

    isolate_protection(monkeypatch, tmp_path)
    scope = PublicationProtectionScope(
        project_key="proj", repository_identity="https://example.test/sidecar.git"
    )
    prompt_bytes = b"ordinary prompt nobody rejected\n"

    run, owner, project = _gated_run(prompt_bytes)
    payload: dict[str, bytes] = {}
    gated = _gate_run_files(run, owner, project, payload, scope=scope)

    assert gated.record is not None
    assert payload["agents/alice.athena.worker/prompt.md"] == prompt_bytes


def test_pre_stage_verification_withholds_rejection_blocked_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync._git_sync_ops_payload import (
        _verify_agents_payload_protection,
    )
    from sase.agents_sync.git import run_git

    remote, sidecar = setup_repo(tmp_path)
    isolate_protection(monkeypatch, tmp_path)
    scope = scope_for(remote)
    rel = "agents/local.athena.worker/chat.md"
    commit(sidecar, rel, b"previously published bytes\n", "baseline")
    blocked_bytes = b"rejected bytes returned through another path\n"
    (sidecar / rel).write_bytes(blocked_bytes)
    assert (
        record_publication_push_rejection(
            scope.project_key,
            repository_identity=scope.repository_identity,
            relative_destination=rel,
            sha256=hashlib.sha256(blocked_bytes).hexdigest(),
            classification=recovery.REJECTED_SECRET_SCAN,
        )
        is not None
    )

    error = _verify_agents_payload_protection(sidecar, run_git, scope=scope)

    assert error is not None and "withheld" in error


def test_pre_stage_verification_passes_unblocked_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync._git_sync_ops_payload import (
        _verify_agents_payload_protection,
    )
    from sase.agents_sync.git import run_git

    remote, sidecar = setup_repo(tmp_path)
    isolate_protection(monkeypatch, tmp_path)
    scope = scope_for(remote)
    candidate = sidecar / CLEAN_REL
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_bytes(b"ordinary clean bytes\n")

    assert _verify_agents_payload_protection(sidecar, run_git, scope=scope) is None


def _gh013_push_runner(rejections: int, stderr: str):
    from sase.agents_sync.git import run_git

    calls: list[int] = []

    def runner(
        cwd: Path, args: list[str], *, network: bool = False, op: str = ""
    ) -> subprocess.CompletedProcess[str]:
        if args == ["push"]:
            calls.append(1)
            if len(calls) <= rejections:
                return subprocess.CompletedProcess(args, 1, "", stderr)
        return run_git(cwd, args, network=network, op=op)

    return runner, calls


def test_full_sync_recovers_from_gh013_and_publishes_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync import git_sync
    from sase.agents_sync.v2_models import V2PublicationCounts
    from tests.agents_sync.git_sync_fixtures import (
        setup_repo as setup_sync_repo,
    )
    from tests.agents_sync.git_sync_fixtures import (
        target as make_target,
    )

    remote, _seed, sidecar = setup_sync_repo(tmp_path)
    sync_target = make_target(tmp_path, remote, sidecar)
    isolate_protection(monkeypatch, tmp_path)
    blocked_rel = "agents/local.athena.worker/notes.md"
    first_bytes = b"rollout note the remote rejected\n"
    second_bytes = b"rollout note sanitized for publication\n"
    calls: list[int] = []

    def reconcile(_target, repo: Path, **_kwargs) -> V2PublicationCounts:
        calls.append(1)
        (repo / "README.md").write_text("# Hoods\n")
        (repo / "schema.json").write_text("{}\n")
        bundle = repo / "agents" / "local.athena.worker"
        bundle.mkdir(parents=True, exist_ok=True)
        (bundle / "notes.md").write_bytes(
            first_bytes if len(calls) == 1 else second_bytes
        )
        for directory in ("users", "families", "sessions"):
            (repo / directory).mkdir(exist_ok=True)
        return V2PublicationCounts(hoods_published=1, runs_published=1)

    monkeypatch.setattr(git_sync, "reconcile_agent_hoods", reconcile)
    runner, push_calls = _gh013_push_runner(1, gh013_stderr(blocked_rel))

    outcome = git_sync._sync_project(sync_target, "athena", git_runner=runner)

    assert outcome.error is None
    assert outcome.pushed and outcome.push_attempts == 2
    assert len(push_calls) == 2 and len(calls) == 2
    check = tmp_path / "check"
    git(tmp_path, "clone", str(remote), str(check))
    assert (check / blocked_rel).read_bytes() == second_bytes
    missing = subprocess.run(
        ["git", "grep", "-l", "remote rejected", "HEAD"],
        cwd=check,
        capture_output=True,
        text=True,
    )
    assert missing.returncode == 1
    assert TOKEN not in repr(outcome)
    scope = PublicationProtectionScope(
        project_key="proj", repository_identity=str(remote)
    )
    assert not publication_content_retry_allowed(
        scope.project_key,
        repository_identity=scope.repository_identity,
        relative_destination=blocked_rel,
        sha256=hashlib.sha256(first_bytes).hexdigest(),
    )


def test_commit_drain_recovers_from_gh013_and_rebuilds_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync.commit_publication_transaction import (
        PublicationTransactionHooks,
        publish_queued_transaction,
    )
    from sase.agents_sync.inventory import ProjectHoodInventory
    from sase.agents_sync.publication_outbox_models import AgentPublicationOutboxItem
    from sase.agents_sync.v2_io import owner_manifest_path, v2_json_bytes
    from sase.agents_sync.v2_models import (
        V2OwnerHoodEntry,
        V2OwnerManifest,
        V2ProjectIdentity,
        V2PublicationCounts,
    )
    from sase.core.agent_identity_facade import AgentOwnerIdentity
    from tests.agents_sync.commit_publication_fixtures import setup_target

    target, remote = setup_target(tmp_path)
    isolate_protection(monkeypatch, tmp_path)
    owner = AgentOwnerIdentity("alice", "athena")
    first = b"hood page the remote rejected\n"
    second = b"hood page sanitized\n"
    writes: list[int] = []

    def publish_hood(_target, repo: Path, _agent: str, **_kwargs) -> object:
        writes.append(1)
        (repo / "README.md").write_bytes(first if len(writes) == 1 else second)
        (repo / "schema.json").write_text("{}\n")
        manifest = V2OwnerManifest(
            owner,
            V2ProjectIdentity("proj", "Project"),
            (("foo", V2OwnerHoodEntry("d" * 64, ("README.md",), 1, 1)),),
        )
        path = repo / owner_manifest_path(owner)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(v2_json_bytes(manifest.to_json_dict()))
        return V2PublicationCounts(hoods_published=1)

    updated: list[tuple[tuple[object, ...], dict[str, object]]] = []
    hooks = PublicationTransactionHooks(
        build_inventory=lambda *args, **kwargs: ProjectHoodInventory(owner, "proj", ()),
        publish_hood=publish_hood,
        update_publications=lambda *args, **kwargs: updated.append((args, kwargs)),
        acknowledge_publications=lambda *args, **kwargs: None,
        configured_max_attempts=lambda: 5,
    )
    runner, push_calls = _gh013_push_runner(1, gh013_stderr("README.md"))
    request = AgentPublicationOutboxItem(
        project_key="proj",
        project="Project",
        local_agent="foo",
        global_agent="alice.athena.foo",
        primary_revision="a" * 40,
        local_hood="foo",
    )

    result = publish_queued_transaction(target, owner, runner, (request,), hooks=hooks)

    assert result.error is None
    assert len(push_calls) == 2 and len(writes) == 2
    check = tmp_path / "check"
    git(tmp_path, "clone", str(remote), str(check))
    assert (check / "README.md").read_bytes() == second
    assert TOKEN not in repr(result)
    assert not publication_content_retry_allowed(
        "proj",
        repository_identity=str(remote),
        relative_destination="README.md",
        sha256=hashlib.sha256(first).hexdigest(),
    )


def test_prompt_publish_gh013_resets_and_sanitizes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync.git import run_git
    from sase.agents_sync.prompt_archive.publish import (
        _classify_prompt_archive_push_error,
    )

    remote, sidecar = setup_repo(tmp_path)
    isolate_protection(monkeypatch, tmp_path)
    scope = PublicationProtectionScope(
        project_key="proj", repository_identity=str(remote)
    )
    rel = "prompts/alice.athena.worker/prompt.md"
    content = b"prompt the remote rejected\n"
    commit(sidecar, rel, content, "prompt unit")
    base_tip = upstream_tip(sidecar)
    pushed = subprocess.CompletedProcess(["push"], 1, "", gh013_stderr(rel))

    message = _classify_prompt_archive_push_error(sidecar, run_git, pushed, scope)

    assert TOKEN not in message and rel in message
    assert tip(sidecar) == base_tip
    record = lookup_publication_content_record(
        scope.project_key,
        repository_identity=scope.repository_identity,
        relative_destination=rel,
        sha256=hashlib.sha256(content).hexdigest(),
    )
    assert isinstance(record, dict) and record.get("status") == "blocked"


def test_migration_push_detail_sanitizes_secret_rejections() -> None:
    from sase.agents_sync.prompt_archive.migration import (
        _sanitized_migration_push_detail,
    )

    rejected = subprocess.CompletedProcess(
        ["push", "origin", "HEAD"], 1, "", gh013_stderr("prompts/past.md")
    )
    detail = _sanitized_migration_push_detail(rejected)
    assert TOKEN not in detail
    assert "secret scanning" in detail

    generic = subprocess.CompletedProcess(
        ["push", "origin", "HEAD"], 1, "", "planned push failure"
    )
    assert _sanitized_migration_push_detail(generic) == "planned push failure"
