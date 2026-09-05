"""Claim and ownership tests for the durable agent-name registry."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.names import (
    NameCollisionError,
    claim_registered_name,
    delete_registered_name,
    get_reserved_agent_names,
    load_name_registry,
    lookup_registered_name,
    rebuild_name_registry,
)
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
)

from tests._agent_names_fixtures import (
    make_agent as _make_agent,
    make_sharded_agent as _make_sharded_agent,
)


def _configure_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    identity = AgentIdentitySnapshot(
        AgentOwnerIdentity("alice", "athena"),
        ("athena", "zeus"),
    )
    monkeypatch.setattr(
        AgentIdentitySnapshot,
        "current",
        classmethod(lambda _cls: identity),
    )


def test_configured_claim_uses_bare_local_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_machine(monkeypatch)
    artifact_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/run1"
    artifact_dir.mkdir(parents=True)

    with patch.object(Path, "home", return_value=tmp_path):
        claim_registered_name("foo", artifact_dir)
        assert get_reserved_agent_names() == {"foo", "zeus"}
        assert lookup_registered_name("foo") is not None
        assert lookup_registered_name("athena.foo") is not None


def test_legacy_and_qualified_claims_collide_in_both_directions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_machine(monkeypatch)
    first = tmp_path / ".sase/projects/proj/artifacts/ace-run/run1"
    second = tmp_path / ".sase/projects/proj/artifacts/ace-run/run2"
    first.mkdir(parents=True)
    second.mkdir(parents=True)

    with patch.object(Path, "home", return_value=tmp_path):
        _make_agent(tmp_path, "proj", "legacy", "foo")
        rebuild_name_registry()
        with pytest.raises(NameCollisionError):
            claim_registered_name("athena.foo", second)

        delete_registered_name("foo")
        claim_registered_name("athena.bar", first)
        with pytest.raises(NameCollisionError):
            claim_registered_name("bar", second)


def test_claim_registered_name_records_sharded_owner_identity(
    tmp_path: Path,
) -> None:
    artifact_dir = _make_sharded_agent(
        tmp_path,
        "proj",
        "20260613130000",
        "claimed",
    )
    with patch.object(Path, "home", return_value=tmp_path):
        claim_registered_name("claimed", artifact_dir)
        entry = lookup_registered_name("claimed")

    assert entry is not None
    assert entry["project_name"] == "proj"
    assert entry["workflow_dir"] == "ace-run"
    assert entry["raw_suffix"] == "20260613130000"
    assert entry["created_at"] == "20260613130000"


def test_local_claim_records_v2_registry_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_machine(monkeypatch)
    artifact_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/run1"
    artifact_dir.mkdir(parents=True)

    with patch.object(Path, "home", return_value=tmp_path):
        claim_registered_name("athena.foo", artifact_dir)
        data = load_name_registry()

    assert data["schema_version"] == 2
    entry = data["entries"]["foo"]
    assert entry["origin"] == "local"
    assert entry["canonical_global_name"] == "alice.athena.foo"
    assert entry["source_owner"] == {
        "username": "alice",
        "machine_name": "athena",
    }


def test_registry_rebuild_globalizes_legacy_terminal_segment_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A legacy role marker outside the terminal segment receives provenance.

    Historical artifacts include names such as ``foo--role.f-0`` (a fanout child
    of a family member). The historical classifier treats that as a solo name
    whose ``--role`` fragment is opaque, so registry rebuilds keep explicit
    current-owner provenance for it.
    """
    _configure_machine(monkeypatch)
    _make_agent(tmp_path, "proj", "run1", "foo--role.f-0")
    _make_agent(tmp_path, "proj", "run2", "foo")

    with patch.object(Path, "home", return_value=tmp_path):
        data = rebuild_name_registry()

    entries = data["entries"]
    legacy = entries["foo--role.f-0"]
    assert legacy["origin"] == "local"
    assert legacy["canonical_global_name"] == "alice.athena.foo--role.f-0"
    assert legacy["source_owner"] == {"username": "alice", "machine_name": "athena"}
    # Well-formed neighbours still receive a canonical global spelling.
    assert entries["foo"]["canonical_global_name"] == "alice.athena.foo"


def test_owner_namespaces_block_new_local_descendants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_machine(monkeypatch)
    artifact_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/run1"
    artifact_dir.mkdir(parents=True)

    with patch.object(Path, "home", return_value=tmp_path):
        with pytest.raises(NameCollisionError, match="owner namespace 'zeus'"):
            claim_registered_name("zeus.worker", artifact_dir)


def test_configured_registry_rebuild_preserves_qualified_auto_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_machine(monkeypatch)
    _make_agent(tmp_path, "proj", "run1", "athena.1.plan")
    with patch.object(Path, "home", return_value=tmp_path):
        data = rebuild_name_registry()

    assert {"athena.1", "athena.1.plan"} <= set(data["entries"])
    assert "1" not in data["entries"]
    assert data["entries"]["athena.1"]["reservation_kind"] == "auto_prefix"


def test_registry_rebuild_preserves_explicit_import_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_machine(monkeypatch)
    artifact_dir = _make_agent(tmp_path, "proj", "run1", "zeus.worker", done=True)
    meta_path = artifact_dir / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update(
        {
            "imported_source_owner": {
                "username": "alice",
                "machine_name": "zeus",
            },
            "canonical_global_name": "alice.zeus.worker",
            "imported_snapshot_digest": "a" * 64,
        }
    )
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    with patch.object(Path, "home", return_value=tmp_path):
        data = rebuild_name_registry()

    entry = data["entries"]["zeus.worker"]
    assert entry["origin"] == "import_v2"
    assert entry["canonical_global_name"] == "alice.zeus.worker"
    assert entry["source_owner"]["machine_name"] == "zeus"


def test_registry_rebuild_keeps_v1_username_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_machine(monkeypatch)
    artifact_dir = _make_agent(tmp_path, "proj", "run1", "zeus.worker", done=True)
    meta_path = artifact_dir / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update(
        {
            "imported_from_machine": "zeus",
            "imported_digest": "a" * 64,
        }
    )
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    with patch.object(Path, "home", return_value=tmp_path):
        data = rebuild_name_registry()

    entry = data["entries"]["zeus.worker"]
    assert entry["origin"] == "import_v1"
    assert entry["source_owner"] is None
    assert entry["legacy_source_machine"] == "zeus"
    assert entry["canonical_global_name"] is None


def test_registry_rebuild_localizes_bare_workflow_name_from_v2_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A synced artifact's bare ``workflow_name`` must not squat the local tree.

    Sync preserves ``name`` as an already-localized spelling but leaves other
    name fields (here ``workflow_name``) in the source machine's bare
    spelling. A rebuild must localize that bare spelling too, or it would
    register a bare ``research`` auto-prefix that permanently blocks every
    local ``research.*`` name (the reported ``NameCollisionError`` bug).
    """
    identity = AgentIdentitySnapshot(
        AgentOwnerIdentity("alice", "zeus"),
        ("zeus", "athena"),
    )
    monkeypatch.setattr(
        AgentIdentitySnapshot,
        "current",
        classmethod(lambda _cls: identity),
    )
    _make_agent(
        tmp_path,
        "proj",
        "run1",
        "athena.research.b.cld.f0",
        workflow_name="research.b.cld.f0",
        extra_meta={
            "imported_source_owner": {"username": "alice", "machine_name": "athena"},
            "canonical_global_name": "alice.athena.research.b.cld.f0",
            "imported_snapshot_digest": "a" * 64,
        },
    )

    with patch.object(Path, "home", return_value=tmp_path):
        data = rebuild_name_registry()

    entries = data["entries"]
    assert "athena.research.b.cld.f0" in entries
    assert entries["athena.research.b.cld.f0"]["reservation_kind"] == "claimed"
    assert entries["athena.research.b.cld.f0"]["origin"] == "import_v2"
    assert entries["athena"]["container_kind"] == "owner_namespace"
    assert "research" not in entries
    assert "research.b.cld.f0" not in entries


def test_registry_rebuild_localizes_bare_workflow_name_from_v1_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = AgentIdentitySnapshot(
        AgentOwnerIdentity("alice", "zeus"),
        ("zeus",),
    )
    monkeypatch.setattr(
        AgentIdentitySnapshot,
        "current",
        classmethod(lambda _cls: identity),
    )
    _make_agent(
        tmp_path,
        "proj",
        "run1",
        "athena.legacy.worker",
        workflow_name="legacy.worker",
        extra_meta={
            "imported_from_machine": "athena",
            "imported_digest": "a" * 64,
        },
    )

    with patch.object(Path, "home", return_value=tmp_path):
        data = rebuild_name_registry()

    entries = data["entries"]
    assert "athena.legacy.worker" in entries
    assert entries["athena.legacy.worker"]["origin"] == "import_v1"
    assert entries["athena"]["container_kind"] == "owner_namespace"
    assert "legacy" not in entries
    assert "legacy.worker" not in entries


def test_delete_registered_name_releases_slot(tmp_path: Path) -> None:
    _make_agent(tmp_path, "proj", "run1", "foo")
    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        delete_registered_name("foo")
        assert lookup_registered_name("foo") is None
