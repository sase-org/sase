"""Fenced prompt cites become link-outbox events, including the queued backlog."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path

import pytest

from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.referenced_by_events import (
    TRUSTED_CITES_PRODUCER,
    cites_outbox_identity,
    convert_fenced_referenced_by_backlog,
    emit_referenced_by_cites_events,
)
from sase.agents_sync.referenced_by_outbox import (
    ReferencedByOutboxItem,
    enqueue_referenced_by_request,
    list_referenced_by_requests,
)
from sase.sdd.artifact_link_event_publisher import artifact_link_machine_run_id
from sase.sdd.artifact_link_outbox import (
    drain_artifact_link_outbox,
    read_artifact_link_outbox_entries,
)
from sase.sdd.artifact_link_release_evidence import (
    record_artifact_link_release_evidence,
)
from sase.sdd.artifact_link_store import ArtifactLinkStore
from sase.sdd.referenced_by_refresh import refresh_referenced_by
from sase.sdd.store import SddStore
from tests._conftest_environment import redirect_sase_home
from tests.main.artifact_link_outbox_helpers import _init_plans_repo
from tests.sdd._artifact_link_store_helpers import (
    allow_machine_sidecar_writes,
    write_imported_cutover_marker,
)


def _target(tmp_path: Path) -> ProjectTarget:
    primary = tmp_path / "primary"
    primary.mkdir(exist_ok=True)
    return ProjectTarget(
        project_key="proj",
        project="Project",
        primary_checkout=primary,
        primary_roots=(primary,),
        sidecar_path=primary / "sase" / "repos" / "agents",
        remote_url="https://example.test/proj--agents.git",
    )


def _item() -> ReferencedByOutboxItem:
    return ReferencedByOutboxItem(
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
        uses=2,
        published_date="2026-08-12",
        relation="cites",
        origin="prompt_ref",
        description="prompt reference @plan:202608/example.md",
    )


def test_cites_outbox_identity_uses_run_when_present() -> None:
    assert cites_outbox_identity(agent_name="worker", run_id="  run-1 ") == (
        "worker",
        "run-1",
    )
    agent, run_id = cites_outbox_identity(agent_name="worker", run_id=None)
    assert agent == TRUSTED_CITES_PRODUCER
    assert run_id == artifact_link_machine_run_id()


def test_fenced_backlog_is_replayed_as_migrated_cites_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    item = enqueue_referenced_by_request(_item())
    target = _target(tmp_path)

    diagnostics = convert_fenced_referenced_by_backlog(target)

    assert diagnostics == ()
    assert list_referenced_by_requests("proj", include_quarantined=True) == ()
    [entry] = read_artifact_link_outbox_entries("proj")
    assert entry.agent_name == TRUSTED_CITES_PRODUCER
    assert entry.run_id == artifact_link_machine_run_id()
    assert entry.event is not None
    assert entry.event["origin"] == "migrated"
    assert entry.event["kind"]["type"] == "edge-put"
    assert entry.event["kind"]["edge"]["source_ref"] == f"agent:{item.global_agent}"
    assert entry.event["kind"]["edge"]["relation"] == "cites"
    assert entry.event["kind"]["edge"]["target_ref"] == item.canonical_ref

    replay = convert_fenced_referenced_by_backlog(target)
    assert replay == ()
    assert len(read_artifact_link_outbox_entries("proj")) == 1


def test_commit_cites_events_drain_for_publication_agent_and_survive_stale_drop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    repo = tmp_path / "plans"
    _init_plans_repo(repo)
    example = repo / "202608" / "example.md"
    example.parent.mkdir(parents=True, exist_ok=True)
    example.write_text("# Example\n\nBody\n", encoding="utf-8")
    store = ArtifactLinkStore(
        project_key="proj",
        sidecar_roots={"plan": repo},
    )
    write_imported_cutover_marker(store)
    item = _item()
    errors = emit_referenced_by_cites_events(
        (item,),
        project_key="proj",
        agent_name="alice.athena.worker",
        run_id="run-1",
    )
    assert errors == ()
    record_artifact_link_release_evidence(
        project_key="proj",
        run_id="run-1",
        agent_id="alice.athena.worker",
        qualifying_repo_ids=(str(repo),),
    )
    monkeypatch.setattr(
        "sase.sdd._artifact_link_outbox_drain._terminal_agent_finished_times",
        lambda _entries: {"alice.athena.worker": 0.0},
    )
    monkeypatch.setattr(
        "sase.sdd._artifact_link_outbox_drain._terminal_cutoff",
        lambda: 10.0,
    )

    report = drain_artifact_link_outbox(
        store=store,
        agent_name="alice.athena.worker",
        drop_stale_terminal=True,
        push_after_commit=False,
    )

    assert report.drained == 1
    assert report.dropped == 0
    assert read_artifact_link_outbox_entries("proj") == ()
    rows = store.load_artifact_rows("plan:202608/example.md")
    cites = [row for row in rows if row.get("relation") == "cites"]
    assert cites
    assert cites[0]["source_ref"] == "agent:alice.athena.worker"
    assert cites[0]["origin"] == "prompt_ref"
    assert cites[0]["uses"] == 2


def test_event_projection_matches_unfenced_legacy_referenced_by_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)

    @contextmanager
    def _acquired_lock(*_args: object, **_kwargs: object):
        yield True

    monkeypatch.setattr(
        "sase.sdd._git_contention.store_git_write_lock",
        _acquired_lock,
    )
    monkeypatch.setattr(
        "sase.sdd.referenced_by_refresh._pull_rebase_if_remote",
        lambda _repo_root: None,
    )
    monkeypatch.setattr(
        "sase.file_references.format_markdown_files_with_prettier",
        lambda _paths: True,
    )
    monkeypatch.setattr("sase.sdd.files.commit_sdd_store_files", lambda *_a, **_k: True)

    unfenced_root = tmp_path / "unfenced"
    unfenced_root.mkdir()
    unfenced_store = SddStore("sidecar_repos", unfenced_root, unfenced_root)
    document = unfenced_root / "202608" / "example.md"
    document.parent.mkdir(parents=True)
    document.write_text("# Example\n\nBody\n", encoding="utf-8")
    request = _item()
    written = refresh_referenced_by(
        unfenced_store,
        role="plans",
        requests=(request,),
        write=True,
    )
    assert written.ok
    legacy_index = unfenced_root / "links/202608/example.md.json"
    legacy_row = json.loads(legacy_index.read_text(encoding="utf-8"))["rows"][0]

    fenced_root = tmp_path / "fenced"
    _init_plans_repo(fenced_root)
    example = fenced_root / "202608" / "example.md"
    example.parent.mkdir(parents=True, exist_ok=True)
    example.write_text("# Example\n\nBody\n", encoding="utf-8")
    fenced_store = ArtifactLinkStore(
        project_key="proj",
        sidecar_roots={"plan": fenced_root},
    )
    write_imported_cutover_marker(fenced_store)
    errors = emit_referenced_by_cites_events(
        (request,),
        project_key="proj",
        agent_name=TRUSTED_CITES_PRODUCER,
        run_id=artifact_link_machine_run_id(),
    )
    assert errors == ()
    report = drain_artifact_link_outbox(
        store=fenced_store,
        agent_name=TRUSTED_CITES_PRODUCER,
        drop_stale_terminal=True,
        push_after_commit=False,
    )
    assert report.drained == 1
    event_rows = [
        row
        for row in fenced_store.load_artifact_rows("plan:202608/example.md")
        if row.get("relation") == "cites"
    ]
    assert len(event_rows) == 1
    event_row = event_rows[0]
    for key in ("source_ref", "relation", "target_ref", "origin", "uses", "created_by"):
        assert event_row[key] == legacy_row[key]
    assert not list(fenced_root.glob("links/**/*.json"))
