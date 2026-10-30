"""A prompt archive deferred by lock contention still reaches the sidecar.

``publish_prompt_archive`` is best-effort: when the agents sync lock is busy it
returns without writing anything. The durable agent-hood publication request it
enqueued is what carries the prompt forward, so the next full ``sase agent
sync`` has to rebuild the archive before it acknowledges that request.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import sase_core_rs

from sase.agents_sync import git_sync
from sase.agents_sync.git import run_git
from sase.agents_sync.models import (
    ProjectTarget,
    TargetSelection,
)
from sase.agents_sync.prompt_archive import publish as archive_publish
from sase.agents_sync.prompt_archive.deferred import prepare_deferred_prompt_archive
from sase.agents_sync.prompt_archive.preparation import PreparedPromptArchive
from sase.agents_sync.prompt_archive.publish import (
    prepare_prompt_archive,
    publish_prompt_archive,
)
from sase.agents_sync.publication_outbox import AgentPublicationOutboxItem
from sase.agents_sync._commit_publication_transaction_steps import (
    acknowledge_completed,
)
from sase.agents_sync._commit_publication_transaction_types import (
    PublicationTransactionHooks,
)
from sase.agents_sync.inventory import ProjectHoodInventory
from sase.core.agent_identity_facade import AgentIdentitySnapshot
from sase.agents_sync.publication_outbox import list_agent_publications
from sase.agents_sync.v2_models import V2PublicationCounts
from sase.core.agent_identity_facade import AgentOwnerIdentity
from tests.agents_sync.commit_publication_fixtures import git, setup_target
from tests.agents_sync.git_sync_fixtures import plant_fulfilled_publication
from tests.agents_sync._prompt_archive_helpers import make_record, write_manifest

_AGENT = "worker"
_GLOBAL_AGENT = "alice.athena.worker"
_REVISION = "a" * 40
_OWNER = AgentOwnerIdentity("alice", "athena")


class _HostedLinks:
    def agent_url(self, name: str) -> str:
        return f"https://example.test/agents/{name}"

    def plan_url(self, plan_ref: str) -> str:
        return f"https://example.test/plans/{plan_ref}"

    def blob_url_for_repository(self, _root: Path, revision: str, path: str) -> str:
        return f"https://example.test/blob/{revision}/{path}"

    def commit_url_for_repository(self, _root: Path, sha: str) -> str:
        return f"https://example.test/commit/{sha}"


def _artifacts_dir(tmp_path: Path, target: ProjectTarget) -> Path:
    artifacts_dir = tmp_path / "runs/20260801130000"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"workspace_dir": str(target.primary_checkout)}),
        encoding="utf-8",
    )
    (artifacts_dir / "raw_xprompt.md").write_text(
        "Archive this prompt.\n",
        encoding="utf-8",
    )
    return artifacts_dir


def _stub_inventory(artifacts_dir: Path) -> SimpleNamespace:
    """One local run matching the queued request's lane and revision."""

    return SimpleNamespace(
        runs=(
            SimpleNamespace(
                local_name=_AGENT,
                global_name=_GLOBAL_AGENT,
                commits=(SimpleNamespace(sha=_REVISION),),
                source_label=str(artifacts_dir),
            ),
        ),
    )


@pytest.fixture
def deferred_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ProjectTarget, Path, Path]:
    """Defer one prompt archive on a busy lock, leaving its request queued."""

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, remote = setup_target(tmp_path)
    artifacts_dir = _artifacts_dir(tmp_path, target)
    monkeypatch.setattr(
        archive_publish,
        "resolve_sync_targets",
        lambda _projects: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(
        archive_publish,
        "require_agent_owner_identity",
        lambda: _OWNER,
    )
    monkeypatch.setattr(
        archive_publish,
        "_hosted_resolver",
        lambda *_args: _HostedLinks(),
    )
    monkeypatch.setattr("sase.file_references.format_with_prettier", lambda text: text)

    real_lock = git_sync.bounded_agents_lock
    contended = [True]

    @contextmanager
    def busy_once(path: Path, timeout_seconds: float):
        """Contend only the deferred publication, not the sync that follows."""

        if contended[0]:
            contended[0] = False
            yield False
            return
        with real_lock(path, timeout_seconds) as acquired:
            yield acquired

    monkeypatch.setattr(git_sync, "bounded_agents_lock", busy_once)
    outcome = publish_prompt_archive(
        _AGENT,
        _REVISION,
        project="Project",
        commit_cwd=target.primary_checkout,
        agent_artifacts_dir=artifacts_dir,
    )

    assert not outcome.published
    assert outcome.queued
    assert outcome.error == "agents sync lock is busy"
    [queued] = list_agent_publications(target.project_key)
    assert queued.logical_key == (_GLOBAL_AGENT, _REVISION)
    assert queued.commit_cwd == str(target.primary_checkout.resolve())
    assert queued.artifacts_dir == str(artifacts_dir.resolve())
    assert queued.run_id is None
    verify = tmp_path / "verify-deferred"
    git(tmp_path, "clone", str(remote), str(verify))
    assert not (verify / "prompts").exists()
    return target, remote, artifacts_dir


def _stub_full_sync(
    monkeypatch: pytest.MonkeyPatch,
    target: ProjectTarget,
    artifacts_dir: Path,
) -> None:
    """Run the real sync transaction over stubbed hood publication."""

    monkeypatch.setattr(
        git_sync,
        "resolve_sync_targets",
        lambda _projects: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(git_sync, "require_agent_owner_identity", lambda: _OWNER)
    monkeypatch.setattr(
        git_sync,
        "build_project_hood_inventory",
        lambda *_args, **_kwargs: _stub_inventory(artifacts_dir),
    )

    def reconcile(_target: ProjectTarget, repo: Path, **_kwargs: object):
        pending = list_agent_publications(_target.project_key)
        for item in pending:
            plant_fulfilled_publication(
                repo,
                local_agent=item.local_agent,
                global_agent=item.global_agent,
                revision=item.primary_revision,
                local_hood=item.local_hood,
                has_prompt_file=True,
            )
        # The rest of the payload path set has to exist for staging to run.
        (repo / "README.md").write_text("# Agents\n", encoding="utf-8")
        (repo / "schema.json").write_text("{}\n", encoding="utf-8")
        for directory in ("users", "families", "sessions"):
            (repo / directory).mkdir(exist_ok=True)
            (repo / directory / ".gitkeep").write_text("", encoding="utf-8")
        return V2PublicationCounts(hoods_published=1)

    monkeypatch.setattr(git_sync, "reconcile_agent_hoods", reconcile)
    monkeypatch.setattr(
        archive_publish,
        "_hosted_resolver",
        lambda *_args: _HostedLinks(),
    )
    monkeypatch.setattr(
        "sase.agents_sync.status.rewrite_agents_sync_status_after_sync",
        lambda _projects: None,
    )


def test_full_sync_publishes_the_prompt_archive_a_busy_lock_deferred(
    deferred_publication: tuple[ProjectTarget, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target, remote, artifacts_dir = deferred_publication
    _stub_full_sync(monkeypatch, target, artifacts_dir)

    [outcome] = git_sync.sync_agents(("proj",))

    assert outcome.error is None
    assert outcome.pushed
    verify = tmp_path / "verify-synced"
    git(tmp_path, "clone", str(remote), str(verify))
    prompt = verify / "prompts/202608" / f"{_GLOBAL_AGENT}.md"
    assert prompt.is_file()
    assert "Archive this prompt." in prompt.read_text(encoding="utf-8")
    # The request is only acknowledged once both halves reached the sidecar.
    assert list_agent_publications("proj") == ()


def test_full_sync_keeps_the_request_queued_when_the_archive_cannot_be_rebuilt(
    deferred_publication: tuple[ProjectTarget, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target, remote, artifacts_dir = deferred_publication
    _stub_full_sync(monkeypatch, target, artifacts_dir)

    def explode(**_kwargs: object) -> None:
        raise RuntimeError("prompt pool is unreadable")

    monkeypatch.setattr(archive_publish, "prepare_prompt_archive", explode)

    [outcome] = git_sync.sync_agents(("proj",))

    assert outcome.error is None
    assert any("prompt pool is unreadable" in line for line in outcome.diagnostics)
    verify = tmp_path / "verify-failed"
    git(tmp_path, "clone", str(remote), str(verify))
    assert not (verify / "prompts").exists()
    # The agent page materialized, but the prompt did not, so the request stays
    # retryable instead of being acknowledged or retired.
    [remaining] = list_agent_publications("proj")
    assert remaining.attempts == 1
    assert not remaining.terminal
    assert "prompt pool is unreadable" in str(remaining.last_error)


def test_full_sync_keeps_the_request_when_the_original_prompt_source_is_gone(
    deferred_publication: tuple[ProjectTarget, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target, remote, artifacts_dir = deferred_publication
    _stub_full_sync(monkeypatch, target, artifacts_dir)
    for leftover in artifacts_dir.glob("raw_*.md"):
        leftover.unlink()

    [outcome] = git_sync.sync_agents(("proj",))

    assert outcome.error is None
    verify = tmp_path / "verify-missing-source"
    git(tmp_path, "clone", str(remote), str(verify))
    assert not (verify / "prompts").exists()
    [remaining] = list_agent_publications("proj")
    assert remaining.attempts == 1
    assert not remaining.terminal
    assert remaining.last_error is not None
    assert "missing local source" in remaining.last_error or (
        "unresolved" in remaining.last_error
    )


def test_full_sync_parks_a_blocked_prompt_without_charging_attempts(
    deferred_publication: tuple[ProjectTarget, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from tests.agents_sync.test_prompt_archive_protection import (
        MARKER,
        _install_marker_scanner,
    )
    from sase.agents_sync.prompt_archive.protection import PROMPT_PROTECTION_BLOCKED

    target, remote, artifacts_dir = deferred_publication
    _install_marker_scanner(monkeypatch)
    (artifacts_dir / "raw_xprompt.md").write_text(
        f"deferred {MARKER.decode()}\n", encoding="utf-8"
    )
    _stub_full_sync(monkeypatch, target, artifacts_dir)

    [outcome] = git_sync.sync_agents(("proj",))

    assert outcome.error is None
    verify = tmp_path / "verify-blocked-deferred"
    git(tmp_path, "clone", str(remote), str(verify))
    assert not any(
        MARKER in path.read_bytes()
        for path in verify.rglob("*")
        if path.is_file() and ".git" not in path.parts
    )
    [remaining] = list_agent_publications("proj")
    assert remaining.attempts == 0
    assert not remaining.terminal
    assert remaining.last_error == PROMPT_PROTECTION_BLOCKED


def test_deferred_archive_matches_sync_after_workspace_head_moves(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, _remote = setup_target(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    git(workspace, "init", "-q")
    git(workspace, "config", "user.name", "Tests")
    git(workspace, "config", "user.email", "tests@example.test")
    source_file = workspace / "src/demo.py"
    source_file.parent.mkdir()
    source_file.write_text("print('revision one')\n", encoding="utf-8")
    git(workspace, "add", "src/demo.py")
    git(workspace, "commit", "-m", "first workspace revision")
    primary_revision = git(workspace, "rev-parse", "HEAD").stdout.strip()

    artifacts_dir = tmp_path / "runs" / "run-parity"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"workspace_dir": str(workspace)}), encoding="utf-8"
    )
    (artifacts_dir / "raw_xprompt.md").write_text(
        "Use @src/demo.py and @diagram.png.\n", encoding="utf-8"
    )
    pool_bytes = b"pooled screenshot bytes"
    digest = hashlib.sha256(pool_bytes).hexdigest()
    pool_name = sase_core_rs.prompt_artifact_pool_filename(digest, "diagram.png")
    pool_path = workspace / ".sase/artifacts/pool" / pool_name
    pool_path.parent.mkdir(parents=True)
    pool_path.write_bytes(pool_bytes)
    file_record = make_record(
        artifacts_dir=artifacts_dir,
        raw_ref="@src/demo.py",
        label="src/demo.py",
        vcs_repo="primary",
        vcs_relpath="src/demo.py",
    )
    file_record["source_path"] = str(source_file)
    pooled_record = make_record(
        artifacts_dir=artifacts_dir,
        raw_ref="@diagram.png",
        label="diagram.png",
        sha256=digest,
        pool_relpath=f"pool/{pool_name}",
    )
    write_manifest(workspace, [file_record, pooled_record])
    monkeypatch.setattr(
        archive_publish, "_hosted_resolver", lambda *_args: _HostedLinks()
    )
    monkeypatch.setattr(
        archive_publish,
        "_repository_roots",
        lambda: {"primary": workspace.resolve()},
    )
    monkeypatch.setattr("sase.file_references.format_with_prettier", lambda text: text)

    synchronous = prepare_prompt_archive(
        target=target,
        repo=target.sidecar_path,
        agent_name=_AGENT,
        global_agent=_GLOBAL_AGENT,
        primary_revision=primary_revision,
        commit_cwd=workspace,
        agent_artifacts_dir=artifacts_dir,
        prompt_content=None,
        plan_ref=None,
        prompt_name="parity",
        yyyymm="202608",
        git_runner=run_git,
    )
    synchronous_bytes = synchronous.prompt_path.read_bytes()
    synchronous.prompt_path.unlink()
    (target.sidecar_path / "prompts/202608/README.md").unlink(missing_ok=True)

    source_file.write_text("print('revision two')\n", encoding="utf-8")
    git(workspace, "add", "src/demo.py")
    git(workspace, "commit", "-m", "move workspace HEAD")
    moved_revision = git(workspace, "rev-parse", "HEAD").stdout.strip()
    assert moved_revision != primary_revision

    request = AgentPublicationOutboxItem(
        project_key="proj",
        project="Project",
        local_agent=_AGENT,
        global_agent=_GLOBAL_AGENT,
        primary_revision=primary_revision,
        local_hood="worker",
        commit_cwd=str(workspace),
        artifacts_dir=str(artifacts_dir),
        run_id="run-parity",
    )
    matching_run = SimpleNamespace(source_label=str(artifacts_dir))
    deferred = prepare_deferred_prompt_archive(
        target,
        request,
        run_git,
        prompt_runs={(_AGENT, primary_revision): matching_run},
    )

    assert deferred.wrote
    assert deferred.prepared_archive is not None
    deferred_bytes = deferred.prepared_archive.prompt_path.read_bytes()
    assert deferred_bytes == synchronous_bytes
    assert f"/blob/{primary_revision}/src/demo.py".encode() in deferred_bytes
    assert f"/blob/{moved_revision}/src/demo.py".encode() not in deferred_bytes
    assert (
        target.sidecar_path / sase_core_rs.artifact_object_relpath(digest)
    ).read_bytes() == pool_bytes


def test_acknowledged_deferred_archives_record_side_effects_once_per_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, _remote = setup_target(tmp_path)
    requests = tuple(
        AgentPublicationOutboxItem(
            project_key="proj",
            project="Project",
            local_agent=f"worker-{index}",
            global_agent=f"alice.athena.worker-{index}",
            primary_revision=f"{index + 1:040x}",
            local_hood=f"worker-{index}",
            run_id=f"run-{index}",
        )
        for index in range(2)
    )
    owner = _OWNER
    inventory = ProjectHoodInventory(owner, "proj", ())
    observed: list[tuple[str, str, str | None]] = []
    acknowledged: list[tuple[tuple[str, str], ...]] = []

    def restore(*_args: object, prepared_archives=None, **_kwargs: object):
        assert prepared_archives is not None
        for request in requests:
            prepared_archives[request.logical_key] = cast(
                PreparedPromptArchive,
                object(),
            )
        return {}

    def record_side_effects(
        _target: ProjectTarget,
        _prepared: PreparedPromptArchive,
        *,
        global_agent: str,
        publication_agent: str,
        run_id: str | None,
    ) -> None:
        observed.append((global_agent, publication_agent, run_id))

    monkeypatch.setattr(
        "sase.agents_sync.prompt_archive.deferred.restore_deferred_prompt_archives",
        restore,
    )
    monkeypatch.setattr(
        "sase.agents_sync.publication_completion.publication_request_fulfilled",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        archive_publish,
        "record_prompt_archive_side_effects",
        record_side_effects,
    )
    hooks = PublicationTransactionHooks(
        build_inventory=lambda *_args, **_kwargs: inventory,
        publish_hood=lambda *_args, **_kwargs: object(),
        update_publications=lambda *_args, **_kwargs: None,
        acknowledge_publications=lambda _project, keys: acknowledged.append(keys),
        configured_max_attempts=lambda: 3,
    )

    acked, errors = acknowledge_completed(
        target,
        owner,
        run_git,
        AgentIdentitySnapshot(owner),
        inventory,
        requests,
        hooks=hooks,
    )

    assert errors == ()
    assert acked == tuple(request.logical_key for request in requests)
    assert acknowledged == [list(acked)]
    assert observed == [
        (request.global_agent, request.local_agent, request.run_id)
        for request in requests
    ]


def test_deferred_acknowledgment_ignores_unrelated_referenced_by_drain_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agents_sync import referenced_by_publication

    target, _remote = setup_target(tmp_path)
    request = AgentPublicationOutboxItem(
        project_key="proj",
        project="Project",
        local_agent="worker",
        global_agent="alice.athena.worker",
        primary_revision="a" * 40,
        local_hood="worker",
        run_id="run-1",
    )
    owner = _OWNER
    inventory = ProjectHoodInventory(owner, "proj", ())
    archive = SimpleNamespace(
        rendered=SimpleNamespace(linked_records=()),
        referenced_by_requests=(),
    )
    acknowledged: list[tuple[tuple[str, str], ...]] = []
    updates: list[tuple[tuple[tuple[str, str], ...], dict[str, object]]] = []

    def restore(*_args: object, prepared_archives=None, **_kwargs: object):
        assert prepared_archives is not None
        prepared_archives[request.logical_key] = cast(
            PreparedPromptArchive,
            archive,
        )
        return {}

    monkeypatch.setattr(
        "sase.agents_sync.prompt_archive.deferred.restore_deferred_prompt_archives",
        restore,
    )
    monkeypatch.setattr(
        "sase.agents_sync.publication_completion.publication_request_fulfilled",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "sase.core.artifact_ref_files_index.upsert_ref_file_versions",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(archive_publish, "_record_prompt_cites", lambda *_a, **_k: None)

    def fail_unrelated_drain(*_args: object, **_kwargs: object):
        raise RuntimeError("unrelated Referenced By row failed")

    monkeypatch.setattr(
        referenced_by_publication,
        "drain_referenced_by_requests",
        fail_unrelated_drain,
    )
    hooks = PublicationTransactionHooks(
        build_inventory=lambda *_args, **_kwargs: inventory,
        publish_hood=lambda *_args, **_kwargs: object(),
        update_publications=lambda _project, keys, **kwargs: updates.append(
            (keys, kwargs)
        ),
        acknowledge_publications=lambda _project, keys: acknowledged.append(keys),
        configured_max_attempts=lambda: 3,
    )

    acked, errors = acknowledge_completed(
        target,
        owner,
        run_git,
        AgentIdentitySnapshot(owner),
        inventory,
        (request,),
        hooks=hooks,
    )

    assert acked == (request.logical_key,)
    assert errors == ()
    assert acknowledged == [list(acked)]
    assert updates == []


def test_deferred_acknowledgment_charges_its_own_cites_persist_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agents_sync import referenced_by_publication

    target, _remote = setup_target(tmp_path)
    request = AgentPublicationOutboxItem(
        project_key="proj",
        project="Project",
        local_agent="worker",
        global_agent="alice.athena.worker",
        primary_revision="a" * 40,
        local_hood="worker",
        run_id="run-1",
    )
    owner = _OWNER
    inventory = ProjectHoodInventory(owner, "proj", ())
    archive = SimpleNamespace(
        rendered=SimpleNamespace(linked_records=()),
        referenced_by_requests=(),
    )
    acknowledged: list[tuple[tuple[str, str], ...]] = []
    updates: list[tuple[tuple[tuple[str, str], ...], dict[str, object]]] = []

    def restore(*_args: object, prepared_archives=None, **_kwargs: object):
        assert prepared_archives is not None
        prepared_archives[request.logical_key] = cast(
            PreparedPromptArchive,
            archive,
        )
        return {}

    monkeypatch.setattr(
        "sase.agents_sync.prompt_archive.deferred.restore_deferred_prompt_archives",
        restore,
    )
    monkeypatch.setattr(
        "sase.agents_sync.publication_completion.publication_request_fulfilled",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "sase.core.artifact_ref_files_index.upsert_ref_file_versions",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        archive_publish,
        "_record_prompt_cites",
        lambda *_args, **_kwargs: "referenced-by cites persist failed: disk full",
    )
    monkeypatch.setattr(
        referenced_by_publication,
        "drain_referenced_by_requests",
        lambda *_args, **_kwargs: pytest.fail(
            "deferred acknowledgment must not drain unrelated requests"
        ),
    )
    hooks = PublicationTransactionHooks(
        build_inventory=lambda *_args, **_kwargs: inventory,
        publish_hood=lambda *_args, **_kwargs: object(),
        update_publications=lambda _project, keys, **kwargs: updates.append(
            (keys, kwargs)
        ),
        acknowledge_publications=lambda _project, keys: acknowledged.append(keys),
        configured_max_attempts=lambda: 3,
    )

    acked, errors = acknowledge_completed(
        target,
        owner,
        run_git,
        AgentIdentitySnapshot(owner),
        inventory,
        (request,),
        hooks=hooks,
    )

    assert acked == ()
    assert acknowledged == []
    assert errors == ("referenced-by cites persist failed: disk full",)
    assert updates == [
        (
            (request.logical_key,),
            {
                "error": "referenced-by cites persist failed: disk full",
                "increment_attempts": True,
                "quarantine_threshold": 3,
            },
        )
    ]
