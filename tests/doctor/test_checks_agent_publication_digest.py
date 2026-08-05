"""Tests for the agents-sidecar hood-snapshot digest-drift doctor check."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.agents_sync.inventory import InventoryRun, ProjectHoodInventory
from sase.agents_sync.models import ProjectTarget, TargetSelection
from sase.agents_sync.publication import publish_agent_hood
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.doctor.checks_agent_publication_digest import (
    _check_agent_publication_digest,
)
from sase.doctor.runner import DoctorContext


def _context(tmp_path: Path) -> DoctorContext:
    return DoctorContext(
        cwd=tmp_path,
        project=None,
        sase_home=tmp_path / ".sase",
    )


def _record(tmp_path: Path, *, name: str = "alpha") -> ProjectRecordWire:
    project_dir = tmp_path / ".sase" / "projects" / name
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name=name,
        project_dir=str(project_dir),
        project_file=str(project_dir / f"{name}.sase"),
        archive_file=None,
        workspace_dir=str(tmp_path / name),
        state="enabled",
        state_explicit=False,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
    )


def _published_target(tmp_path: Path) -> tuple[ProjectTarget, Path, AgentOwnerIdentity]:
    owner = AgentOwnerIdentity("alice", "athena")
    primary = tmp_path / "primary"
    primary.mkdir()
    sidecar = tmp_path / "agents"
    sidecar.mkdir()
    target = ProjectTarget(
        "alpha",
        "Alpha",
        primary,
        (primary.resolve(),),
        sidecar,
        "git@example.test:alpha--agents.git",
    )
    run = InventoryRun(
        "run-01",
        "foo",
        f"{owner.username}.{owner.machine_name}.foo",
        "completed",
        "2026-07-23T12:00:00+00:00",
        "2026-07-23T12:01:00+00:00",
        None,
        (("model", "gpt"),),
        (),
        b"prompt for foo\n",
        b"chat for foo\n",
        None,
        None,
        (),
        "2026072312001",
    )
    publish_agent_hood(
        target,
        sidecar,
        "foo",
        identity=AgentIdentitySnapshot(owner),
        inventory=ProjectHoodInventory(owner, "alpha", (run,)),
    )
    return target, sidecar, owner


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    record: ProjectRecordWire,
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication_digest.list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication_digest.resolve_sync_targets",
        lambda *_args, **_kwargs: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication_digest.require_agent_owner_identity",
        lambda: owner,
    )


def test_digest_check_warns_on_drifted_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record(tmp_path)
    target, sidecar, owner = _published_target(tmp_path)
    _patch(monkeypatch, record, target, owner)
    chat_path = sidecar / "agents" / "alice.athena.foo" / "chat.md"
    chat_path.write_bytes(b"rewritten out of band\n")

    check = _check_agent_publication_digest(_context(tmp_path))

    assert check.status == "WARN"
    assert "drifted file" in check.summary
    assert "sase agent sync --repair-digests" in check.summary
    assert check.data["problems"][0]["project_key"] == "alpha"
    assert any("chat.md" in detail for detail in check.details)


def test_digest_check_is_silent_on_healthy_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record(tmp_path)
    target, _sidecar, owner = _published_target(tmp_path)
    _patch(monkeypatch, record, target, owner)
    assert _sidecar.is_dir()

    check = _check_agent_publication_digest(_context(tmp_path))

    assert check.status == "OK"
    assert check.data["problems"] == ()
