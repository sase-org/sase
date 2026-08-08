"""Loader-compatible artifact, bundle, and saved-family rendering for v2 imports."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.agents_sync.models import ProjectTarget
from sase.core.agent_artifact_paths import ACE_RUN_WORKFLOW_DIR
from sase.core.agent_identity_facade import (
    AgentOwnerIdentity,
    AgentSourceOwnerIdentity,
    localize_imported_agent_name,
    parse_agent_family_name,
)
from sase.core.dismissed_agents_facade import validate_dismissed_agent_bundle
from sase.core.paths import sase_projects_dir

if TYPE_CHECKING:
    from sase.agents_sync.v2_import_types import (
        HoodPlan,
        PlannedContainer,
        PlannedRun,
    )


def artifact_payload(
    target: ProjectTarget,
    plan: HoodPlan,
    run: PlannedRun,
    family: PlannedContainer | None,
    clan: PlannedContainer | None,
    relationships: tuple[Mapping[str, Any], ...],
    chat_path: Path | None,
) -> dict[str, bytes]:
    """Render one portable source run as terminal local artifact markers."""

    record = run.payload.record
    metadata = dict(record.metadata)
    meta: dict[str, Any] = {
        key: metadata[key]
        for key in (
            "approve",
            "bead_id",
            "patch_name",
            "changespec_name",
            "cl_name",
            "epic_bead_id",
            "hidden",
            "llm_provider",
            "model",
            "output_variables",
            "phase_bead_id",
            "plan",
            "reasoning_effort",
            "role_suffix",
            "tribe",
            "vcs_provider",
            "workflow_name",
        )
        if key in metadata
    }
    meta.update(
        {
            "name": run.localized_name,
            "canonical_global_name": record.global_name,
            "imported_source_owner": {
                "username": plan.package.owner.username,
                "machine_name": plan.package.owner.machine_name,
            },
            "imported_source_run_id": record.source_run_id,
            "imported_snapshot_digest": plan.package.entry.digest,
            "imported_file_digests": {
                kind: reference.digest for kind, reference in record.files
            },
            "imported_transaction_key": plan.transaction_key,
            "historical_source_state": record.state,
            "stopped_at": (
                record.finished_at or record.dismissed_at or record.started_at
            ),
        }
    )
    if chat_path is not None:
        meta["chat_path"] = _local_path_string(chat_path)
    if family is not None:
        meta["agent_family"] = family.localized_name
        raw_role = metadata.get("agent_family_role")
        if isinstance(raw_role, str) and raw_role:
            meta["agent_family_role"] = raw_role
        else:
            parsed = parse_agent_family_name(run.localized_name)
            if parsed.member_role:
                meta["agent_family_role"] = parsed.member_role
    if clan is not None:
        meta["agent_clan"] = clan.localized_name
        generation = metadata.get("agent_clan_generation")
        meta["agent_clan_generation"] = (
            generation
            if isinstance(generation, str) and generation
            else plan.transaction_key
        )
        for key in ("clan_tribe", "clan_summary"):
            if key in metadata:
                meta[key] = metadata[key]
    _project_relationship_markers(plan, meta, relationships)

    done: dict[str, Any] = {
        "schema_version": 1,
        "status": "DONE",
        "name": run.localized_name,
        "timestamp": run.destination_id,
        "artifacts_timestamp": run.destination_id,
        "patch_name": _cl_name(target, metadata),
        "cl_name": _cl_name(target, metadata),
        "project_file": str(_project_file(target)),
        "outcome": _historical_outcome(record.state),
        "model": metadata.get("model"),
        "llm_provider": metadata.get("llm_provider"),
        "vcs_provider": metadata.get("vcs_provider"),
        "hidden": metadata.get("hidden") is True,
        "approve": metadata.get("approve") is True,
        "historical_source_state": record.state,
        "imported_source_owner": meta["imported_source_owner"],
        "imported_source_run_id": record.source_run_id,
        "imported_snapshot_digest": plan.package.entry.digest,
        "imported_transaction_key": plan.transaction_key,
        "finished_at": _source_datetime(
            record.finished_at or record.dismissed_at or record.started_at,
            run.destination_id,
        ).timestamp(),
    }
    if chat_path is not None:
        done["response_path"] = _local_path_string(chat_path)
    for key in (
        "retried_as_timestamp",
        "retry_chain_root_timestamp",
        "retry_error_category",
    ):
        if key in meta:
            done[key] = meta[key]

    files = {
        "agent_meta.json": json_bytes(meta),
        "done.json": json_bytes(done),
        "imported_commits.json": json_bytes(
            {
                "schema_version": 1,
                "source_run_id": record.source_run_id,
                "commits": [
                    commit.to_json_dict() for commit in run.payload.commits.commits
                ],
            }
        ),
    }
    prompt = run.payload.file_bytes("prompt")
    if prompt is not None:
        files["raw_xprompt.md"] = prompt
    embedded = run.payload.file_bytes("embedded_workflows")
    if embedded is not None:
        files["embedded_workflows.json"] = embedded
    prompt_steps = run.payload.file_bytes("prompt_steps")
    if prompt_steps is not None:
        for name, marker in _prompt_step_markers(prompt_steps):
            files[name] = json_bytes(marker)
    return files


def bundle_payload(
    target: ProjectTarget,
    plan: HoodPlan,
    run: PlannedRun,
    family: PlannedContainer | None,
    clan: PlannedContainer | None,
    relationships: tuple[Mapping[str, Any], ...],
    chat_path: Path | None,
) -> dict[str, Any]:
    """Render and validate one dismissed bundle for the real R loader."""

    record = run.payload.record
    metadata = dict(record.metadata)
    start = _source_datetime(record.started_at, run.destination_id)
    stop = _source_datetime(
        record.finished_at or record.dismissed_at or record.started_at,
        run.destination_id,
    )
    bundle: dict[str, Any] = {
        "agent_type": "run",
        "patch_name": _cl_name(target, metadata),
        "cl_name": _cl_name(target, metadata),
        "project_file": str(_project_file(target)),
        "status": _display_status(record.state),
        "start_time": start.isoformat(),
        "stop_time": stop.isoformat(),
        "workflow": ACE_RUN_WORKFLOW_DIR,
        "raw_suffix": run.destination_id,
        "agent_name": run.localized_name,
        "artifacts_dir": str(run.artifact_dir),
        "model": _optional_text(metadata.get("model")),
        "llm_provider": _optional_text(metadata.get("llm_provider")),
        "reasoning_effort": _optional_text(metadata.get("reasoning_effort")),
        "vcs_provider": _optional_text(metadata.get("vcs_provider")),
        "tribe": _optional_text(metadata.get("tribe")),
        "role_suffix": _optional_text(metadata.get("role_suffix")),
        "hidden": metadata.get("hidden") is True,
        "approve": metadata.get("approve") is True,
        "imported_source_owner": {
            "username": plan.package.owner.username,
            "machine_name": plan.package.owner.machine_name,
        },
        "imported_snapshot_digest": plan.package.entry.digest,
        "imported_transaction_key": plan.transaction_key,
        "step_output": {
            "meta_commits": [
                commit.to_json_dict() for commit in run.payload.commits.commits
            ],
            "imported_source_run_id": record.source_run_id,
        },
    }
    if chat_path is not None:
        bundle["response_path"] = _local_path_string(chat_path)
    if family is not None:
        bundle["agent_family"] = family.localized_name
        raw_role = _optional_text(metadata.get("agent_family_role"))
        if raw_role is None:
            raw_role = parse_agent_family_name(run.localized_name).member_role
        bundle["agent_family_role"] = raw_role
    if clan is not None:
        bundle["agent_clan"] = clan.localized_name
        bundle["agent_clan_generation"] = (
            _optional_text(metadata.get("agent_clan_generation")) or run.destination_id
        )
    for relation in relationships:
        kind = relation["kind"]
        target_id = relation["target"].get("destination_run_id")
        if kind == "workflow_parent" and isinstance(target_id, str):
            bundle["parent_timestamp"] = target_id
        elif kind == "retry" and isinstance(target_id, str):
            bundle["retry_of_timestamp"] = target_id

    validate_dismissed_agent_bundle(bundle)
    return bundle


def saved_family_group(
    target: ProjectTarget,
    plan: HoodPlan,
    container: PlannedContainer,
    member_ids: tuple[str, ...],
    bundles: dict[str, dict[str, Any]],
    bundle_paths: dict[str, Path],
) -> dict[str, Any]:
    """Render one stable saved-family archive record in source member order."""

    refs: list[dict[str, Any]] = []
    for source_id in member_ids:
        bundle = bundles[source_id]
        prompt = _plan_run(plan, source_id).payload.file_bytes("prompt")
        refs.append(
            {
                "agent_type": bundle["agent_type"],
                "patch_name": bundle.get("patch_name"),
                "cl_name": bundle["cl_name"],
                "raw_suffix": bundle["raw_suffix"],
                "bundle_path": str(bundle_paths[source_id]),
                "is_workflow_child": False,
                "parent_timestamp": bundle.get("parent_timestamp"),
                "display_name": bundle["agent_name"],
                "agent_name": bundle["agent_name"],
                "status": bundle["status"],
                "start_time": bundle["start_time"],
                "model": bundle.get("model"),
                "llm_provider": bundle.get("llm_provider"),
                "reasoning_effort": bundle.get("reasoning_effort"),
                "tribe": bundle.get("tribe"),
                "prompt_preview": _prompt_preview(prompt),
                "source_run_id": source_id,
            }
        )
    status_counts = dict(
        sorted(
            Counter(
                str(bundles[source_id]["status"]) for source_id in member_ids
            ).items()
        )
    )
    return {
        "schema_version": 2,
        "group_id": family_group_id(container.record.global_name),
        "created_at": _group_created_at(
            tuple(bundles[source_id] for source_id in member_ids)
        ),
        "source": "agents_sidecar",
        "title": f"{len(member_ids)} agents in {container.localized_name}",
        "name": container.localized_name,
        "agent_count": len(member_ids),
        "top_level_agent_count": len(member_ids),
        "status_counts": status_counts,
        "project_names": [target.project],
        "cl_names": sorted(
            {
                str(bundles[source_id]["cl_name"])
                for source_id in member_ids
                if bundles[source_id]["cl_name"] != "unknown"
            }
        ),
        "agent_refs": refs,
        "revived_at": None,
        "times_revived": 0,
        "canonical_global_family": container.record.global_name,
        "source_snapshot_digest": plan.package.entry.digest,
    }


def family_group_id(global_family: str) -> str:
    digest = hashlib.sha256(global_family.encode()).hexdigest()[:32]
    return f"agents-sidecar-{digest}"


def _project_relationship_markers(
    plan: HoodPlan,
    meta: dict[str, Any],
    relationships: tuple[Mapping[str, Any], ...],
) -> None:
    by_source = {run.payload.record.source_run_id: run for run in plan.runs}
    waits: list[str] = []
    for relation in relationships:
        kind = str(relation["kind"])
        target = relation["target"]
        target_id = target.get("destination_run_id")
        target_source_id = target.get("source_run_id")
        target_run = (
            by_source.get(str(target_source_id))
            if target_source_id is not None
            else None
        )
        target_name = (
            target_run.localized_name
            if target_run is not None
            else _localized_external_target(target, plan)
        )
        if kind == "parent":
            if isinstance(target_id, str):
                meta["parent_agent_timestamp"] = target_id
            if target_name:
                meta["parent_agent_name"] = target_name
        elif kind == "workflow_parent" and isinstance(target_id, str):
            meta["parent_timestamp"] = target_id
        elif kind == "retry" and isinstance(target_id, str):
            meta["retry_of_timestamp"] = target_id
        elif kind == "wait" and target_name:
            waits.append(target_name)
    if waits:
        meta["wait_for"] = list(dict.fromkeys(waits))
    source_id = meta.get("imported_source_run_id")
    for relation in plan.relationships:
        target = relation["target"]
        if relation["kind"] == "retry" and target.get("source_run_id") == source_id:
            child = by_source.get(str(relation["source_run_id"]))
            if child is not None:
                meta["retried_as_timestamp"] = child.destination_id


def _localized_external_target(
    target: Mapping[str, Any],
    plan: HoodPlan,
) -> str | None:
    global_name = target.get("global_name")
    owner = target.get("owner")
    if not isinstance(global_name, str) or not isinstance(owner, Mapping):
        return None
    username = owner.get("username")
    machine = owner.get("machine_name")
    if not isinstance(username, str) or not isinstance(machine, str):
        return None
    return localize_imported_agent_name(
        global_name,
        AgentSourceOwnerIdentity.v2(AgentOwnerIdentity(username, machine)),
        plan.identity,
    )


def _project_file(target: ProjectTarget) -> Path:
    return sase_projects_dir() / target.project_key / f"{target.project_key}.sase"


def _source_datetime(value: str | None, fallback: str) -> datetime:
    return _parse_datetime(value) or datetime.strptime(
        fallback, "%Y%m%d%H%M%S"
    ).replace(tzinfo=UTC)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    if len(value) == 14 and value.isdigit():
        try:
            return datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
        except ValueError:
            return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC)


def _historical_outcome(state: str) -> str:
    if state == "failed":
        return "failed"
    if state in {"active", "waiting", "stopped"}:
        return "stopped"
    return "completed"


def _display_status(state: str) -> str:
    if state == "failed":
        return "FAILED"
    if state in {"active", "waiting", "stopped"}:
        return "STOPPED"
    return "DONE"


def _cl_name(target: ProjectTarget, metadata: Mapping[str, Any]) -> str:
    return (
        _optional_text(metadata.get("patch_name"))
        or _optional_text(metadata.get("changespec_name"))
        or _optional_text(metadata.get("cl_name"))
        or target.project_key
    )


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _local_path_string(path: Path) -> str:
    try:
        return f"~/{path.resolve().relative_to(Path.home().resolve())}"
    except ValueError:
        return str(path)


def _prompt_step_markers(payload: bytes) -> tuple[tuple[str, dict[str, Any]], ...]:
    value = json.loads(payload.decode("utf-8"))
    assert isinstance(value, list)
    return tuple((str(row["file_name"]), dict(row["marker"])) for row in value)


def _prompt_preview(payload: bytes | None) -> str | None:
    if payload is None:
        return None
    preview = " ".join(payload.decode("utf-8").strip().split())
    if not preview:
        return None
    return preview if len(preview) <= 120 else preview[:117].rstrip() + "..."


def _group_created_at(bundles: tuple[dict[str, Any], ...]) -> str:
    values = [
        value
        for bundle in bundles
        if isinstance((value := bundle.get("stop_time")), str)
    ]
    return max(values) if values else datetime.now(UTC).isoformat()


def _plan_run(plan: HoodPlan, source_id: str) -> PlannedRun:
    for run in plan.runs:
        if run.payload.record.source_run_id == source_id:
            return run
    raise KeyError(source_id)


def json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


__all__ = [
    "artifact_payload",
    "bundle_payload",
    "family_group_id",
    "json_bytes",
    "saved_family_group",
]
