"""Parked outbox rows: schema 8, due checks, clearing, and doctor."""

from __future__ import annotations

import dataclasses
import json
import time

from sase.agents_sync.publication_job import _publication_is_ready
from sase.agents_sync.publication_outbox import (
    PUBLICATION_OUTBOX_SCHEMA_VERSION,
    AgentPublicationOutboxItem,
    enqueue_agent_publication,
    list_agent_publications,
    park_agent_publications,
    publication_is_parked_due,
    update_agent_publications,
)
from tests.agents_sync.test_publication_outbox._helpers import make_outbox_item


def _parked_item(**overrides) -> AgentPublicationOutboxItem:
    now = time.time()
    base = dataclasses.replace(
        make_outbox_item(),
        parked_reason="run withheld by publication protection",
        parked_since=now - 10,
        parked_checked_at=now - 10,
        parked_rules_version=2,
    )
    if overrides:
        base = dataclasses.replace(base, **overrides)
    return base


def test_schema_8_parked_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    path = tmp_path / "projects" / "proj" / "agents-publication-outbox.json"
    path.parent.mkdir(parents=True)
    item = _parked_item()
    path.write_text(
        json.dumps({"schema_version": 8, "items": [item.to_json_dict()]}),
        encoding="utf-8",
    )

    [loaded] = list_agent_publications("proj")
    assert loaded.parked_reason == item.parked_reason
    assert loaded.parked_since == item.parked_since
    assert loaded.parked_checked_at == item.parked_checked_at
    assert loaded.parked_rules_version == 2
    assert loaded.is_parked

    update_agent_publications("proj", (loaded.logical_key,), error=None)
    rewritten = json.loads(path.read_text(encoding="utf-8"))
    assert rewritten["schema_version"] == PUBLICATION_OUTBOX_SCHEMA_VERSION
    assert rewritten["items"][0]["parked_reason"] == item.parked_reason


def test_schema_7_backlog_reads_without_parked_fields(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    path = tmp_path / "projects" / "proj" / "agents-publication-outbox.json"
    path.parent.mkdir(parents=True)
    row = make_outbox_item().to_json_dict()
    for field in (
        "parked_reason",
        "parked_since",
        "parked_checked_at",
        "parked_rules_version",
    ):
        row.pop(field, None)
    path.write_text(
        json.dumps({"schema_version": 7, "items": [row]}),
        encoding="utf-8",
    )

    [loaded] = list_agent_publications("proj")
    assert loaded.parked_reason is None
    assert loaded.parked_since is None
    assert loaded.parked_checked_at is None
    assert loaded.parked_rules_version is None
    assert not loaded.is_parked


def test_park_sets_fields_and_preserves_parked_since(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    item = make_outbox_item()
    enqueue_agent_publication(item)
    before = time.time()
    park_agent_publications(
        "proj",
        {item.logical_key: "run withheld by publication protection"},
        now=before,
        rules_version=2,
    )
    [parked] = list_agent_publications("proj")
    assert parked.attempts == 0
    assert parked.last_error == "run withheld by publication protection"
    assert parked.parked_reason == "run withheld by publication protection"
    assert parked.parked_since == before
    assert parked.parked_checked_at == before
    assert parked.parked_rules_version == 2

    later = before + 100
    park_agent_publications(
        "proj",
        {item.logical_key: "run withheld by publication protection"},
        now=later,
        rules_version=2,
    )
    [reparked] = list_agent_publications("proj")
    assert reparked.parked_since == before
    assert reparked.parked_checked_at == later


def test_charged_update_clears_parked_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    enqueue_agent_publication(make_outbox_item())
    [item] = list_agent_publications("proj")
    park_agent_publications(
        "proj", {item.logical_key: "run withheld by publication protection"}
    )
    [parked] = list_agent_publications("proj")
    assert parked.is_parked

    update_agent_publications(
        "proj",
        (parked.logical_key,),
        error="hood failed",
        increment_attempts=True,
        quarantine_threshold=3,
    )
    [cleared] = list_agent_publications("proj")
    assert cleared.parked_reason is None
    assert cleared.parked_since is None
    assert cleared.parked_checked_at is None
    assert cleared.parked_rules_version is None


def test_enqueue_merging_into_parked_key_clears_park(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    enqueue_agent_publication(make_outbox_item())
    [item] = list_agent_publications("proj")
    park_agent_publications(
        "proj", {item.logical_key: "run withheld by publication protection"}
    )
    assert list_agent_publications("proj")[0].is_parked

    enqueue_agent_publication(make_outbox_item())
    [refreshed] = list_agent_publications("proj")
    assert not refreshed.is_parked
    assert refreshed.parked_reason is None


def test_parked_due_checks_interval_rules_and_missing_metadata() -> None:
    now = 10_000.0
    fresh = _parked_item(parked_checked_at=now - 10, parked_rules_version=2)
    assert not publication_is_parked_due(
        fresh, now=now, current_rules_version=2, recheck_interval_seconds=3600.0
    )
    expired = _parked_item(parked_checked_at=now - 3600.0, parked_rules_version=2)
    assert publication_is_parked_due(
        expired, now=now, current_rules_version=2, recheck_interval_seconds=3600.0
    )
    changed_rules = _parked_item(parked_checked_at=now - 10, parked_rules_version=1)
    assert publication_is_parked_due(
        changed_rules,
        now=now,
        current_rules_version=2,
        recheck_interval_seconds=3600.0,
    )
    future = _parked_item(parked_checked_at=now + 100, parked_rules_version=2)
    assert publication_is_parked_due(
        future, now=now, current_rules_version=2, recheck_interval_seconds=3600.0
    )
    missing = _parked_item(parked_checked_at=None, parked_rules_version=None)
    assert publication_is_parked_due(
        missing, now=now, current_rules_version=2, recheck_interval_seconds=3600.0
    )
    assert publication_is_parked_due(make_outbox_item(), now=now)


def test_publication_is_ready_excludes_parked_until_due() -> None:
    now = time.time()
    parked = _parked_item(parked_checked_at=now - 10, parked_rules_version=2)
    assert not _publication_is_ready(parked, now=now)
    due = _parked_item(parked_checked_at=now - 7200, parked_rules_version=2)
    assert _publication_is_ready(due, now=now)


def test_parked_only_project_does_not_ring_until_due(tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace
    from pathlib import Path

    from sase.agents_sync import publication_job
    from tests._conftest_environment import redirect_sase_home

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    target = SimpleNamespace(
        project_key="proj",
        project="Project",
        primary_checkout=tmp_path / "primary",
        primary_roots=(tmp_path / "primary",),
        sidecar_path=tmp_path / "agents",
        remote_url="https://example.invalid/agents.git",
    )
    monkeypatch.setattr(
        publication_job,
        "list_project_records",
        lambda *_args, **_kwargs: [
            SimpleNamespace(
                project_name="proj",
                workspace_dir=str(tmp_path / "primary"),
                is_project=True,
            )
        ],
    )
    monkeypatch.setattr(
        publication_job,
        "resolve_sync_targets",
        lambda _keys: SimpleNamespace(targets=(target,), outcomes=()),
    )
    now = time.time()
    parked = _parked_item(parked_checked_at=now - 10, parked_rules_version=2)
    monkeypatch.setattr(
        publication_job, "active_agent_publications", lambda _key: (parked,)
    )
    monkeypatch.setattr(
        publication_job,
        "list_referenced_by_requests",
        lambda *_args, **_kwargs: (),
    )
    bells: list[str] = []
    monkeypatch.setattr(
        publication_job,
        "ring_publication_doorbell",
        lambda key, _hint=None: bells.append(key),
    )
    # Import here so the monkeypatched drain is used by _drain_project.
    from sase.agents_sync import _commit_publication_queue as publication_queue

    monkeypatch.setattr(
        publication_queue,
        "drain_selected_agent_publications",
        lambda *_args, **_kwargs: SimpleNamespace(
            drained=0,
            error=None,
            skip_reason=None,
            failure_scope=None,
            parked_keys=(parked.logical_key,),
            newly_parked_keys=(),
        ),
    )

    summary = publication_job.run_publication_job(work_budget_seconds=10)

    assert bells == []
    assert summary.project_stats["proj"]["parked_count"] == 1
    assert summary.parked == 1
    assert summary.errors == 0


def test_revive_paths_clear_parked_state(tmp_path, monkeypatch) -> None:
    from sase.agents_sync.publication_outbox import (
        clear_quarantined_agent_publications,
        revive_agent_publications,
    )

    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    enqueue_agent_publication(make_outbox_item())
    [item] = list_agent_publications("proj")

    # Quarantine first, then park the quarantined row; an explicit clear must
    # release both states.
    update_agent_publications(
        "proj",
        (item.logical_key,),
        error="hood failed",
        increment_attempts=True,
        quarantine_threshold=1,
    )
    [quarantined] = list_agent_publications("proj", include_quarantined=True)
    assert quarantined.quarantined
    assert not quarantined.is_parked
    park_agent_publications(
        "proj", {item.logical_key: "run withheld by publication protection"}
    )
    [parked_quarantined] = list_agent_publications("proj", include_quarantined=True)
    assert parked_quarantined.quarantined
    assert parked_quarantined.is_parked
    clear_quarantined_agent_publications("proj")
    [cleared] = list_agent_publications("proj")
    assert not cleared.is_parked
    assert not cleared.quarantined

    # Revive clears parked for retired rows.
    update_agent_publications(
        "proj",
        (item.logical_key,),
        error="terminal failure",
        increment_attempts=True,
        quarantine_threshold=1,
        terminal_reason="terminal failure",
    )
    update_agent_publications(
        "proj",
        (item.logical_key,),
        error="terminal failure",
        increment_attempts=True,
        quarantine_threshold=1,
        terminal_reason="terminal failure",
    )
    park_agent_publications(
        "proj", {item.logical_key: "run withheld by publication protection"}
    )
    revive_agent_publications("proj", retry_retired=True, retry_quarantined=True)
    [revived] = list_agent_publications("proj")
    assert not revived.is_parked


def test_doctor_lists_parked_rows_as_warn(tmp_path, monkeypatch) -> None:
    from pathlib import Path

    from sase.core.project_lifecycle_wire import (
        PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        ProjectRecordWire,
    )
    from sase.doctor._agent_publication import problem_for_item

    project_dir = tmp_path / ".sase" / "projects" / "proj"
    record = ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name="proj",
        project_dir=str(project_dir),
        project_file=str(project_dir / "proj.sase"),
        archive_file=None,
        workspace_dir=str(tmp_path / "proj"),
        state="enabled",
        state_explicit=False,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
    )
    item = _parked_item()
    problem = problem_for_item(
        record,
        Path("/tmp/outbox.json"),
        item,
        now=time.time(),
        stalled_attempts=3,
        stalled_age_seconds=24 * 60 * 60,
    )
    assert problem is not None
    assert problem.parked
    assert not problem.stalled
    assert "parked: run withheld by publication protection" in problem.reasons[0]
