"""Tests for agent publication doctor reporting of agents-sidecar state."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.agents_sync.models import ProjectTarget, TargetSelection
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.doctor.checks_agent_publication_outbox import check_agent_publication_outbox
from tests.doctor._checks_agent_publication_helpers import (
    doctor_context,
    make_record,
    write_outbox,
)


def test_agent_publication_doctor_warns_on_unreadable_local_owner_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = make_record(tmp_path)
    sidecar = tmp_path / "agents"
    sidecar.mkdir()
    manifest = sidecar / "users" / "alice" / "machines" / "athena" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}\n", encoding="utf-8")
    target = ProjectTarget(
        "alpha",
        "Alpha",
        tmp_path / "primary",
        (tmp_path / "primary",),
        sidecar,
        "git@example.test:alpha--agents.git",
    )
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication_outbox.list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication_sidecar.resolve_sync_targets",
        lambda *_args, **_kwargs: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication_sidecar.require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )
    write_outbox(tmp_path / ".sase", "alpha", [])

    check = check_agent_publication_outbox(doctor_context(tmp_path), now=200.0)

    assert check.status == "WARN"
    assert "unreadable owner manifest" in check.summary
    assert "sase agent sync --retry-quarantined" in check.summary
    assert str(manifest) in check.details[0]
    assert "missing required keys" in check.details[0]
    assert check.data["owner_manifest_problem_count"] == 1
    assert check.data["owner_manifest_problems"][0]["manifest_path"] == str(manifest)


def test_agent_publication_doctor_accepts_healthy_local_owner_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = make_record(tmp_path)
    sidecar = tmp_path / "agents"
    sidecar.mkdir()
    target = ProjectTarget(
        "alpha",
        "Alpha",
        tmp_path / "primary",
        (tmp_path / "primary",),
        sidecar,
        "git@example.test:alpha--agents.git",
    )
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication_outbox.list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication_sidecar.resolve_sync_targets",
        lambda *_args, **_kwargs: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication_sidecar.require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )
    write_outbox(tmp_path / ".sase", "alpha", [])

    check = check_agent_publication_outbox(doctor_context(tmp_path), now=200.0)

    assert check.status == "OK"
    assert check.data["owner_manifest_problem_count"] == 0
    assert check.data["owner_manifest_problems"] == ()


def test_agent_publication_doctor_warns_for_parked_diverged_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agents_sync import publication_diverged_replay

    record = make_record(tmp_path)
    sidecar = tmp_path / "agents"
    target = ProjectTarget(
        "alpha",
        "Alpha",
        tmp_path / "primary",
        (tmp_path / "primary",),
        sidecar,
        "git@example.test:alpha--agents.git",
    )
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication_outbox.list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication_sidecar.resolve_sync_targets",
        lambda *_args, **_kwargs: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication_sidecar.require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication_outbox.owner_manifest_problems",
        lambda *_args, **_kwargs: ((), ()),
    )
    monkeypatch.setattr(
        publication_diverged_replay,
        "sase_projects_dir",
        lambda: tmp_path / ".sase" / "projects",
    )
    write_outbox(tmp_path / ".sase", "alpha", [])
    marker = publication_diverged_replay._write_diverged_replay_marker(
        "alpha",
        head="a" * 40,
        upstream="b" * 40,
        paths=("users/alice/README.md",),
        now=100.0,
    )

    check = check_agent_publication_outbox(doctor_context(tmp_path), now=200.0)

    assert check.status == "WARN"
    assert check.data["sidecar_states"][0]["diverged_replay"] is True
    assert check.data["sidecar_states"][0]["diverged_replay_head"] == marker.head
    assert "parked diverged replay" in check.summary
    assert any("users/alice/README.md" in detail for detail in check.details)
    assert any("Stale-replay recovery" in step for step in check.next_steps)
