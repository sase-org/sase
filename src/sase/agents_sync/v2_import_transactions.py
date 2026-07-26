"""Preparation, application, and recovery of v2 import transactions."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import re
import shutil
from typing import Any

from sase.agent.names import (
    ImportedV2RegistryClaim,
    claim_imported_registered_names_v2,
)
from sase.agents_sync.io import AgentsSyncFormatError, atomic_write_bytes
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.v2_import_history import read_json_object
from sase.agents_sync.v2_import_rendering import (
    artifact_payload,
    bundle_payload,
    family_group_id,
    json_bytes,
    saved_family_group,
)
from sase.agents_sync.v2_import_storage import (
    JOURNAL_SCHEMA_VERSION,
    destination_path,
    dismissed_bundles_dir,
    dismissed_groups_dir,
    imports_root,
    journal_path,
    journals_dir,
    read_journal,
    stage_dir_from_journal,
    stage_file,
    write_journal,
)
from sase.agents_sync.v2_import_types import HoodPlan, PlannedContainer, PlannedRun
from sase.agents_sync.v2_io import content_digest, validate_relative_path
from sase.core.agent_artifact_index_lifecycle import (
    sync_dismissed_agent_artifact_index,
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.agent_identity_facade import AgentIdentitySnapshot
from sase.core.agent_types import AgentType
from sase.core.dismissed_agents_facade import (
    archive_index_exists,
    load_dismissed_agents,
    persist_dismissed_agents as save_dismissed_agents,
    rebuild_dismissed_bundle_index,
    upsert_bundle_summary,
)
from sase.core.paths import sase_home, sase_projects_dir

DismissedIdentity = tuple[AgentType, str, str | None]


def recover_v2_import_transactions(
    target: ProjectTarget,
    *,
    identity: AgentIdentitySnapshot,
) -> tuple[str, ...]:
    """Roll back prepared journals and finish interrupted applied transactions."""

    diagnostics: list[str] = []
    journals = journals_dir(target.project_key)
    if not journals.is_dir():
        return ()
    for path in sorted(journals.glob("*.json"), key=lambda item: item.name):
        try:
            journal = read_journal(path)
            state = journal["state"]
            if state == "complete":
                continue
            if state == "prepared":
                shutil.rmtree(
                    stage_dir_from_journal(target, journal), ignore_errors=True
                )
                path.unlink(missing_ok=True)
                continue
            apply_and_finalize_transaction(target, path, identity)
        except Exception as exc:  # noqa: BLE001 - preserve other recoveries
            diagnostics.append(f"{path.name}: import recovery failed: {exc}")
    return tuple(diagnostics)


def prepare_transaction(target: ProjectTarget, plan: HoodPlan) -> None:
    root = imports_root(target.project_key)
    root.mkdir(parents=True, exist_ok=True)
    stage = root / "staging" / plan.transaction_key
    transaction_journal = journal_path(target.project_key, plan.transaction_key)
    if transaction_journal.is_file():
        existing_journal = read_journal(transaction_journal)
        if existing_journal.get("state") == "complete":
            return
        if existing_journal.get("state") != "prepared":
            return
        shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True, exist_ok=True)

    files: list[dict[str, str]] = []
    groups: list[dict[str, str]] = []
    family_by_member = _containers_by_member(plan, kind="family")
    clan_by_member = _containers_by_member(plan, kind="clan")
    relationships = _relationships_by_source(plan)
    project_root = sase_projects_dir() / target.project_key

    bundle_locations: dict[str, Path] = {}
    bundle_payloads: dict[str, dict[str, Any]] = {}
    dismissed_identities: list[dict[str, str | None]] = []
    chat_paths: dict[str, Path | None] = {}
    for run in plan.changed_runs:
        record = run.payload.record
        artifact_relative = _artifact_relative(project_root, run.artifact_dir)
        chat_path = _chat_path(run)
        chat_payload = run.payload.file_bytes("chat")
        if chat_payload is not None:
            stage_file(
                stage,
                files,
                "state",
                chat_path.relative_to(sase_home()).as_posix(),
                chat_payload,
            )

        marker_files = artifact_payload(
            target,
            plan,
            run,
            family_by_member.get(record.source_run_id),
            clan_by_member.get(record.source_run_id),
            relationships.get(record.source_run_id, ()),
            chat_path if chat_payload is not None else None,
        )
        chat_paths[record.source_run_id] = (
            chat_path if chat_payload is not None else None
        )
        for name, payload in marker_files.items():
            stage_file(
                stage,
                files,
                "project",
                f"{artifact_relative}/{name}",
                payload,
            )

    # Saved families must include every source member in snapshot order,
    # including exact-current-owner observations that did not need a new
    # historical artifact.
    for run in plan.runs:
        record = run.payload.record
        bundle_chat_path: Path | None = chat_paths.get(record.source_run_id)
        if run.disposition == "observed":
            bundle_chat_path = _existing_chat_path(run.artifact_dir)
        bundle = bundle_payload(
            target,
            plan,
            run,
            family_by_member.get(record.source_run_id),
            clan_by_member.get(record.source_run_id),
            relationships.get(record.source_run_id, ()),
            bundle_chat_path,
        )
        bundle_relative = f"{run.destination_id[:6]}/{run.destination_id}.json"
        bundle_destination = dismissed_bundles_dir() / bundle_relative
        bundle_locations[record.source_run_id] = bundle_destination
        bundle_payloads[record.source_run_id] = bundle
        dismissed_identities.append(_dismissed_identity_row(bundle))
        stage_file(
            stage,
            files,
            "bundles",
            bundle_relative,
            json_bytes(bundle),
        )

    for container in plan.containers:
        if container.record.kind != "family":
            continue
        member_ids = tuple(
            source_id
            for source_id in container.record.member_source_run_ids
            if source_id in bundle_payloads
        )
        if not member_ids:
            continue
        group_id = family_group_id(container.record.global_name)
        group = saved_family_group(
            target,
            plan,
            container,
            member_ids,
            bundle_payloads,
            bundle_locations,
        )
        existing_group = read_json_object(dismissed_groups_dir() / f"{group_id}.json")
        if existing_group is not None:
            revived_at = existing_group.get("revived_at")
            times_revived = existing_group.get("times_revived")
            if isinstance(revived_at, str) and revived_at:
                group["revived_at"] = revived_at
            if isinstance(times_revived, int) and not isinstance(times_revived, bool):
                group["times_revived"] = max(0, times_revived)
        stage_file(
            stage,
            groups,
            "groups",
            f"{group_id}.json",
            json_bytes(group),
        )

    claims = [
        {
            "source_username": claim.source_owner.username,
            "source_machine": claim.source_owner.machine_name,
            "canonical_global_name": claim.canonical_global_name,
            "localized_name": claim.localized_name,
            "artifact_relative": _artifact_relative(
                project_root,
                Path(claim.claiming_dir),
            ),
            "digest": claim.digest,
            "container_kind": claim.container_kind,
            "clan_generation": claim.clan_generation,
        }
        for claim in plan.registry_claims
    ]
    journal: dict[str, Any] = {
        "schema_version": JOURNAL_SCHEMA_VERSION,
        "transaction_key": plan.transaction_key,
        "project_key": target.project_key,
        "source_owner": {
            "username": plan.package.owner.username,
            "machine_name": plan.package.owner.machine_name,
        },
        "hood": plan.package.hood,
        "snapshot_digest": plan.package.entry.digest,
        "state": "prepared",
        "stage_relative": f"staging/{plan.transaction_key}",
        "files": files,
        "groups": groups,
        "claims": claims,
        "dismissed_identities": dismissed_identities,
        "artifact_relatives": sorted(
            {
                row["relative"].rsplit("/", 1)[0]
                for row in files
                if row["destination_kind"] == "project"
                and row["relative"].endswith("/done.json")
            }
        ),
    }
    write_journal(transaction_journal, journal)


def apply_and_finalize_transaction(
    target: ProjectTarget,
    transaction_journal: Path,
    identity: AgentIdentitySnapshot,
) -> None:
    journal = read_journal(transaction_journal)
    state = journal["state"]
    if state == "complete":
        return
    if state == "prepared":
        journal["state"] = "applying"
        write_journal(transaction_journal, journal)
        state = "applying"
    if state == "applying":
        _apply_staged_files(target, journal, journal["files"])
        claims = _claims_from_journal(target, journal)
        claim_imported_registered_names_v2(claims, identity=identity)
        journal["state"] = "applied"
        write_journal(transaction_journal, journal)
        state = "applied"
    if state in {"applied", "finalizing"}:
        journal["state"] = "finalizing"
        write_journal(transaction_journal, journal)
        _finalize_transaction(target, journal)
        journal["state"] = "complete"
        write_journal(transaction_journal, journal)
        shutil.rmtree(stage_dir_from_journal(target, journal), ignore_errors=True)


def _finalize_transaction(target: ProjectTarget, journal: dict[str, Any]) -> None:
    for relative in journal["artifact_relatives"]:
        update_agent_artifact_index_for_marker_mutation(
            sase_projects_dir() / target.project_key / relative
        )
    _apply_staged_files(target, journal, journal["groups"])
    _update_dismissed_bundle_index(target, journal)
    _record_imported_dismissed_agents(journal)


def _record_imported_dismissed_agents(journal: dict[str, Any]) -> None:
    identities = _dismissed_identities_from_journal(journal)
    if not identities:
        sync_dismissed_agent_artifact_index()
        return

    dismissed = load_dismissed_agents()
    added = identities - dismissed
    if added:
        dismissed.update(added)
        if not save_dismissed_agents(dismissed):
            raise AgentsSyncFormatError("failed to save imported dismissed identities")
        sync_dismissed_agent_artifact_index(dismissed, added=added)
        return
    sync_dismissed_agent_artifact_index(dismissed)


def _dismissed_identity_row(bundle: Mapping[str, Any]) -> dict[str, str | None]:
    agent_type = bundle.get("agent_type")
    cl_name = bundle.get("cl_name")
    raw_suffix = bundle.get("raw_suffix")
    if not isinstance(agent_type, str) or not agent_type:
        raise AgentsSyncFormatError("dismissed import identity missing agent_type")
    if not isinstance(cl_name, str) or not cl_name:
        raise AgentsSyncFormatError("dismissed import identity missing cl_name")
    if raw_suffix is not None and not isinstance(raw_suffix, str):
        raise AgentsSyncFormatError("dismissed import identity has invalid raw_suffix")
    return {
        "agent_type": agent_type,
        "cl_name": cl_name,
        "raw_suffix": raw_suffix,
    }


def _dismissed_identities_from_journal(
    journal: Mapping[str, Any],
) -> set[DismissedIdentity]:
    rows = journal.get("dismissed_identities", [])
    if not isinstance(rows, list):
        raise AgentsSyncFormatError(
            "import journal dismissed_identities must be a list"
        )
    identities: set[DismissedIdentity] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise AgentsSyncFormatError(
                "import journal dismissed identity must be an object"
            )
        agent_type = row.get("agent_type")
        cl_name = row.get("cl_name")
        raw_suffix = row.get("raw_suffix")
        if not isinstance(agent_type, str):
            raise AgentsSyncFormatError(
                "import journal dismissed identity missing agent_type"
            )
        try:
            typed_agent_type = AgentType(agent_type)
        except ValueError as exc:
            raise AgentsSyncFormatError(
                f"unknown import journal dismissed agent type {agent_type!r}"
            ) from exc
        if not isinstance(cl_name, str) or not cl_name:
            raise AgentsSyncFormatError(
                "import journal dismissed identity missing cl_name"
            )
        if raw_suffix is not None and not isinstance(raw_suffix, str):
            raise AgentsSyncFormatError(
                "import journal dismissed identity has invalid raw_suffix"
            )
        identities.add((typed_agent_type, cl_name, raw_suffix))
    return identities


def _update_dismissed_bundle_index(
    target: ProjectTarget,
    journal: dict[str, Any],
) -> None:
    """Incrementally index imported bundles, rebuilding only as a fallback."""

    root = dismissed_bundles_dir()
    bundle_rows = [
        row for row in journal["files"] if row.get("destination_kind") == "bundles"
    ]
    if not archive_index_exists(root):
        rebuild_dismissed_bundle_index()
        return
    for row in bundle_rows:
        path = destination_path(target, row)
        bundle = read_json_object(path)
        if bundle is None or not upsert_bundle_summary(root, path, bundle):
            rebuild_dismissed_bundle_index()
            return


def _apply_staged_files(
    target: ProjectTarget,
    journal: dict[str, Any],
    rows: list[dict[str, str]],
) -> None:
    stage = stage_dir_from_journal(target, journal)
    for row in rows:
        staged = stage / row["stage_relative"]
        payload = staged.read_bytes()
        if content_digest(payload) != row["digest"]:
            raise AgentsSyncFormatError("staged import payload digest mismatch")
        destination = destination_path(target, row)
        atomic_write_bytes(destination, payload)


def _claims_from_journal(
    target: ProjectTarget,
    journal: dict[str, Any],
) -> tuple[ImportedV2RegistryClaim, ...]:
    from sase.core.agent_identity_facade import AgentOwnerIdentity

    result: list[ImportedV2RegistryClaim] = []
    project_root = sase_projects_dir() / target.project_key
    for row in journal["claims"]:
        relative = validate_relative_path(row["artifact_relative"])
        result.append(
            ImportedV2RegistryClaim(
                AgentOwnerIdentity(
                    str(row["source_username"]),
                    str(row["source_machine"]),
                ),
                str(row["canonical_global_name"]),
                str(row["localized_name"]),
                project_root / relative,
                str(row["digest"]),
                (
                    str(row["container_kind"])
                    if row.get("container_kind") is not None
                    else None
                ),
                (
                    str(row["clan_generation"])
                    if row.get("clan_generation") is not None
                    else None
                ),
            )
        )
    return tuple(result)


def _relationships_by_source(
    plan: HoodPlan,
) -> dict[str, tuple[Mapping[str, Any], ...]]:
    rows: dict[str, list[Mapping[str, Any]]] = {}
    for relation in plan.relationships:
        rows.setdefault(str(relation["source_run_id"]), []).append(relation)
    return {key: tuple(value) for key, value in rows.items()}


def _containers_by_member(
    plan: HoodPlan,
    *,
    kind: str,
) -> dict[str, PlannedContainer]:
    result: dict[str, PlannedContainer] = {}
    for container in plan.containers:
        if container.record.kind != kind:
            continue
        for source_id in container.record.member_source_run_ids:
            result[source_id] = container
    return result


def _chat_path(run: PlannedRun) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_]", "_", run.localized_name)
    return (
        sase_home()
        / "chats"
        / run.destination_id[:6]
        / f"imported-v2-{safe}-{run.destination_id}.md"
    )


def _existing_chat_path(artifact_dir: Path) -> Path | None:
    meta = read_json_object(artifact_dir / "agent_meta.json") or {}
    done = read_json_object(artifact_dir / "done.json") or {}
    for value in (meta.get("chat_path"), done.get("response_path")):
        if isinstance(value, str) and value:
            path = Path(value).expanduser()
            if path.is_file():
                return path
    return None


def _artifact_relative(project_root: Path, artifact: Path) -> str:
    try:
        relative = artifact.resolve(strict=False).relative_to(
            project_root.resolve(strict=False)
        )
    except ValueError as exc:
        raise AgentsSyncFormatError(
            "imported artifact destination escapes its project root"
        ) from exc
    return validate_relative_path(relative.as_posix())


__all__ = [
    "apply_and_finalize_transaction",
    "prepare_transaction",
    "recover_v2_import_transactions",
]
