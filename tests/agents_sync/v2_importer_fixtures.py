"""Shared builders and isolated local state for v2 importer tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace import dismissed_agents
from sase.agents_sync import v2_import_history
from sase.agents_sync import v2_import_planning
from sase.agents_sync import v2_import_rendering
from sase.agents_sync import v2_import_storage
from sase.agents_sync import v2_import_transactions
from sase.agents_sync.inventory import InventoryRun, ProjectHoodInventory
from sase.agents_sync.models import CommitRecord, ProjectTarget
from sase.agents_sync.publication import publish_agent_hood
from sase.agents_sync.v2_import_package import (
    ValidatedV2HoodPackage,
    discover_agent_imports,
)
from sase.agents_sync.v2_models import V2ProjectIdentity
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity


SOURCE_OWNER = AgentOwnerIdentity("bob", "zeus")
LOCAL_OWNER = AgentOwnerIdentity("alice", "athena")
PROJECT = V2ProjectIdentity("proj", "Project")


def make_target(tmp_path: Path) -> ProjectTarget:
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


def _run(
    name: str,
    suffix: str,
    *,
    state: str,
    chat: bytes | None,
    owner: AgentOwnerIdentity = SOURCE_OWNER,
) -> InventoryRun:
    finished_at = None if state == "active" else "2026-07-24T12:01:00+00:00"
    output_variables = (
        (("output_variables", {"plan_file": "plans/crew.md"}),) if suffix == "1" else ()
    )
    return InventoryRun(
        f"source-{suffix}",
        name,
        f"{owner.username}.{owner.machine_name}.{name}",
        state,
        "2026-07-24T12:00:00+00:00",
        finished_at,
        None,
        (
            ("agent_family", "crew"),
            ("agent_family_role", name.rsplit("--", 1)[-1]),
            ("llm_provider", "codex"),
            ("model", "gpt-test"),
            *output_variables,
            ("reasoning_effort", "high"),
            ("tribe", "backend"),
        ),
        (CommitRecord(suffix * 40, name, 1),),
        f"prompt {name}\n".encode(),
        chat,
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


def published_package(
    tmp_path: Path,
    *,
    owner: AgentOwnerIdentity = SOURCE_OWNER,
) -> tuple[ProjectTarget, ValidatedV2HoodPackage]:
    target = make_target(tmp_path)
    target.sidecar_path.mkdir()
    inventory = ProjectHoodInventory(
        owner,
        PROJECT.key,
        (
            _run(
                "crew--plan",
                "1",
                state="completed",
                chat=b"plan chat\n",
                owner=owner,
            ),
            _run(
                "crew--code",
                "2",
                state="active",
                chat=None,
                owner=owner,
            ),
        ),
    )
    publish_agent_hood(
        target,
        target.sidecar_path,
        "crew--plan",
        identity=AgentIdentitySnapshot(owner),
        inventory=inventory,
    )
    discovery = discover_agent_imports(target.sidecar_path, PROJECT)
    assert discovery.diagnostics == ()
    return target, discovery.v2_packages[0]


def isolate_local_state(
    tmp_path: Path,
    target: ProjectTarget,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, list[tuple[object, ...]]]:
    state = tmp_path / "state"
    projects = state / "projects"
    artifact_root = projects / target.project_key / "artifacts" / "ace-run"
    bundles = state / "dismissed_bundles"
    groups = state / "dismissed_agent_groups"
    claims: list[tuple[object, ...]] = []

    monkeypatch.setattr(v2_import_storage, "sase_home", lambda: state)
    monkeypatch.setattr(v2_import_storage, "sase_projects_dir", lambda: projects)
    monkeypatch.setattr(v2_import_transactions, "sase_home", lambda: state)
    monkeypatch.setattr(v2_import_transactions, "sase_projects_dir", lambda: projects)
    monkeypatch.setattr(v2_import_rendering, "sase_projects_dir", lambda: projects)
    monkeypatch.setattr(
        v2_import_history,
        "canonical_agent_artifact_path",
        lambda _project, _workflow, timestamp: artifact_root / timestamp,
    )
    monkeypatch.setattr(
        v2_import_planning,
        "canonical_agent_artifact_path",
        lambda _project, _workflow, timestamp: artifact_root / timestamp,
    )
    monkeypatch.setattr(
        v2_import_history,
        "iter_agent_artifact_dirs",
        lambda *_args, **_kwargs: iter(sorted(artifact_root.glob("*"))),
    )
    monkeypatch.setattr(
        v2_import_planning,
        "iter_agent_artifact_dirs",
        lambda *_args, **_kwargs: iter(sorted(artifact_root.glob("*"))),
    )
    monkeypatch.setattr(
        v2_import_planning,
        "preflight_imported_registered_names_v2",
        lambda rows, **_kwargs: claims.append(("preflight", *rows)),
    )
    monkeypatch.setattr(
        v2_import_transactions,
        "claim_imported_registered_names_v2",
        lambda rows, **_kwargs: claims.append(("claim", *rows)),
    )
    monkeypatch.setattr(
        v2_import_transactions,
        "update_agent_artifact_index_for_marker_mutation",
        lambda _path: None,
    )
    monkeypatch.setattr(
        v2_import_transactions,
        "sync_dismissed_agent_artifact_index",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(v2_import_storage, "dismissed_bundles_dir", lambda: bundles)
    monkeypatch.setattr(v2_import_storage, "dismissed_groups_dir", lambda: groups)
    monkeypatch.setattr(
        dismissed_agents,
        "_DISMISSED_AGENTS_FILE",
        state / "dismissed_agents.json",
    )
    monkeypatch.setattr(
        v2_import_transactions, "dismissed_bundles_dir", lambda: bundles
    )
    monkeypatch.setattr(v2_import_transactions, "dismissed_groups_dir", lambda: groups)
    monkeypatch.setattr(
        dismissed_agents,
        "rebuild_dismissed_bundle_index",
        lambda: None,
    )
    return artifact_root, groups, claims
