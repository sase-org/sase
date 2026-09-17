from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.publication import publish_agent_hood, reconcile_agent_hoods
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.feature_flags import FeatureFlag, override_flags
from tests.agents_sync.publication_fixtures import _identity, _inventory, _target


def _owner_manifest_path(repo: Path) -> Path:
    return repo / "users" / "alice" / "machines" / "athena" / "manifest.json"


def test_publication_skips_undecodable_foreign_manifest_but_keeps_local_strict(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    inventory = _inventory(AgentOwnerIdentity("alice", "athena"))
    publish_agent_hood(
        target,
        repo,
        "foo.bar.baz--code",
        identity=_identity(),
        inventory=inventory,
    )
    foreign_manifest = repo / "users" / "bob" / "machines" / "zeus" / "manifest.json"
    foreign_manifest.parent.mkdir(parents=True)
    foreign_manifest.write_text("{}\n", encoding="utf-8")

    counts = publish_agent_hood(
        target,
        repo,
        "foo.bar.baz--code",
        identity=_identity(),
        inventory=inventory,
    )

    assert counts.hoods_unchanged == 1
    assert any(
        "users/bob/machines/zeus/manifest.json: skipped v2 owner manifest" in row
        for row in counts.diagnostics
    )

    local_manifest = repo / "users" / "alice" / "machines" / "athena" / "manifest.json"
    local_manifest.write_text("{}\n", encoding="utf-8")
    with pytest.raises(AgentsSyncFormatError, match="missing required keys"):
        publish_agent_hood(
            target,
            repo,
            "foo.bar.baz--code",
            identity=_identity(),
            inventory=inventory,
        )


def test_plan_hoods_refuses_to_republish_from_an_empty_manifest(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    inventory = _inventory(AgentOwnerIdentity("alice", "athena"))
    publish_agent_hood(
        target,
        repo,
        "foo.bar.baz--code",
        identity=_identity(),
        inventory=inventory,
    )
    _owner_manifest_path(repo).unlink()

    with pytest.raises(AgentsSyncFormatError, match="on-disk hood director"):
        publish_agent_hood(
            target,
            repo,
            "foo.bar.baz--code",
            identity=_identity(),
            inventory=inventory,
        )


def test_plan_hoods_diagnoses_but_still_publishes_when_manifest_omits_a_hood(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    inventory = _inventory(AgentOwnerIdentity("alice", "athena"))
    counts = reconcile_agent_hoods(
        target,
        repo,
        identity=_identity(),
        inventory=inventory,
    )
    assert counts.hoods_published == 2

    manifest_path = _owner_manifest_path(repo)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["hoods"]["work"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    refreshed = publish_agent_hood(
        target,
        repo,
        "foo.bar.baz--code",
        identity=_identity(),
        inventory=inventory,
    )

    assert any(
        "omits" in diagnostic and "work" in diagnostic
        for diagnostic in refreshed.diagnostics
    )
    assert (
        repo
        / "users"
        / "alice"
        / "machines"
        / "athena"
        / "hoods"
        / "work"
        / "snapshot.json"
    ).is_file()


def test_plan_hoods_manifest_guard_is_inert_on_a_clean_repository(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    inventory = _inventory(AgentOwnerIdentity("alice", "athena"))

    counts = publish_agent_hood(
        target,
        repo,
        "foo.bar.baz--code",
        identity=_identity(),
        inventory=inventory,
    )

    assert counts.hoods_published == 1
    assert not any("omits" in diagnostic for diagnostic in counts.diagnostics)


def test_manifest_writer_honors_slim_agents_manifest_flag(tmp_path: Path) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    inventory = _inventory(AgentOwnerIdentity("alice", "athena"))

    publish_agent_hood(
        target,
        repo,
        "foo.bar.baz--code",
        identity=_identity(),
        inventory=inventory,
    )
    slim_manifest = json.loads(_owner_manifest_path(repo).read_text(encoding="utf-8"))
    assert "files" not in slim_manifest["hoods"]["foo"]

    with override_flags(**{str(FeatureFlag.slim_agents_manifest): False}):
        publish_agent_hood(
            target,
            repo,
            "foo.bar.baz--code",
            identity=_identity(),
            inventory=inventory,
        )
    fat_manifest = json.loads(_owner_manifest_path(repo).read_text(encoding="utf-8"))
    fat_files = fat_manifest["hoods"]["foo"]["files"]
    assert fat_files == sorted(set(fat_files))

    publish_agent_hood(
        target,
        repo,
        "foo.bar.baz--code",
        identity=_identity(),
        inventory=inventory,
    )
    resumed_manifest = json.loads(
        _owner_manifest_path(repo).read_text(encoding="utf-8")
    )
    assert "files" not in resumed_manifest["hoods"]["foo"]


def test_plan_hoods_write_guard_rejects_a_manifest_over_the_read_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agents_sync import v2_manifest_io

    monkeypatch.setattr(v2_manifest_io, "MAX_MANIFEST_HOODS", 0)
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    inventory = _inventory(AgentOwnerIdentity("alice", "athena"))

    with pytest.raises(AgentsSyncFormatError, match="hood read cap"):
        publish_agent_hood(
            target,
            repo,
            "foo.bar.baz--code",
            identity=_identity(),
            inventory=inventory,
        )

    assert not _owner_manifest_path(repo).exists()
