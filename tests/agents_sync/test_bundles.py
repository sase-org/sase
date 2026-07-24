from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from sase.agents_sync import bundles
from sase.agents_sync.io import compute_bundle_digest, write_bundle
from sase.agents_sync.models import (
    AgentBundle,
    AgentsManifest,
    CommitRecord,
    ManifestEntry,
    PortableAgentMetadata,
    ProjectTarget,
)


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
    return AgentBundle(meta, commits, chat, compute_bundle_digest(meta, commits, chat))


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
        lambda name, machine, path, digest: claims.append(
            (name, machine, Path(path), digest)
        ),
    )
    indexed: list[Path] = []
    monkeypatch.setattr(
        bundles,
        "update_agent_artifact_index_for_marker_mutation",
        lambda path: indexed.append(Path(path)),
    )

    counts = bundles.integrate_foreign_bundles(target, repo, manifest, "athena")
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

    unchanged = bundles.integrate_foreign_bundles(target, repo, manifest, "athena")
    assert unchanged.unchanged == 1
    assert len(claims) == 1

    refreshed_bundle = _bundle(model="second", chat=b"new chat\n")
    refreshed_manifest = AgentsManifest((_entry(refreshed_bundle),))
    write_bundle(repo, refreshed_bundle)
    refreshed = bundles.integrate_foreign_bundles(
        target, repo, refreshed_manifest, "athena"
    )
    assert refreshed.refreshed == 1
    refreshed_meta = json.loads((artifact / "agent_meta.json").read_text())
    assert refreshed_meta["model"] == "second"
    assert Path(refreshed_meta["chat_path"]).read_bytes() == b"new chat\n"


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

    bundles.integrate_foreign_bundles(target, repo, manifest, "athena")

    assert (artifact_root / "20260722123457" / "done.json").is_file()


def test_same_machine_v1_requires_local_commit_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
        compute_bundle_digest(
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

    imported = bundles.integrate_foreign_bundles(
        target,
        repo,
        AgentsManifest((entry,)),
        "athena",
    )
    assert imported.integrated == 1
    imported_meta = json.loads(
        (artifact_root / "20260722123457" / "agent_meta.json").read_text()
    )
    assert imported_meta["imported_owner_kind"] == "username_unknown_v1"

    # Once the original artifact carries matching durable commit evidence,
    # the same v1 entry is only observed and is not duplicated again.
    (local / "commit_results.json").write_text(
        json.dumps([{"result": ambiguous.commits[0].sha}]),
        encoding="utf-8",
    )
    (artifact_root / "20260722123457" / "agent_meta.json").unlink()
    (artifact_root / "20260722123457" / "done.json").unlink()
    observed = bundles.integrate_foreign_bundles(
        target,
        repo,
        AgentsManifest((entry,)),
        "athena",
    )
    assert observed.unchanged == 1
    assert observed.integrated == 0


def test_local_bundle_uses_legacy_footer_backfill_and_allowlists_meta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _target(tmp_path)
    artifact = tmp_path / "20260722123456"
    artifact.mkdir()
    chat = tmp_path / "chat.md"
    chat.write_bytes(b"transcript")
    (artifact / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "worker",
                "model": "gpt-test",
                "pid": 999,
                "workspace_dir": "/private/workspace",
                "chat_path": str(chat),
            }
        )
    )
    (artifact / "done.json").write_text(json.dumps({"outcome": "completed"}))
    sha = "b" * 40
    log_output = (
        f"{sha}\x00100\x00subject\x00subject\n\n"
        "SASE_AGENT=worker\nSASE_MACHINE=legacy-host\x00"
    )

    def runner(
        _cwd: Path, args: list[str], *, network: bool = False, op: str = ""
    ) -> subprocess.CompletedProcess[str]:
        del network, op
        if args[0] == "log":
            return subprocess.CompletedProcess(args, 0, log_output, "")
        return subprocess.CompletedProcess(args, 1, "", "unused")

    monkeypatch.setattr(
        bundles,
        "iter_agent_artifact_dirs",
        lambda *_args, **_kwargs: iter((artifact,)),
    )
    monkeypatch.setattr(
        bundles,
        "parse_agent_artifact_path",
        lambda _path: SimpleNamespace(timestamp="20260722123456", layout_version=2),
    )
    built, skipped, diagnostics = bundles._build_local_bundles(
        target, "athena", git_runner=runner, incremental_only=False
    )

    assert skipped == 0
    assert diagnostics == []
    exported = built["athena.worker"]
    assert exported.commits == (CommitRecord(sha, "subject", 100),)
    portable = exported.metadata.to_json_dict()
    assert portable["model"] == "gpt-test"
    assert "pid" not in portable
    assert "workspace_dir" not in portable


def test_historical_footer_classification_accepts_legacy_and_local_modern_only(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    legacy_sha = "a" * 40
    local_sha = "b" * 40
    foreign_sha = "c" * 40
    log_output = "".join(
        (
            f"{legacy_sha}\x00100\x00legacy\x00legacy\n\n"
            "SASE_AGENT=worker\nSASE_MACHINE=old-host\x00",
            f"{local_sha}\x00200\x00local\x00local\n\n"
            "SASE_AGENT=athena.builder\nSASE_MACHINE=athena\x00",
            f"{foreign_sha}\x00300\x00foreign\x00foreign\n\n"
            "SASE_AGENT=zeus.reviewer\nSASE_MACHINE=zeus\x00",
        )
    )

    def runner(
        _cwd: Path, args: list[str], *, network: bool = False, op: str = ""
    ) -> subprocess.CompletedProcess[str]:
        del network, op
        assert args[0] == "log"
        return subprocess.CompletedProcess(args, 0, log_output, "")

    associations = bundles._historical_commit_associations(
        target,
        "athena",
        runner,
    )

    assert associations == [
        ("athena.worker", CommitRecord(legacy_sha, "legacy", 100)),
        ("athena.builder", CommitRecord(local_sha, "local", 200)),
    ]
