"""Workspace-head parity and deferred acknowledgment tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import sase_core_rs

from sase.agents_sync import git_sync
from sase.agents_sync.git import run_git
from sase.agents_sync.inventory import ProjectHoodInventory
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.prompt_archive import publish as archive_publish
from sase.agents_sync.prompt_archive.deferred import prepare_deferred_prompt_archive
from sase.agents_sync.prompt_archive.preparation import PreparedPromptArchive
from sase.agents_sync.prompt_archive.publish import prepare_prompt_archive
from sase.agents_sync.publication_outbox import AgentPublicationOutboxItem
from sase.agents_sync._commit_publication_transaction_steps import (
    acknowledge_completed,
)
from sase.agents_sync._commit_publication_transaction_types import (
    PublicationTransactionHooks,
)
from sase.core.agent_identity_facade import AgentIdentitySnapshot
from tests.agents_sync.commit_publication_fixtures import (
    fulfilled_completion,
    git,
    setup_target,
)
from tests.agents_sync.test_deferred_prompt_archive._helpers import (
    GLOBAL_AGENT,
    OWNER,
    HostedLinks,
)
from tests.agents_sync._prompt_archive_helpers import make_record, write_manifest


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
        archive_publish, "_hosted_resolver", lambda *_args: HostedLinks()
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
        agent_name="worker",
        global_agent=GLOBAL_AGENT,
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
        local_agent="worker",
        global_agent=GLOBAL_AGENT,
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
        prompt_runs={("worker", primary_revision): matching_run},
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
    owner = OWNER
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
        "sase.agents_sync.publication_completion.publication_request_completion",
        fulfilled_completion,
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
    owner = OWNER
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
        "sase.agents_sync.publication_completion.publication_request_completion",
        fulfilled_completion,
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
    owner = OWNER
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
        "sase.agents_sync.publication_completion.publication_request_completion",
        fulfilled_completion,
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
