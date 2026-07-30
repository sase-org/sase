from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from sase.agents_sync.inventory import InventoryRun, ProjectHoodInventory
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.models import CommitRecord, ProjectTarget
from sase.agents_sync.publication import publish_agent_hood
from sase.agents_sync.v2_import_package import (
    _validate_v2_hood_package,
    discover_agent_imports,
)
from sase.agents_sync.v2_io import (
    content_digest,
    read_owner_manifest,
    v2_json_bytes,
)
from sase.agents_sync.v2_models import V2ProjectIdentity
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity


OWNER = AgentOwnerIdentity("bob", "zeus")
PROJECT = V2ProjectIdentity("proj", "Project")


def _target(tmp_path: Path) -> ProjectTarget:
    primary = tmp_path / "primary"
    primary.mkdir()
    return ProjectTarget(
        PROJECT.key,
        PROJECT.name,
        primary,
        (primary.resolve(),),
        tmp_path / "sidecar",
        "unused",
    )


def _run(name: str, suffix: str) -> InventoryRun:
    return InventoryRun(
        f"run-{suffix}",
        name,
        f"{OWNER.username}.{OWNER.machine_name}.{name}",
        "completed",
        "2026-07-24T12:00:00+00:00",
        "2026-07-24T12:01:00+00:00",
        None,
        (("model", "gpt"),),
        (CommitRecord(suffix * 40, name, 1),),
        f"prompt {name}\n".encode(),
        b"chat\n",
        "crew",
        None,
        (),
        f"2026072412000{suffix}",
        b'[{"args":{},"name":"propose","tags":["rollover"]}]\n',
        (
            b'[{"file_name":"prompt_step_0.json","marker":'
            b'{"status":"completed","step_index":0}}]\n'
        ),
    )


def _publish(tmp_path: Path) -> tuple[ProjectTarget, Path]:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    inventory = ProjectHoodInventory(
        OWNER,
        PROJECT.key,
        (_run("crew--plan", "1"), _run("crew--code", "2")),
    )
    publish_agent_hood(
        target,
        repo,
        "crew--plan",
        identity=AgentIdentitySnapshot(OWNER),
        inventory=inventory,
    )
    return target, repo


def test_discovery_validates_complete_optional_restart_payloads(
    tmp_path: Path,
) -> None:
    _target_value, repo = _publish(tmp_path)

    discovery = discover_agent_imports(repo, PROJECT)

    assert discovery.diagnostics == ()
    assert len(discovery.v2_packages) == 1
    package = discovery.v2_packages[0]
    assert package.hood == "crew"
    assert package.runs[0].file_bytes("embedded_workflows") is not None
    assert package.runs[0].file_bytes("prompt_steps") is not None


def test_import_package_preserves_family_container_commits(tmp_path: Path) -> None:
    _target_value, repo = _publish(tmp_path)
    manifest = read_owner_manifest(repo, OWNER, PROJECT)
    hood, entry = manifest.hoods[0]
    snapshot_path = (
        repo
        / "users"
        / OWNER.username
        / "machines"
        / OWNER.machine_name
        / "hoods"
        / hood
        / "snapshot.json"
    )
    snapshot = json.loads(snapshot_path.read_bytes())
    lane_commit = CommitRecord("f" * 40, "lane commit", 3)
    snapshot["containers"][0]["commits"] = [lane_commit.to_json_dict()]
    snapshot_bytes = v2_json_bytes(snapshot)
    snapshot_path.write_bytes(snapshot_bytes)

    package = _validate_v2_hood_package(
        repo,
        manifest,
        hood,
        replace(entry, digest=content_digest(snapshot_bytes)),
    )

    assert package.snapshot.containers[0].commits == (lane_commit,)


def test_whole_hood_rejects_referenced_digest_mismatch(
    tmp_path: Path,
) -> None:
    _target_value, repo = _publish(tmp_path)
    manifest = read_owner_manifest(repo, OWNER, PROJECT)
    hood, entry = manifest.hoods[0]
    meta_path = repo / "agents" / f"{OWNER.username}.{OWNER.machine_name}.crew--plan"
    payload = (meta_path / "meta.json").read_bytes()
    (meta_path / "meta.json").write_bytes(b"[" + payload[1:])

    with pytest.raises(AgentsSyncFormatError, match="digest mismatch"):
        _validate_v2_hood_package(repo, manifest, hood, entry)


def test_whole_hood_rejects_extra_manifest_reference(
    tmp_path: Path,
) -> None:
    _target_value, repo = _publish(tmp_path)
    manifest = read_owner_manifest(repo, OWNER, PROJECT)
    hood, entry = manifest.hoods[0]
    malformed = replace(entry, files=(*entry.files, "extra.txt"))

    with pytest.raises(AgentsSyncFormatError, match="file set"):
        _validate_v2_hood_package(repo, manifest, hood, malformed)
