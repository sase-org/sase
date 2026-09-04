"""Claim and ownership tests for the durable agent-name registry."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.names import (
    ImportedNameCollisionError,
    ImportedV2RegistryClaim,
    NameCollisionError,
    claim_imported_registered_name,
    claim_imported_registered_name_v2,
    claim_imported_registered_names_v2,
    claim_registered_name,
    delete_registered_name,
    get_reserved_agent_names,
    load_name_registry,
    lookup_registered_name,
    preflight_imported_registered_names_v2,
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


def test_v2_import_claims_preserve_owner_and_namespace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_machine(monkeypatch)
    artifact_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/run1"
    artifact_dir.mkdir(parents=True)
    source_owner = AgentOwnerIdentity("alice", "zeus")

    with patch.object(Path, "home", return_value=tmp_path):
        claim_imported_registered_name_v2(
            source_owner,
            "alice.zeus.worker",
            "zeus.worker",
            artifact_dir,
            digest="a" * 64,
        )
        claim_imported_registered_name_v2(
            source_owner,
            "alice.zeus.worker",
            "zeus.worker",
            artifact_dir,
            digest="b" * 64,
        )
        data = load_name_registry()

    entry = data["entries"]["zeus.worker"]
    assert entry["origin"] == "import_v2"
    assert entry["canonical_global_name"] == "alice.zeus.worker"
    assert entry["source_owner"] == {
        "username": "alice",
        "machine_name": "zeus",
    }
    assert entry["imported_digest"] == "b" * 64
    assert data["entries"]["zeus"]["container_kind"] == "owner_namespace"


def test_v2_import_rejects_owner_and_namespace_collisions_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_machine(monkeypatch)
    first = tmp_path / ".sase/projects/proj/artifacts/ace-run/run1"
    second = tmp_path / ".sase/projects/proj/artifacts/ace-run/run2"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    source_owner = AgentOwnerIdentity("bob", "athena")

    with patch.object(Path, "home", return_value=tmp_path):
        claim_registered_name("bob.athena.local", first)
        before = load_name_registry()
        with pytest.raises(ImportedNameCollisionError):
            claim_imported_registered_name_v2(
                source_owner,
                "bob.athena.worker",
                "bob.athena.worker",
                second,
                digest="a" * 64,
            )
        after = load_name_registry()

    assert after == before
    assert "bob.athena.worker" not in after["entries"]


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


def test_exact_current_owner_v2_refresh_reuses_local_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_machine(monkeypatch)
    artifact_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/run1"
    artifact_dir.mkdir(parents=True)
    current_owner = AgentOwnerIdentity("alice", "athena")

    with patch.object(Path, "home", return_value=tmp_path):
        claim_registered_name("foo", artifact_dir)
        before = load_name_registry()
        claim_imported_registered_name_v2(
            current_owner,
            "alice.athena.foo",
            "foo",
            artifact_dir,
            digest="a" * 64,
        )
        after = load_name_registry()

    assert after == before
    assert set(after["entries"]) == {"foo", "zeus"}


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


def test_v2_claim_tolerates_legacy_v1_root_and_unrelated_sibling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A same-user/other-machine v2 claim must not collide with v1 leftovers.

    Regression coverage for the wedged-machine namespace guard: a v1 import
    reserves a synthetic ``legacy_source_machine`` root plus one leaf per
    imported name. A same-user v2 claim from that same machine must tolerate
    both the root and any unrelated v1 sibling beneath it.
    """
    _configure_machine(monkeypatch)
    sibling_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/sibling"
    artifact_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/run1"
    sibling_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    local_owner = AgentOwnerIdentity("alice", "athena")
    source_owner = AgentOwnerIdentity("alice", "zeus")

    with patch.object(Path, "home", return_value=tmp_path):
        claim_imported_registered_name(
            "zeus.other",
            "zeus",
            sibling_dir,
            digest="c" * 64,
            target_owner=local_owner,
        )
        before_sibling = load_name_registry()["entries"]["zeus.other"]

        claim_imported_registered_name_v2(
            source_owner,
            "alice.zeus.worker",
            "zeus.worker",
            artifact_dir,
            digest="a" * 64,
        )
        data = load_name_registry()

    assert data["entries"]["zeus.other"] == before_sibling
    entry = data["entries"]["zeus.worker"]
    assert entry["origin"] == "import_v2"
    assert entry["source_owner"] == {"username": "alice", "machine_name": "zeus"}


def test_v1_root_for_different_machine_still_collides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_machine(monkeypatch)
    legacy_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/legacy"
    artifact_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/run1"
    legacy_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    local_owner = AgentOwnerIdentity("alice", "athena")

    with patch.object(Path, "home", return_value=tmp_path):
        # A v1 legacy machine literally named "bob" reserved a namespace root.
        claim_imported_registered_name(
            "bob.legacy-worker",
            "bob",
            legacy_dir,
            digest="c" * 64,
            target_owner=local_owner,
        )
        before = load_name_registry()

        # A same-named OTHER_USER "bob" now imports from an unrelated machine.
        source_owner = AgentOwnerIdentity("bob", "pluto")
        claim = ImportedV2RegistryClaim(
            source_owner,
            "bob.pluto.worker",
            "bob.pluto.worker",
            artifact_dir,
            "a" * 64,
        )
        with pytest.raises(ImportedNameCollisionError):
            preflight_imported_registered_names_v2((claim,))
        after = load_name_registry()

    assert after == before


def test_v2_claim_adopts_matching_v1_import_when_authorized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_machine(monkeypatch)
    artifact_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/run1"
    artifact_dir.mkdir(parents=True)
    local_owner = AgentOwnerIdentity("alice", "athena")
    source_owner = AgentOwnerIdentity("alice", "zeus")

    with patch.object(Path, "home", return_value=tmp_path):
        claim_imported_registered_name(
            "zeus.worker",
            "zeus",
            artifact_dir,
            digest="a" * 64,
            target_owner=local_owner,
        )
        resolved_dir = artifact_dir.resolve()
        claim = ImportedV2RegistryClaim(
            source_owner,
            "alice.zeus.worker",
            "zeus.worker",
            artifact_dir,
            "b" * 64,
        )
        preflight_imported_registered_names_v2(
            (claim,),
            adopted_v1_artifact_dirs=frozenset({resolved_dir}),
        )
        claim_imported_registered_names_v2(
            (claim,),
            adopted_v1_artifact_dirs=frozenset({resolved_dir}),
        )
        data = load_name_registry()

    entry = data["entries"]["zeus.worker"]
    assert entry["origin"] == "import_v2"
    assert entry["source_owner"] == {"username": "alice", "machine_name": "zeus"}
    assert entry["canonical_global_name"] == "alice.zeus.worker"
    assert "collision_owners" not in entry


def test_v2_claim_without_adoption_authority_still_collides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_machine(monkeypatch)
    artifact_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/run1"
    artifact_dir.mkdir(parents=True)
    local_owner = AgentOwnerIdentity("alice", "athena")
    source_owner = AgentOwnerIdentity("alice", "zeus")

    with patch.object(Path, "home", return_value=tmp_path):
        claim_imported_registered_name(
            "zeus.worker",
            "zeus",
            artifact_dir,
            digest="a" * 64,
            target_owner=local_owner,
        )
        before = load_name_registry()
        claim = ImportedV2RegistryClaim(
            source_owner,
            "alice.zeus.worker",
            "zeus.worker",
            artifact_dir,
            "b" * 64,
        )
        with pytest.raises(ImportedNameCollisionError):
            preflight_imported_registered_names_v2((claim,))
        after = load_name_registry()

    assert after == before


def test_foreign_username_adoption_pops_machine_rooted_v1_spelling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_machine(monkeypatch)
    artifact_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/run1"
    artifact_dir.mkdir(parents=True)
    local_owner = AgentOwnerIdentity("alice", "athena")
    source_owner = AgentOwnerIdentity("bob", "zeus")

    with patch.object(Path, "home", return_value=tmp_path):
        claim_imported_registered_name(
            "zeus.crew--plan",
            "zeus",
            artifact_dir,
            digest="a" * 64,
            target_owner=local_owner,
        )
        resolved_dir = artifact_dir.resolve()
        claim = ImportedV2RegistryClaim(
            source_owner,
            "bob.zeus.crew--plan",
            "bob.zeus.crew--plan",
            artifact_dir,
            "b" * 64,
        )
        preflight_imported_registered_names_v2(
            (claim,),
            adopted_v1_artifact_dirs=frozenset({resolved_dir}),
        )
        claim_imported_registered_names_v2(
            (claim,),
            adopted_v1_artifact_dirs=frozenset({resolved_dir}),
        )
        data = load_name_registry()

    assert "zeus.crew--plan" not in data["entries"]
    entry = data["entries"]["bob.zeus.crew--plan"]
    assert entry["origin"] == "import_v2"
    assert entry["source_owner"] == {"username": "bob", "machine_name": "zeus"}
    assert entry["canonical_global_name"] == "bob.zeus.crew--plan"


def test_delete_registered_name_releases_slot(tmp_path: Path) -> None:
    _make_agent(tmp_path, "proj", "run1", "foo")
    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        delete_registered_name("foo")
        assert lookup_registered_name("foo") is None
