from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

import pytest

from sase.agent.names import _registry
from sase.agent.names._common import ImportedNameCollisionError, NameCollisionError
from sase.agent.names._registry_mutations import ImportedV2RegistryClaim
from sase.agents_sync.io import AgentsSyncFormatError
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity


def test_imported_claim_preserves_exact_unknown_foreign_hood(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored: dict[str, object] = {"entries": {}}
    monkeypatch.setattr(_registry, "_registry_mutation_lock", nullcontext)
    monkeypatch.setattr(_registry, "load_name_registry", lambda: stored)
    monkeypatch.setattr(
        _registry,
        "_owner_from_artifact_name",
        lambda path, name, reservation_kind: {
            "source": "artifact",
            "name": name,
            "artifacts_dir": str(path),
            "reservation_kind": reservation_kind,
        },
    )

    def save(entries: dict[str, object]) -> None:
        stored["entries"] = entries

    monkeypatch.setattr(_registry, "_save_entries", save)
    artifact = tmp_path / "artifact"

    _registry.claim_imported_registered_name(
        "zeus.worker", "zeus", artifact, digest="a" * 64
    )
    entry = stored["entries"]["zeus.worker"]  # type: ignore[index]
    assert entry["name"] == "zeus.worker"
    assert entry["imported_from_machine"] == "zeus"

    _registry.claim_imported_registered_name(
        "zeus.worker", "zeus", artifact, digest="b" * 64
    )
    assert stored["entries"]["zeus.worker"]["imported_digest"] == "b" * 64  # type: ignore[index]

    with pytest.raises(NameCollisionError):
        _registry.claim_imported_registered_name(
            "zeus.worker", "zeus", tmp_path / "other", digest="c" * 64
        )
    with pytest.raises(AgentsSyncFormatError, match="does not belong"):
        _registry.claim_imported_registered_name(
            "zeus.worker", "hera", artifact, digest="d" * 64
        )


def test_v2_claim_batch_preflights_without_write_and_saves_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored: dict[str, object] = {"entries": {}}
    saves: list[dict[str, object]] = []
    monkeypatch.setattr(_registry, "_registry_mutation_lock", nullcontext)
    monkeypatch.setattr(_registry, "load_name_registry", lambda: stored)
    monkeypatch.setattr(
        _registry,
        "_owner_from_artifact_name",
        lambda path, name, reservation_kind: {
            "source": "artifact",
            "name": name,
            "artifacts_dir": str(Path(path).resolve()),
            "reservation_kind": reservation_kind,
        },
    )

    def save(entries: dict[str, object]) -> None:
        stored["entries"] = entries
        saves.append(entries)

    monkeypatch.setattr(_registry, "_save_entries", save)
    source = AgentOwnerIdentity("bob", "zeus")
    identity = AgentIdentitySnapshot(AgentOwnerIdentity("alice", "athena"))
    claims = (
        ImportedV2RegistryClaim(
            source,
            "bob.zeus.one",
            "bob.zeus.one",
            tmp_path / "one",
            "a" * 64,
        ),
        ImportedV2RegistryClaim(
            source,
            "bob.zeus.two",
            "bob.zeus.two",
            tmp_path / "two",
            "a" * 64,
        ),
    )

    _registry.preflight_imported_registered_names_v2(claims, identity=identity)
    assert saves == []
    _registry.claim_imported_registered_names_v2(claims, identity=identity)
    assert len(saves) == 1
    assert {"bob", "bob.zeus.one", "bob.zeus.two"} <= set(
        stored["entries"]  # type: ignore[arg-type]
    )

    conflicting = (
        *claims,
        ImportedV2RegistryClaim(
            source,
            "bob.zeus.one",
            "bob.zeus.one",
            tmp_path / "other",
            "b" * 64,
        ),
    )
    with pytest.raises(ImportedNameCollisionError):
        _registry.preflight_imported_registered_names_v2(
            conflicting,
            identity=identity,
        )
    assert len(saves) == 1
