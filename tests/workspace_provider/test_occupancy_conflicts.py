"""Tests for RUNNING-field / occupant-record occupancy conflict detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.logs.workspace_claim_ledger import record_running_field_mutation
from sase.running_field import WorkspaceClaim
from sase.workspace_provider.occupancy_conflicts import (
    CODE_DUPLICATE_CLAIM,
    CODE_OCCUPANT_PID_MISMATCH,
    CODE_ORPHAN_OCCUPANT,
    detect_occupancy_conflicts,
)
from sase.workspace_provider.occupant import new_occupant_record, write_occupant_record
from sase.workspace_provider.registry import (
    load_or_init_registry,
    record_workspace,
    save_registry,
)
from sase.workspace_provider.store import WorkspaceStore


def _project(tmp_path: Path, name: str) -> ProjectRecordWire:
    primary = tmp_path / "primary" / name
    primary.mkdir(parents=True)
    project_dir = tmp_path / "projects" / name
    project_dir.mkdir(parents=True)
    project_file = project_dir / f"{name}.sase"
    project_file.write_text(name, encoding="utf-8")
    return ProjectRecordWire(
        schema_version=3,
        project_name=name,
        project_dir=str(project_dir),
        project_file=str(project_file),
        archive_file=None,
        workspace_dir=str(primary),
        state="enabled",
        state_explicit=False,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        display_name=name,
        is_project=True,
        vcs_kind="git",
    )


def _config(tmp_path: Path, primary: str) -> dict[str, object]:
    return {
        "workspace": {
            "root": str(tmp_path / "managed"),
            "project_key": Path(primary).name,
            "cleanup_ttl_days": 1,
        }
    }


def _write_claims(project_file: str, claims: list[WorkspaceClaim]) -> None:
    lines = ["# Test Project\n", "NAME: Test Feature\n", "STATUS: Ready\n"]
    if claims:
        lines.insert(1, "RUNNING:\n")
        for claim in claims:
            lines.insert(-2, claim.to_line() + "\n")
    Path(project_file).write_text("".join(lines), encoding="utf-8")


def _register_checkout(tmp_path: Path, project: ProjectRecordWire, num: int) -> Path:
    primary = project.workspace_dir or ""
    store = WorkspaceStore(primary, config=_config(tmp_path, primary), env={})
    registry = load_or_init_registry(store)
    save_registry(store, registry)
    resolved = store.resolve(num)
    checkout = Path(resolved.checkout_dir)
    checkout.mkdir(parents=True)
    record_workspace(store, resolved, role="claim")
    return checkout


def _patch_projects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    projects: list[ProjectRecordWire],
) -> None:
    monkeypatch.setattr(
        "sase.workspace_provider.occupancy_conflicts.list_project_records",
        lambda *_args, **_kwargs: projects,
    )
    monkeypatch.setattr(
        "sase.workspace_provider.occupancy_conflicts.resolution_config",
        lambda primary, _config: _config_for(tmp_path, str(primary)),
    )


def _config_for(tmp_path: Path, primary: str) -> dict[str, object]:
    return _config(tmp_path, primary)


def test_detects_duplicate_running_claim_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path, "alpha")
    _write_claims(
        project.project_file,
        [
            WorkspaceClaim(10, "ace(run)-a", "agent-a", pid=111),
            WorkspaceClaim(10, "ace(run)-b", "agent-b", pid=222),
        ],
    )
    _patch_projects(monkeypatch, tmp_path, [project])

    conflicts = detect_occupancy_conflicts(tmp_path / "projects")

    assert len(conflicts) == 1
    assert conflicts[0].code == CODE_DUPLICATE_CLAIM
    assert conflicts[0].workspace_num == 10
    assert conflicts[0].claim_pids == (111, 222)
    assert "more than one RUNNING row" in conflicts[0].message


def test_detects_live_claim_vs_different_live_occupant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path, "alpha")
    claim_pid = 111
    occupant_pid = 222
    _write_claims(
        project.project_file,
        [WorkspaceClaim(10, "ace(run)-a", "agent-a", pid=claim_pid)],
    )
    checkout = _register_checkout(tmp_path, project, 10)
    write_occupant_record(
        str(checkout),
        new_occupant_record(
            pid=occupant_pid,
            workflow="ace(run)-b",
            project="alpha",
            workspace_num=10,
        ),
    )
    _patch_projects(monkeypatch, tmp_path, [project])

    conflicts = detect_occupancy_conflicts(
        tmp_path / "projects",
        process_running=lambda pid: pid in {claim_pid, occupant_pid},
    )

    assert len(conflicts) == 1
    assert conflicts[0].code == CODE_OCCUPANT_PID_MISMATCH
    assert conflicts[0].occupant_pid == occupant_pid
    assert conflicts[0].claim_pids == (claim_pid,)
    assert "different live PID" in conflicts[0].message


def test_detects_orphan_occupant_without_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path, "alpha")
    _write_claims(project.project_file, [])
    checkout = _register_checkout(tmp_path, project, 10)
    write_occupant_record(
        str(checkout),
        new_occupant_record(
            pid=333,
            workflow="ace(run)-orphan",
            project="alpha",
            workspace_num=10,
        ),
    )
    _patch_projects(monkeypatch, tmp_path, [project])

    conflicts = detect_occupancy_conflicts(tmp_path / "projects")

    assert len(conflicts) == 1
    assert conflicts[0].code == CODE_ORPHAN_OCCUPANT
    assert conflicts[0].occupant_pid == 333
    assert "no corresponding RUNNING claim" in conflicts[0].message


def test_matching_live_occupant_is_not_a_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path, "alpha")
    pid = 444
    _write_claims(
        project.project_file,
        [WorkspaceClaim(10, "ace(run)-a", "agent-a", pid=pid)],
    )
    checkout = _register_checkout(tmp_path, project, 10)
    write_occupant_record(
        str(checkout),
        new_occupant_record(
            pid=pid,
            workflow="ace(run)-a",
            project="alpha",
            workspace_num=10,
        ),
    )
    _patch_projects(monkeypatch, tmp_path, [project])

    conflicts = detect_occupancy_conflicts(
        tmp_path / "projects",
        process_running=lambda candidate: candidate == pid,
    )

    assert conflicts == ()


def test_dead_occupant_pid_is_not_a_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path, "alpha")
    live_pid = 555
    dead_pid = 666
    _write_claims(
        project.project_file,
        [WorkspaceClaim(10, "ace(run)-a", "agent-a", pid=live_pid)],
    )
    checkout = _register_checkout(tmp_path, project, 10)
    write_occupant_record(
        str(checkout),
        new_occupant_record(
            pid=dead_pid,
            workflow="ace(run)-stale",
            project="alpha",
            workspace_num=10,
        ),
    )
    _patch_projects(monkeypatch, tmp_path, [project])

    conflicts = detect_occupancy_conflicts(
        tmp_path / "projects",
        process_running=lambda pid: pid == live_pid,
    )

    assert conflicts == ()


def test_annotates_conflict_with_last_ledger_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path, "alpha")
    _write_claims(
        project.project_file,
        [
            WorkspaceClaim(10, "ace(run)-a", "agent-a", pid=111),
            WorkspaceClaim(10, "ace(run)-b", "agent-b", pid=222),
        ],
    )
    _patch_projects(monkeypatch, tmp_path, [project])
    ledger_file = str(tmp_path / "workspace_claims.jsonl")
    monkeypatch.setattr("sase.logs.workspace_claim_ledger.LEDGER_FILE", ledger_file)
    record_running_field_mutation(
        operation="claim_next_axe",
        project_file=project.project_file,
        workspace_num=10,
        success=True,
        before_content="",
        caller_tag="deferred-claim",
    )

    conflicts = detect_occupancy_conflicts(
        tmp_path / "projects", ledger_file=ledger_file
    )

    assert len(conflicts) == 1
    assert conflicts[0].last_caller_tag == "deferred-claim"
    assert conflicts[0].last_mutated_at
    assert "Last mutated at" in conflicts[0].message
    assert "deferred-claim" in conflicts[0].message
