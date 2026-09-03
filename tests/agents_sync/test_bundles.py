from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from sase.agents_sync import bundles
from sase.agents_sync.io import _compute_bundle_digest
from sase.agents_sync.models import (
    AgentBundle,
    AgentsManifest,
    CommitRecord,
    ManifestEntry,
    PortableAgentMetadata,
    ProjectTarget,
)
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.feature_flags import override_flags

from tests.agents_sync.bundle_fixtures import write_bundle

LOCAL_OWNER = AgentOwnerIdentity("alice", "athena")


@pytest.fixture(autouse=True)
def _v1_import_not_retired() -> Iterator[None]:
    """This module exercises the v1 materialization path the sunset flag guards.

    ``v1_import_retired`` defaults on; these tests specifically cover the
    disabled-branch behavior, which stays reachable until the flag is removed.
    """
    with override_flags(v1_import_retired=False):
        yield


def _target(tmp_path: Path) -> ProjectTarget:
    primary = tmp_path / "primary"
    primary.mkdir()
    return ProjectTarget(
        "proj",
        "Project",
        primary,
        (primary.resolve(),),
        tmp_path / "sidecar",
        str(tmp_path / "remote.git"),
    )


def _bundle(*, model: str = "first", chat: bytes = b"chat\n") -> AgentBundle:
    meta = PortableAgentMetadata(
        "zeus.worker",
        "zeus",
        "20260722123456",
        2,
        (("model", model), ("workflow_name", "ace-run")),
    )
    commits = (CommitRecord("a" * 40, "subject", 100),)
    return AgentBundle(meta, commits, chat, _compute_bundle_digest(meta, commits, chat))


def _entry(bundle: AgentBundle) -> ManifestEntry:
    return ManifestEntry(
        bundle.metadata.name,
        bundle.metadata.machine,
        bundle.digest,
        bundle.metadata.artifact_timestamp,
        "2026-07-22T12:34:56+00:00",
    )


def test_foreign_bundle_round_trip_idempotence_and_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    first = _bundle()
    manifest = AgentsManifest((_entry(first),))
    write_bundle(repo, first)
    artifact_root = tmp_path / "artifacts"
    chat_home = tmp_path / "state"
    claims: list[tuple[str, str, Path, str]] = []

    monkeypatch.setattr(bundles, "sase_home", lambda: chat_home)
    monkeypatch.setattr(
        bundles,
        "canonical_agent_artifact_path",
        lambda _project, _workflow, timestamp: artifact_root / timestamp,
    )
    monkeypatch.setattr(
        bundles,
        "iter_agent_artifact_dirs",
        lambda *_args, **_kwargs: iter(sorted(artifact_root.glob("*"))),
    )
    monkeypatch.setattr(
        bundles,
        "claim_imported_registered_name",
        lambda name, machine, path, digest, **_kwargs: claims.append(
            (name, machine, Path(path), digest)
        ),
    )
    indexed: list[Path] = []
    monkeypatch.setattr(
        bundles,
        "update_agent_artifact_index_for_marker_mutation",
        lambda path: indexed.append(Path(path)),
    )

    counts = bundles.integrate_foreign_bundles(target, repo, manifest, LOCAL_OWNER)
    assert counts.integrated == 1
    artifact = artifact_root / "20260722123456"
    meta = json.loads((artifact / "agent_meta.json").read_text())
    done = json.loads((artifact / "done.json").read_text())
    assert meta["name"] == "zeus.worker"
    assert meta["imported_from_machine"] == "zeus"
    assert Path(meta["chat_path"]).read_bytes() == b"chat\n"
    assert done["outcome"] == "completed"
    assert claims[-1][:2] == ("zeus.worker", "zeus")
    assert indexed == [artifact]

    unchanged = bundles.integrate_foreign_bundles(target, repo, manifest, LOCAL_OWNER)
    assert unchanged.unchanged == 1
    assert len(claims) == 1

    refreshed_bundle = _bundle(model="second", chat=b"new chat\n")
    refreshed_manifest = AgentsManifest((_entry(refreshed_bundle),))
    write_bundle(repo, refreshed_bundle)
    refreshed = bundles.integrate_foreign_bundles(
        target, repo, refreshed_manifest, LOCAL_OWNER
    )
    assert refreshed.refreshed == 1
    refreshed_meta = json.loads((artifact / "agent_meta.json").read_text())
    assert refreshed_meta["model"] == "second"
    assert Path(refreshed_meta["chat_path"]).read_bytes() == b"new chat\n"


def test_v1_import_retired_flag_blocks_create_and_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    first = _bundle()
    manifest = AgentsManifest((_entry(first),))
    write_bundle(repo, first)
    artifact_root = tmp_path / "artifacts"

    monkeypatch.setattr(bundles, "sase_home", lambda: tmp_path / "state")
    monkeypatch.setattr(
        bundles,
        "canonical_agent_artifact_path",
        lambda _project, _workflow, timestamp: artifact_root / timestamp,
    )
    monkeypatch.setattr(
        bundles,
        "iter_agent_artifact_dirs",
        lambda *_args, **_kwargs: iter(sorted(artifact_root.glob("*"))),
    )
    claims: list[tuple[str, str]] = []
    monkeypatch.setattr(
        bundles,
        "claim_imported_registered_name",
        lambda name, machine, *_args, **_kwargs: claims.append((name, machine)),
    )
    monkeypatch.setattr(
        bundles,
        "update_agent_artifact_index_for_marker_mutation",
        lambda _path: None,
    )

    # First import happens while the flag is off; it establishes an existing
    # imported artifact so the refresh branch (not just create) can be probed.
    baseline = bundles.integrate_foreign_bundles(target, repo, manifest, LOCAL_OWNER)
    assert baseline.integrated == 1
    assert len(claims) == 1
    artifact = artifact_root / "20260722123456"
    original_meta = json.loads((artifact / "agent_meta.json").read_text())

    with override_flags(v1_import_retired=True):
        never_imported_meta = PortableAgentMetadata(
            "zeus.other",
            "zeus",
            "20260722999999",
            2,
            (("model", "brand-new"), ("workflow_name", "ace-run")),
        )
        never_imported = AgentBundle(
            never_imported_meta,
            first.commits,
            b"chat\n",
            _compute_bundle_digest(never_imported_meta, first.commits, b"chat\n"),
        )
        write_bundle(repo, never_imported)
        create_manifest = AgentsManifest((_entry(never_imported),))
        create_counts = bundles.integrate_foreign_bundles(
            target, repo, create_manifest, LOCAL_OWNER
        )
        assert create_counts.integrated == 0
        assert create_counts.v1_import_skipped == 1
        assert create_counts.diagnostics
        assert not (artifact_root / "20260722999999").exists()
        assert len(claims) == 1

        refreshed_bundle = _bundle(model="second", chat=b"new chat\n")
        refresh_manifest = AgentsManifest((_entry(refreshed_bundle),))
        write_bundle(repo, refreshed_bundle)
        refresh_counts = bundles.integrate_foreign_bundles(
            target, repo, refresh_manifest, LOCAL_OWNER
        )
        assert refresh_counts.refreshed == 0
        assert refresh_counts.v1_import_skipped == 1
        assert json.loads((artifact / "agent_meta.json").read_text()) == original_meta


def test_import_probes_forward_on_artifact_timestamp_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    foreign = _bundle()
    manifest = AgentsManifest((_entry(foreign),))
    write_bundle(repo, foreign)
    artifact_root = tmp_path / "artifacts"
    (artifact_root / "20260722123456").mkdir(parents=True)

    monkeypatch.setattr(bundles, "sase_home", lambda: tmp_path / "state")
    monkeypatch.setattr(
        bundles,
        "canonical_agent_artifact_path",
        lambda _project, _workflow, timestamp: artifact_root / timestamp,
    )
    monkeypatch.setattr(
        bundles,
        "iter_agent_artifact_dirs",
        lambda *_args, **_kwargs: iter(()),
    )
    monkeypatch.setattr(
        bundles, "claim_imported_registered_name", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        bundles,
        "update_agent_artifact_index_for_marker_mutation",
        lambda _path: None,
    )

    bundles.integrate_foreign_bundles(target, repo, manifest, LOCAL_OWNER)

    assert (artifact_root / "20260722123457" / "done.json").is_file()


def test_v1_import_indexes_local_artifacts_once_for_multi_entry_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    first = _bundle()
    second_meta = PortableAgentMetadata(
        "zeus.worker--code",
        "zeus",
        "20260722123457",
        2,
        (("model", "second"), ("workflow_name", "ace-run")),
    )
    second = AgentBundle(
        second_meta,
        first.commits,
        b"second chat\n",
        _compute_bundle_digest(second_meta, first.commits, b"second chat\n"),
    )
    write_bundle(repo, first)
    write_bundle(repo, second)
    scans = 0
    created: list[str] = []

    def artifact_rows(
        _target: ProjectTarget,
    ) -> tuple[tuple[Path, dict[str, object], dict[str, object]], ...]:
        nonlocal scans
        scans += 1
        return ()

    monkeypatch.setattr(bundles, "_v1_artifact_rows", artifact_rows)
    monkeypatch.setattr(
        bundles,
        "_create_imported_artifact",
        lambda _target, _bundle, entry, **_kwargs: created.append(entry.name),
    )

    counts = bundles.integrate_foreign_bundles(
        target,
        repo,
        AgentsManifest((_entry(first), _entry(second))),
        LOCAL_OWNER,
    )

    assert counts.integrated == 2
    assert scans == 1
    assert created == ["zeus.worker", "zeus.worker--code"]


def test_same_machine_v1_without_commit_proof_is_skipped_not_reimported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fix 2 backstop.

    A same-machine entry that shares a local artifact's timestamp and
    machine-qualified name is skipped even before any commit proof exists,
    since the proof path only ever narrows the backstop's guarantee.
    """

    target = _target(tmp_path)
    repo = target.sidecar_path
    ambiguous = _bundle()
    ambiguous_meta = PortableAgentMetadata(
        "athena.worker",
        "athena",
        ambiguous.metadata.artifact_timestamp,
        ambiguous.metadata.artifact_layout_version,
        ambiguous.metadata.fields,
    )
    ambiguous = AgentBundle(
        ambiguous_meta,
        ambiguous.commits,
        ambiguous.chat_bytes,
        _compute_bundle_digest(
            ambiguous_meta,
            ambiguous.commits,
            ambiguous.chat_bytes,
        ),
    )
    entry = _entry(ambiguous)
    write_bundle(repo, ambiguous)
    artifact_root = tmp_path / "artifacts"
    local = artifact_root / entry.artifact_timestamp
    local.mkdir(parents=True)
    (local / "agent_meta.json").write_text(
        json.dumps({"name": "worker"}),
        encoding="utf-8",
    )
    (local / "done.json").write_text(
        json.dumps({"name": "worker", "outcome": "completed"}),
        encoding="utf-8",
    )

    monkeypatch.setattr(bundles, "sase_home", lambda: tmp_path / "state")
    monkeypatch.setattr(
        bundles,
        "canonical_agent_artifact_path",
        lambda _project, _workflow, timestamp: artifact_root / timestamp,
    )
    monkeypatch.setattr(
        bundles,
        "iter_agent_artifact_dirs",
        lambda *_args, **_kwargs: iter(sorted(artifact_root.glob("*"))),
    )
    monkeypatch.setattr(
        bundles, "claim_imported_registered_name", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        bundles,
        "update_agent_artifact_index_for_marker_mutation",
        lambda _path: None,
    )

    skipped = bundles.integrate_foreign_bundles(
        target,
        repo,
        AgentsManifest((entry,)),
        LOCAL_OWNER,
    )
    assert skipped.integrated == 0
    assert skipped.unchanged == 1
    assert not (artifact_root / "20260722123457").exists()

    # Once the original artifact also carries matching durable commit
    # evidence, the group instead classifies owner-observed outright.
    (local / "commit_results.json").write_text(
        json.dumps([{"result": ambiguous.commits[0].sha[:9]}]),
        encoding="utf-8",
    )
    observed = bundles.integrate_foreign_bundles(
        target,
        repo,
        AgentsManifest((entry,)),
        LOCAL_OWNER,
    )
    assert observed.unchanged == 1
    assert observed.owner_observed_groups == 1
    assert observed.integrated == 0


def test_one_proven_entry_marks_the_whole_v1_group_owner_observed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    source_sha = "a1b2c3d4e" + "f" * 31
    entries: list[ManifestEntry] = []
    for index, role in enumerate(("plan", "code"), start=1):
        metadata = PortableAgentMetadata(
            f"athena.crew--{role}",
            "athena",
            f"2026072212345{index}",
            2,
        )
        commits = (CommitRecord(source_sha, role, index),)
        chat = f"{role}\n".encode()
        bundle = AgentBundle(
            metadata,
            commits,
            chat,
            _compute_bundle_digest(metadata, commits, chat),
        )
        entries.append(_entry(bundle))
        write_bundle(repo, bundle)

    local = tmp_path / entries[0].artifact_timestamp
    local.mkdir()
    (local / "commit_result.json").write_text(
        json.dumps({"result": source_sha[:9]}),
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

    counts = bundles.integrate_foreign_bundles(
        target,
        repo,
        AgentsManifest(tuple(entries)),
        LOCAL_OWNER,
    )

    assert counts.integrated == 0
    assert counts.unchanged == 2
    assert counts.owner_observed_groups == 1


def test_self_owned_entry_matching_a_local_artifact_is_never_reimported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fix 2 backstop.

    Commit proof is withheld so the group still classifies FOREIGN, but a
    local non-imported artifact matches the entry's timestamp and
    machine-qualified name. That entry must be skipped, not reimported.
    """

    target = _target(tmp_path)
    repo = target.sidecar_path
    meta = PortableAgentMetadata(
        "athena.worker",
        "athena",
        "20260722123456",
        2,
        (("model", "first"), ("workflow_name", "ace-run")),
    )
    commits = (CommitRecord("a" * 40, "subject", 100),)
    chat = b"chat\n"
    bundle = AgentBundle(
        meta, commits, chat, _compute_bundle_digest(meta, commits, chat)
    )
    entry = _entry(bundle)
    write_bundle(repo, bundle)

    artifact_root = tmp_path / "artifacts"
    local = artifact_root / entry.artifact_timestamp
    local.mkdir(parents=True)
    (local / "agent_meta.json").write_text(
        json.dumps({"name": "worker"}), encoding="utf-8"
    )
    # Deliberately withhold commit proof (no commit_results.json), so
    # proven_entry_count stays 0 and the group classifies FOREIGN.

    monkeypatch.setattr(bundles, "sase_home", lambda: tmp_path / "state")
    monkeypatch.setattr(
        bundles,
        "canonical_agent_artifact_path",
        lambda _project, _workflow, timestamp: artifact_root / timestamp,
    )
    monkeypatch.setattr(
        bundles,
        "iter_agent_artifact_dirs",
        lambda *_args, **_kwargs: iter(sorted(artifact_root.glob("*"))),
    )
    monkeypatch.setattr(
        bundles,
        "_create_imported_artifact",
        lambda *_args, **_kwargs: pytest.fail("self-owned entry was reimported"),
    )
    monkeypatch.setattr(
        bundles,
        "_refresh_imported_artifact",
        lambda *_args, **_kwargs: pytest.fail("self-owned entry was reimported"),
    )

    counts = bundles.integrate_foreign_bundles(
        target,
        repo,
        AgentsManifest((entry,)),
        LOCAL_OWNER,
    )

    assert counts.integrated == 0
    assert counts.refreshed == 0
    assert counts.unchanged == 1
    assert counts.owner_observed_groups == 0
    assert any("worker" in diagnostic for diagnostic in counts.diagnostics)


def test_v2_hood_coverage_marks_v1_group_owner_observed_without_artifact_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    foreign = _bundle()
    metadata = PortableAgentMetadata(
        "athena.worker",
        "athena",
        foreign.metadata.artifact_timestamp,
        foreign.metadata.artifact_layout_version,
        foreign.metadata.fields,
    )
    bundle = AgentBundle(
        metadata,
        foreign.commits,
        foreign.chat_bytes,
        _compute_bundle_digest(metadata, foreign.commits, foreign.chat_bytes),
    )
    entry = _entry(bundle)
    write_bundle(repo, bundle)
    monkeypatch.setattr(
        bundles,
        "_v1_artifact_rows",
        lambda _target: pytest.fail("v2 coverage should avoid an artifact scan"),
    )
    monkeypatch.setattr(
        bundles,
        "_create_imported_artifact",
        lambda *_args, **_kwargs: pytest.fail("owner group was imported"),
    )

    counts = bundles.integrate_foreign_bundles(
        target,
        repo,
        AgentsManifest((entry,)),
        LOCAL_OWNER,
        owner_v2_hoods={"worker"},
    )

    assert counts.integrated == 0
    assert counts.unchanged == 1
    assert counts.owner_observed_groups == 1
