from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

import pytest

from sase.agent.names import _registry
from sase.agent.names._common import NameCollisionError
from sase.agents_sync.io import AgentsSyncFormatError


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
