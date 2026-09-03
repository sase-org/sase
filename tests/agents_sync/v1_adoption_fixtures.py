"""Shared ``wedged_machine`` fixture builder for v1-to-v2 adoption tests."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

import pytest

from sase.agents_sync.inventory import InventoryRun, ProjectHoodInventory
from sase.agents_sync.inventory_io import source_run_id
from sase.agents_sync.models import CommitRecord, ProjectTarget
from sase.agents_sync.publication import publish_agent_hood
from sase.agents_sync.v2_import_package import (
    ValidatedV2HoodPackage,
    discover_agent_imports,
)
from sase.core.agent_artifact_paths import ACE_RUN_WORKFLOW_DIR
from sase.core.agent_identity_facade import AgentIdentitySnapshot
from sase.core.agent_types import AgentType
from sase.core.dismissed_agents_facade import persist_dismissed_agents

from tests.agents_sync.v2_importer_fixtures import (
    LOCAL_OWNER,
    PROJECT,
    SOURCE_OWNER,
    isolate_local_state,
    make_target,
)

DURABLE_TIMESTAMP = "20260601120000"
V1_NAME = "zeus.crew--plan"
LOCAL_NAME = "crew--plan"
CHAT_BYTES = b"plan chat\n"
V1_CL_NAME = "unknown"


@dataclass(frozen=True, slots=True)
class WedgedMachine:
    """Everything one v1-adoption test needs, isolated in ``tmp_path``."""

    target: ProjectTarget
    package: ValidatedV2HoodPackage
    artifact_root: Path
    groups_dir: Path
    bundles_dir: Path
    claims: list[tuple[object, ...]]
    v1_artifact_dir: Path
    v1_chat_path: Path
    v1_bundle_path: Path
    durable: str


def wedged_machine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    durable: str = DURABLE_TIMESTAMP,
    v2_chat_bytes: bytes | None = CHAT_BYTES,
) -> WedgedMachine:
    """Seed a published v2 hood plus the matching v1 state a wedged machine holds."""

    target = make_target(tmp_path)
    target.sidecar_path.mkdir()
    artifact_root, groups_dir, claims = isolate_local_state(
        tmp_path, target, monkeypatch
    )
    bundles_dir = tmp_path / "state" / "dismissed_bundles"

    expected_source_run_id = source_run_id(PROJECT.key, ACE_RUN_WORKFLOW_DIR, durable)
    run = InventoryRun(
        expected_source_run_id,
        LOCAL_NAME,
        f"{SOURCE_OWNER.username}.{SOURCE_OWNER.machine_name}.{LOCAL_NAME}",
        "completed",
        "2026-07-24T12:00:00+00:00",
        "2026-07-24T12:01:00+00:00",
        None,
        (
            ("llm_provider", "codex"),
            ("model", "gpt-test"),
        ),
        (CommitRecord("a" * 40, LOCAL_NAME, 1),),
        f"prompt {LOCAL_NAME}\n".encode(),
        v2_chat_bytes,
        None,
        None,
        (),
        durable,
    )
    inventory = ProjectHoodInventory(
        SOURCE_OWNER,
        PROJECT.key,
        (run,),
    )
    publish_agent_hood(
        target,
        target.sidecar_path,
        LOCAL_NAME,
        identity=AgentIdentitySnapshot(SOURCE_OWNER),
        inventory=inventory,
    )
    discovery = discover_agent_imports(target.sidecar_path, PROJECT)
    assert discovery.diagnostics == ()
    package = discovery.v2_packages[0]

    v1_artifact_dir = artifact_root / durable
    v1_artifact_dir.mkdir(parents=True)
    v1_chat_path = (
        tmp_path / "state" / "chats" / durable[:6] / f"imported-{V1_NAME}-{durable}.md"
    )
    v1_chat_path.parent.mkdir(parents=True, exist_ok=True)
    v1_chat_path.write_bytes(CHAT_BYTES)
    (v1_artifact_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": V1_NAME,
                "model": "gpt-test",
                "chat_path": str(v1_chat_path),
                "imported_from_machine": SOURCE_OWNER.machine_name,
                "imported_owner_kind": "username_unknown_v1",
                "imported_digest": "c" * 64,
            }
        ),
        encoding="utf-8",
    )

    v1_bundle_path = bundles_dir / durable[:6] / f"{durable}.json"
    v1_bundle_path.parent.mkdir(parents=True, exist_ok=True)
    v1_bundle_path.write_text(
        json.dumps(
            {
                "agent_type": "run",
                "patch_name": V1_CL_NAME,
                "cl_name": V1_CL_NAME,
                "project_file": str(target.sidecar_path / f"{PROJECT.key}.sase"),
                "status": "DONE",
                "start_time": "2026-07-24T12:00:00+00:00",
                "stop_time": "2026-07-24T12:01:00+00:00",
                "workflow": ACE_RUN_WORKFLOW_DIR,
                "raw_suffix": durable,
                "agent_name": V1_NAME,
                "artifacts_dir": str(v1_artifact_dir),
            }
        ),
        encoding="utf-8",
    )
    persist_dismissed_agents({(AgentType.RUNNING, V1_CL_NAME, durable)})

    return WedgedMachine(
        target,
        package,
        artifact_root,
        groups_dir,
        bundles_dir,
        claims,
        v1_artifact_dir,
        v1_chat_path,
        v1_bundle_path,
        durable,
    )


__all__ = [
    "CHAT_BYTES",
    "DURABLE_TIMESTAMP",
    "LOCAL_OWNER",
    "V1_NAME",
    "WedgedMachine",
    "wedged_machine",
]
