"""Legacy-v1 classification: which v1 groups stay foreign, pending, or covered."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.agents_sync import (
    bundles,
    incoming_cache,
    incoming_detection,
    incoming_integration,
)
from sase.agents_sync.io import _compute_bundle_digest, atomic_write_json
from sase.agents_sync.models import (
    AgentBundle,
    AgentsManifest,
    CommitRecord,
    ManifestEntry,
    PortableAgentMetadata,
    ProjectTarget,
)
from sase.core.agent_identity_facade import AgentOwnerIdentity

from tests.agents_sync.bundle_fixtures import write_bundle
from tests.agents_sync.incoming_cache_fixtures import (
    LOCAL_OWNER,
    PROJECT,
    commit_and_push,
    git,
    patch_target,
    publish_owner,
    refresh,
    seed_target_for,
    setup_v2_remote,
    write_legacy_group,
)


def _setup_v1_only_remote(
    tmp_path: Path,
    roles: tuple[str, ...],
) -> tuple[ProjectTarget, tuple[ManifestEntry, ...]]:
    """Seed a remote holding one legacy-v1 bundle per role and clone it."""

    primary = tmp_path / "primary"
    primary.mkdir()
    remote = tmp_path / "remote.git"
    remote.mkdir()
    git(remote, "init", "--bare")
    seed = tmp_path / "seed"
    seed.mkdir()
    entries: list[ManifestEntry] = []
    for index, role in enumerate(roles, start=1):
        name = f"athena.crew--{role}"
        metadata = PortableAgentMetadata(
            name,
            "athena",
            f"2026072412000{index}",
            2,
        )
        commits = (CommitRecord(str(index) * 40, role, index),)
        chat = f"{role}\n".encode()
        digest = _compute_bundle_digest(metadata, commits, chat)
        bundle = AgentBundle(metadata, commits, chat, digest)
        write_bundle(seed, bundle)
        entries.append(
            ManifestEntry(
                name,
                "athena",
                digest,
                metadata.artifact_timestamp,
                "2026-07-24T12:00:00+00:00",
            )
        )
    atomic_write_json(
        seed / "manifest.json",
        AgentsManifest(tuple(entries)).to_json_dict(),
    )
    git(seed, "init")
    git(seed, "config", "user.name", "Tests")
    git(seed, "config", "user.email", "tests@example.test")
    git(seed, "add", ".")
    git(seed, "commit", "-m", "legacy")
    git(seed, "remote", "add", "origin", str(remote))
    git(seed, "push", "-u", "origin", "HEAD")
    sidecar = tmp_path / "sidecar"
    git(tmp_path, "clone", str(remote), str(sidecar))
    return (
        ProjectTarget(
            PROJECT.key,
            PROJECT.name,
            primary,
            (primary.resolve(),),
            sidecar,
            str(remote),
        ),
        tuple(entries),
    )


def test_username_unknown_v1_entries_are_grouped_by_machine_and_hood(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, entries = _setup_v1_only_remote(tmp_path, ("plan", "code"))
    patch_target(monkeypatch, target)

    current = refresh(target, network_calls=[], now=100.0).projects[0]

    assert current.pending_foreign_count == 1
    item = current.pending_updates[0]
    assert item.format_version == 1
    assert item.source_username is None
    assert item.source_machine == "athena"
    assert item.top_hood == "crew"
    assert item.run_count == 2
    assert incoming_cache.load_validated_cache_item(item).legacy_manifest is not None

    local = tmp_path / entries[0].artifact_timestamp
    local.mkdir()
    (local / "commit_result.json").write_text(
        json.dumps({"result": "1" * 9}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        bundles,
        "_v1_artifact_rows",
        lambda _target: (
            (
                local,
                {"name": "crew--plan"},
                {"name": "crew--plan", "outcome": "completed"},
            ),
        ),
    )
    monkeypatch.setattr(
        bundles,
        "_create_imported_artifact",
        lambda *_args, **_kwargs: pytest.fail("owner group was imported"),
    )

    cached = incoming_integration.integrate_cached_agent_updates((item,))
    full = incoming_integration.integrate_agent_imports_with_receipts(
        target,
        target.sidecar_path,
        LOCAL_OWNER,
    )

    assert cached[0].disposition == "owner_observed"
    assert cached[0].ok
    assert cached[0].unchanged == 2
    assert full.integrated == 0
    assert full.unchanged == 2
    assert full.owner_observed_groups == 1
    assert incoming_cache.read_project_receipts(PROJECT.key) == ()


def test_owner_machine_v1_with_exact_owner_v2_coverage_is_not_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, seed = setup_v2_remote(tmp_path)
    entry = write_legacy_group(seed, machine="athena", hood="crew")
    for filename in ("meta.json", "commits.json", "chat.md"):
        (seed / "agents" / entry.name / filename).unlink()
    commit_and_push(seed, "add covered legacy owner hood")
    patch_target(monkeypatch, target)

    current = refresh(target, network_calls=[], now=100.0).projects[0]

    assert current.owner_v2_hoods == ("crew",)
    assert current.exact_owner_count == 2
    assert current.validated_foreign_count == 2
    assert all(item.format_version == 2 for item in current.pending_updates)
    assert current.quarantine_diagnostics == ()


def test_owner_machine_v1_with_abbreviated_local_commit_proof_is_not_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, seed = setup_v2_remote(tmp_path)
    entry = write_legacy_group(seed, machine="athena", hood="legacy")
    (seed / "agents" / entry.name / "chat.md").unlink()
    commit_and_push(seed, "add locally proven legacy owner hood")
    patch_target(monkeypatch, target)
    artifact = tmp_path / "artifacts" / entry.artifact_timestamp
    artifact.mkdir(parents=True)
    (artifact / "commit_result.json").write_text(
        json.dumps({"result": "d" * 9}),
        encoding="utf-8",
    )
    artifact_index_calls = 0

    def artifact_rows(
        _target: ProjectTarget,
    ) -> tuple[tuple[Path, dict[str, object], dict[str, object]], ...]:
        nonlocal artifact_index_calls
        artifact_index_calls += 1
        return ((artifact, {"name": "legacy"}, {"name": "legacy"}),)

    monkeypatch.setattr(incoming_detection.bundles, "_v1_artifact_rows", artifact_rows)

    current = refresh(target, network_calls=[], now=100.0).projects[0]

    assert artifact_index_calls == 1
    assert current.exact_owner_count == 2
    assert all(item.format_version == 2 for item in current.pending_updates)
    assert current.quarantine_diagnostics == ()


@pytest.mark.parametrize(
    ("machine", "hood"),
    (
        ("athena", "unproven"),
        ("zeus", "crew"),
    ),
)
def test_unproven_or_other_machine_v1_stays_foreign(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    machine: str,
    hood: str,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, seed = setup_v2_remote(tmp_path)
    write_legacy_group(seed, machine=machine, hood=hood)
    commit_and_push(seed, "add foreign legacy hood")
    patch_target(monkeypatch, target)

    current = refresh(target, network_calls=[], now=100.0).projects[0]

    legacy = [item for item in current.pending_updates if item.format_version == 1]
    assert len(legacy) == 1
    assert (legacy[0].source_machine, legacy[0].top_hood) == (machine, hood)
    assert current.validated_foreign_count == 3


def test_same_machine_v1_is_not_covered_by_another_username_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, seed = setup_v2_remote(tmp_path)
    publish_owner(
        seed_target_for(target, seed),
        AgentOwnerIdentity("bob", "athena"),
        suffix="4",
        hood="other",
    )
    write_legacy_group(seed, machine="athena", hood="other")
    commit_and_push(seed, "add other-user coverage and legacy hood")
    patch_target(monkeypatch, target)

    current = refresh(target, network_calls=[], now=100.0).projects[0]

    assert current.owner_v2_hoods == ("crew",)
    legacy = [item for item in current.pending_updates if item.format_version == 1]
    assert len(legacy) == 1
    assert legacy[0].top_hood == "other"
