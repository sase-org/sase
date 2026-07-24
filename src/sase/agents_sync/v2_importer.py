"""Transactional local-history import for validated v2 agent hoods."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any

from sase.agent.names import (
    ImportedV2RegistryClaim,
    claim_imported_registered_names_v2,
    preflight_imported_registered_names_v2,
)
from sase.agents_sync.io import (
    AgentsSyncFormatError,
    atomic_write_bytes,
)
from sase.agents_sync.models import IntegrationCounts, ProjectTarget
from sase.agents_sync.v2_import_package import (
    ValidatedV2HoodPackage,
    ValidatedV2RunPayload,
)
from sase.agents_sync.v2_import_rendering import (
    artifact_payload,
    bundle_payload,
    family_group_id,
    json_bytes,
    saved_family_group,
)
from sase.agents_sync.v2_io import content_digest, validate_relative_path
from sase.agents_sync.v2_models import V2ContainerRecord
from sase.core.agent_artifact_index_lifecycle import (
    sync_dismissed_agent_artifact_index,
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.agent_artifact_paths import (
    ACE_RUN_WORKFLOW_DIR,
    canonical_agent_artifact_path,
    iter_agent_artifact_dirs,
)
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnershipClassification,
    AgentSourceOwnerIdentity,
    classify_imported_agent_owner,
    globalize_agent_name,
    localize_imported_agent_name,
    normalize_agent_archive_name,
    normalize_owned_agent_name,
    rewrite_agent_relationship_batch,
)
from sase.core.paths import sase_home, sase_projects_dir

_JOURNAL_SCHEMA_VERSION = 1
_IMPORT_DIR_NAME = "agents_sync_imports"
_TRANSACTION_RE = re.compile(r"^[a-z0-9-]{16,96}$")


@dataclass(frozen=True, slots=True)
class PlannedRun:
    payload: ValidatedV2RunPayload
    localized_name: str
    destination_id: str
    artifact_dir: Path
    disposition: str
    previous_digest: str | None = None


@dataclass(frozen=True, slots=True)
class PlannedContainer:
    record: V2ContainerRecord
    localized_name: str


@dataclass(frozen=True, slots=True)
class HoodPlan:
    package: ValidatedV2HoodPackage
    identity: AgentIdentitySnapshot
    transaction_key: str
    runs: tuple[PlannedRun, ...]
    containers: tuple[PlannedContainer, ...]
    registry_claims: tuple[ImportedV2RegistryClaim, ...]
    relationships: tuple[Mapping[str, Any], ...]

    @property
    def changed_runs(self) -> tuple[PlannedRun, ...]:
        return tuple(run for run in self.runs if run.disposition != "observed")

    @property
    def is_unchanged(self) -> bool:
        return all(run.disposition in {"observed", "unchanged"} for run in self.runs)

    @property
    def is_refresh(self) -> bool:
        return any(run.disposition == "refresh" for run in self.runs)


def integrate_v2_hoods(
    target: ProjectTarget,
    packages: tuple[ValidatedV2HoodPackage, ...],
    *,
    identity: AgentIdentitySnapshot,
) -> IntegrationCounts:
    """Preflight and import independently validated hoods one transaction each."""

    diagnostics: list[str] = []
    imported = refreshed = unchanged = quarantined = 0
    families = runs = 0
    with _project_import_lock(target.project_key):
        diagnostics.extend(_recover_v2_import_transactions(target, identity=identity))

    for package in packages:
        label = f"{package.owner.username}.{package.owner.machine_name}.{package.hood}"
        try:
            plan = _preflight_hood(target, package, identity)
            if not plan.changed_runs or (
                plan.is_unchanged
                and _transaction_is_complete(target.project_key, plan.transaction_key)
            ):
                unchanged += 1
                continue
            _prepare_transaction(target, plan)
            with _project_import_lock(target.project_key):
                _apply_and_finalize_transaction(
                    target,
                    _journal_path(target.project_key, plan.transaction_key),
                    identity,
                )
            if plan.is_refresh:
                refreshed += 1
            else:
                imported += 1
            families += sum(
                container.record.kind == "family" for container in plan.containers
            )
            runs += len(plan.changed_runs)
        except Exception as exc:  # noqa: BLE001 - hood-scoped quarantine contract
            quarantined += 1
            diagnostics.append(f"{label}: quarantined v2 import: {exc}")
    return IntegrationCounts(
        hoods_imported=imported,
        hoods_refreshed=refreshed,
        hoods_unchanged=unchanged,
        hoods_quarantined=quarantined,
        families_imported=families,
        runs_imported=runs,
        diagnostics=tuple(diagnostics),
    )


def _recover_v2_import_transactions(
    target: ProjectTarget,
    *,
    identity: AgentIdentitySnapshot,
) -> tuple[str, ...]:
    """Roll back prepared journals and finish interrupted applied transactions."""

    diagnostics: list[str] = []
    journals = _journals_dir(target.project_key)
    if not journals.is_dir():
        return ()
    for path in sorted(journals.glob("*.json"), key=lambda item: item.name):
        try:
            journal = _read_journal(path)
            state = journal["state"]
            if state == "complete":
                continue
            if state == "prepared":
                shutil.rmtree(
                    _stage_dir_from_journal(target, journal), ignore_errors=True
                )
                path.unlink(missing_ok=True)
                continue
            _apply_and_finalize_transaction(target, path, identity)
        except Exception as exc:  # noqa: BLE001 - preserve other recoveries
            diagnostics.append(f"{path.name}: import recovery failed: {exc}")
    return tuple(diagnostics)


def import_transaction_is_complete(
    project_key: str,
    transaction_key: str,
) -> bool:
    """Return whether a loader-visible imported transaction is complete."""

    if _TRANSACTION_RE.fullmatch(transaction_key) is None:
        return False
    return _transaction_is_complete(project_key, transaction_key)


def _preflight_hood(
    target: ProjectTarget,
    package: ValidatedV2HoodPackage,
    identity: AgentIdentitySnapshot,
) -> HoodPlan:
    if identity.owner is None:
        raise AgentsSyncFormatError("v2 import requires a configured owner identity")
    source = AgentSourceOwnerIdentity.v2(package.owner)
    classification = classify_imported_agent_owner(source, identity)
    existing = _existing_project_imports(target, identity)
    reserved = {
        path.name
        for path in iter_agent_artifact_dirs(
            target.project_key,
            ACE_RUN_WORKFLOW_DIR,
            newest_first=False,
        )
    }
    planned_runs: list[PlannedRun] = []
    destination_ids: dict[str, str] = {}

    for payload in package.runs:
        run = payload.record
        localized = localize_imported_agent_name(run.global_name, source, identity)
        match = existing.get(
            (
                package.owner.username,
                package.owner.machine_name,
                run.source_run_id,
                run.global_name,
            )
        )
        if match is not None:
            artifact, previous_digest = match
            disposition = (
                "unchanged" if previous_digest == package.entry.digest else "refresh"
            )
            destination = artifact.name
        else:
            observed = (
                _find_exact_local_observation(target, payload, identity)
                if classification is AgentOwnershipClassification.EXACT_OWNER
                else None
            )
            if observed is not None:
                artifact = observed
                destination = artifact.name
                disposition = "observed"
                previous_digest = package.entry.digest
            else:
                preferred = _preferred_timestamp(run.source_run_id, run.started_at)
                destination = _reserve_timestamp(
                    target,
                    preferred,
                    reserved,
                )
                reserved.add(destination)
                artifact = canonical_agent_artifact_path(
                    target.project_key,
                    ACE_RUN_WORKFLOW_DIR,
                    destination,
                )
                disposition = "new"
                previous_digest = None
        destination_ids[run.source_run_id] = destination
        planned_runs.append(
            PlannedRun(
                payload,
                localized,
                destination,
                artifact,
                disposition,
                previous_digest,
            )
        )

    rewritten = rewrite_agent_relationship_batch(
        package.snapshot.relationship_batch(),
        destination_ids,
    )
    containers = tuple(
        PlannedContainer(
            container,
            localize_imported_agent_name(
                container.global_name,
                source,
                identity,
            ),
        )
        for container in package.snapshot.containers
    )
    transaction_key = _transaction_key(package, target.project_key)
    preliminary = HoodPlan(
        package,
        identity,
        transaction_key,
        tuple(planned_runs),
        containers,
        (),
        rewritten.relationships,
    )
    claims = _registry_claims(preliminary)
    preflight_imported_registered_names_v2(claims, identity=identity)
    return HoodPlan(
        package,
        identity,
        transaction_key,
        tuple(planned_runs),
        containers,
        claims,
        rewritten.relationships,
    )


def _registry_claims(plan: HoodPlan) -> tuple[ImportedV2RegistryClaim, ...]:
    by_id = {run.payload.record.source_run_id: run for run in plan.runs}
    claims: list[ImportedV2RegistryClaim] = []
    # Container claims are applied first so a concrete family root and its
    # container can intentionally share one registry row.
    for container in plan.containers:
        materialized = [
            by_id[source_id]
            for source_id in container.record.member_source_run_ids
            if source_id in by_id and by_id[source_id].disposition != "observed"
        ]
        if not materialized:
            continue
        owner_run = materialized[0]
        claims.append(
            ImportedV2RegistryClaim(
                plan.package.owner,
                container.record.global_name,
                container.localized_name,
                owner_run.artifact_dir,
                plan.package.entry.digest,
                container_kind=container.record.kind,
                clan_generation=plan.transaction_key,
            )
        )
    container_names = {
        (container.record.kind, container.record.global_name): container
        for container in plan.containers
    }
    for run in plan.runs:
        if run.disposition == "observed":
            continue
        # The family container claim already owns a same-named concrete root.
        if ("family", run.payload.record.global_name) in container_names:
            continue
        claims.append(
            ImportedV2RegistryClaim(
                plan.package.owner,
                run.payload.record.global_name,
                run.localized_name,
                run.artifact_dir,
                plan.package.entry.digest,
            )
        )
    return tuple(claims)


def _prepare_transaction(target: ProjectTarget, plan: HoodPlan) -> None:
    root = _imports_root(target.project_key)
    root.mkdir(parents=True, exist_ok=True)
    stage = root / "staging" / plan.transaction_key
    journal_path = _journal_path(target.project_key, plan.transaction_key)
    if journal_path.is_file():
        existing_journal = _read_journal(journal_path)
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
    chat_paths: dict[str, Path | None] = {}
    for run in plan.changed_runs:
        record = run.payload.record
        artifact_relative = _artifact_relative(project_root, run.artifact_dir)
        chat_path = _chat_path(run)
        chat_payload = run.payload.file_bytes("chat")
        if chat_payload is not None:
            _stage_file(
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
            _stage_file(
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
        bundle_destination = _dismissed_bundles_dir() / bundle_relative
        bundle_locations[record.source_run_id] = bundle_destination
        bundle_payloads[record.source_run_id] = bundle
        _stage_file(
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
        existing_group = _read_json_object(_dismissed_groups_dir() / f"{group_id}.json")
        if existing_group is not None:
            revived_at = existing_group.get("revived_at")
            times_revived = existing_group.get("times_revived")
            if isinstance(revived_at, str) and revived_at:
                group["revived_at"] = revived_at
            if isinstance(times_revived, int) and not isinstance(times_revived, bool):
                group["times_revived"] = max(0, times_revived)
        _stage_file(
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
        "schema_version": _JOURNAL_SCHEMA_VERSION,
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
        "artifact_relatives": sorted(
            {
                row["relative"].rsplit("/", 1)[0]
                for row in files
                if row["destination_kind"] == "project"
                and row["relative"].endswith("/done.json")
            }
        ),
    }
    _write_journal(journal_path, journal)


def _apply_and_finalize_transaction(
    target: ProjectTarget,
    journal_path: Path,
    identity: AgentIdentitySnapshot,
) -> None:
    journal = _read_journal(journal_path)
    state = journal["state"]
    if state == "complete":
        return
    if state == "prepared":
        journal["state"] = "applying"
        _write_journal(journal_path, journal)
        state = "applying"
    if state == "applying":
        _apply_staged_files(target, journal, journal["files"])
        claims = _claims_from_journal(target, journal)
        claim_imported_registered_names_v2(claims, identity=identity)
        journal["state"] = "applied"
        _write_journal(journal_path, journal)
        state = "applied"
    if state in {"applied", "finalizing"}:
        journal["state"] = "finalizing"
        _write_journal(journal_path, journal)
        _finalize_transaction(target, journal)
        journal["state"] = "complete"
        _write_journal(journal_path, journal)
        shutil.rmtree(_stage_dir_from_journal(target, journal), ignore_errors=True)


def _apply_staged_files(
    target: ProjectTarget,
    journal: dict[str, Any],
    rows: list[dict[str, str]],
) -> None:
    stage = _stage_dir_from_journal(target, journal)
    for row in rows:
        staged = stage / row["stage_relative"]
        payload = staged.read_bytes()
        if content_digest(payload) != row["digest"]:
            raise AgentsSyncFormatError("staged import payload digest mismatch")
        destination = _destination_path(target, row)
        atomic_write_bytes(destination, payload)


def _finalize_transaction(target: ProjectTarget, journal: dict[str, Any]) -> None:
    for relative in journal["artifact_relatives"]:
        update_agent_artifact_index_for_marker_mutation(
            sase_projects_dir() / target.project_key / relative
        )
    _apply_staged_files(target, journal, journal["groups"])
    from sase.ace.dismissed_agents import rebuild_dismissed_bundle_index

    rebuild_dismissed_bundle_index()
    sync_dismissed_agent_artifact_index(force=True)


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


def _existing_project_imports(
    target: ProjectTarget,
    identity: AgentIdentitySnapshot,
) -> dict[tuple[str, str, str, str], tuple[Path, str | None]]:
    results: dict[tuple[str, str, str, str], tuple[Path, str | None]] = {}
    for artifact in iter_agent_artifact_dirs(
        target.project_key,
        ACE_RUN_WORKFLOW_DIR,
        newest_first=False,
    ):
        meta = _read_json_object(artifact / "agent_meta.json")
        if meta is None:
            continue
        owner = meta.get("imported_source_owner")
        source_id = meta.get("imported_source_run_id")
        global_name = meta.get("canonical_global_name")
        if (
            not isinstance(owner, dict)
            or not isinstance(source_id, str)
            or not isinstance(global_name, str)
        ):
            continue
        username = owner.get("username")
        machine = owner.get("machine_name")
        if not isinstance(username, str) or not isinstance(machine, str):
            continue
        localized = localize_imported_agent_name(
            global_name,
            AgentSourceOwnerIdentity(machine, username),
            identity,
        )
        if meta.get("name") != localized:
            continue
        digest = meta.get("imported_snapshot_digest")
        results[(username, machine, source_id, global_name)] = (
            artifact,
            digest if isinstance(digest, str) else None,
        )
    return results


def _find_exact_local_observation(
    target: ProjectTarget,
    payload: ValidatedV2RunPayload,
    identity: AgentIdentitySnapshot,
) -> Path | None:
    if identity.owner is None:
        return None
    source_shas = {commit.sha for commit in payload.commits.commits}
    for artifact in iter_agent_artifact_dirs(
        target.project_key,
        ACE_RUN_WORKFLOW_DIR,
        newest_first=False,
    ):
        meta = _read_json_object(artifact / "agent_meta.json")
        done = _read_json_object(artifact / "done.json") or {}
        if meta is None or meta.get("imported_source_owner") is not None:
            continue
        raw_name = meta.get("name") or done.get("name")
        if not isinstance(raw_name, str) or not raw_name:
            continue
        try:
            local_name = normalize_agent_archive_name(
                normalize_owned_agent_name(raw_name, identity)
            )
            if (
                globalize_agent_name(local_name, identity.owner)
                != payload.record.global_name
            ):
                continue
        except (ValueError, RuntimeError):
            continue
        durable = meta.get("artifact_agent_id")
        if not isinstance(durable, str) or not durable:
            durable = artifact.name
        derived_id = _source_run_id(target.project_key, ACE_RUN_WORKFLOW_DIR, durable)
        if derived_id == payload.record.source_run_id:
            return artifact
        if source_shas and source_shas & _artifact_commit_shas(artifact):
            return artifact
    return None


def _artifact_commit_shas(artifact: Path) -> set[str]:
    result: set[str] = set()
    for name in ("commit_results.json", "commit_result.json"):
        value = _read_json(artifact / name)
        rows = value if isinstance(value, list) else [value]
        for row in rows:
            if not isinstance(row, dict):
                continue
            sha = row.get("result") or row.get("commit_result") or row.get("sha")
            if isinstance(sha, str):
                result.add(sha.lower())
    return result


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


def _stage_file(
    stage: Path,
    rows: list[dict[str, str]],
    destination_kind: str,
    relative: str,
    payload: bytes,
) -> None:
    validate_relative_path(relative)
    stage_relative = f"{destination_kind}/{relative}"
    destination = stage / stage_relative
    atomic_write_bytes(destination, payload)
    rows.append(
        {
            "destination_kind": destination_kind,
            "relative": relative,
            "stage_relative": stage_relative,
            "digest": content_digest(payload),
        }
    )


def _destination_path(target: ProjectTarget, row: Mapping[str, str]) -> Path:
    relative = validate_relative_path(row["relative"])
    kind = row["destination_kind"]
    roots = {
        "project": sase_projects_dir() / target.project_key,
        "state": sase_home(),
        "bundles": _dismissed_bundles_dir(),
        "groups": _dismissed_groups_dir(),
    }
    root = roots.get(kind)
    if root is None:
        raise AgentsSyncFormatError(f"unknown import destination kind {kind!r}")
    destination = root / relative
    if not destination.resolve(strict=False).is_relative_to(root.resolve(strict=False)):
        raise AgentsSyncFormatError("import destination escapes its local root")
    return destination


def _journal_path(project_key: str, transaction_key: str) -> Path:
    if _TRANSACTION_RE.fullmatch(transaction_key) is None:
        raise AgentsSyncFormatError("invalid import transaction key")
    return _journals_dir(project_key) / f"{transaction_key}.json"


def _imports_root(project_key: str) -> Path:
    return sase_projects_dir() / project_key / _IMPORT_DIR_NAME


def _journals_dir(project_key: str) -> Path:
    return _imports_root(project_key) / "journals"


def _transaction_is_complete(project_key: str, transaction_key: str) -> bool:
    path = _journal_path(project_key, transaction_key)
    try:
        return _read_journal(path).get("state") == "complete"
    except (OSError, AgentsSyncFormatError):
        return False


def _read_journal(path: Path) -> dict[str, Any]:
    value = _read_json(path)
    if not isinstance(value, dict):
        raise AgentsSyncFormatError(f"invalid import journal {path}")
    if value.get("schema_version") != _JOURNAL_SCHEMA_VERSION:
        raise AgentsSyncFormatError("unsupported import journal schema")
    key = value.get("transaction_key")
    if not isinstance(key, str) or _TRANSACTION_RE.fullmatch(key) is None:
        raise AgentsSyncFormatError("invalid import journal transaction key")
    if value.get("state") not in {
        "prepared",
        "applying",
        "applied",
        "finalizing",
        "complete",
    }:
        raise AgentsSyncFormatError("invalid import journal state")
    for list_key in ("files", "groups", "claims", "artifact_relatives"):
        if not isinstance(value.get(list_key), list):
            raise AgentsSyncFormatError(f"import journal {list_key} must be a list")
    return value


def _write_journal(path: Path, journal: dict[str, Any]) -> None:
    atomic_write_bytes(path, json_bytes(journal))


def _stage_dir_from_journal(
    target: ProjectTarget,
    journal: Mapping[str, Any],
) -> Path:
    relative = validate_relative_path(journal["stage_relative"])
    root = _imports_root(target.project_key)
    stage = root / relative
    if not stage.resolve(strict=False).is_relative_to(root.resolve(strict=False)):
        raise AgentsSyncFormatError("import stage escapes project import root")
    return stage


@contextmanager
def _project_import_lock(project_key: str) -> Iterator[None]:
    root = _imports_root(project_key)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "mutation.lock"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _transaction_key(
    package: ValidatedV2HoodPackage,
    project_key: str,
) -> str:
    identity = "\0".join(
        (
            project_key,
            package.owner.username,
            package.owner.machine_name,
            package.hood,
            package.entry.digest,
        )
    )
    return "v2-" + hashlib.sha256(identity.encode()).hexdigest()[:40]


def _preferred_timestamp(source_run_id: str, started_at: str | None) -> str:
    match = re.search(r"(?<!\d)(\d{14})(?!\d)", source_run_id)
    if match is not None:
        try:
            datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
            return match.group(1)
        except ValueError:
            pass
    parsed = _parse_datetime(started_at)
    if parsed is not None:
        return parsed.astimezone(UTC).strftime("%Y%m%d%H%M%S")
    # Stable fallback in a historical range; probing resolves collisions.
    seconds = int(hashlib.sha256(source_run_id.encode()).hexdigest()[:8], 16)
    return (datetime(2000, 1, 1, tzinfo=UTC) + timedelta(seconds=seconds)).strftime(
        "%Y%m%d%H%M%S"
    )


def _reserve_timestamp(
    target: ProjectTarget,
    preferred: str,
    reserved: set[str],
) -> str:
    current = datetime.strptime(preferred, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    for _ in range(86_400):
        value = current.strftime("%Y%m%d%H%M%S")
        destination = canonical_agent_artifact_path(
            target.project_key,
            ACE_RUN_WORKFLOW_DIR,
            value,
        )
        if value not in reserved and not destination.exists():
            return value
        current += timedelta(seconds=1)
    raise RuntimeError("could not allocate a free imported artifact timestamp")


def _chat_path(run: PlannedRun) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_]", "_", run.localized_name)
    return (
        sase_home()
        / "chats"
        / run.destination_id[:6]
        / f"imported-v2-{safe}-{run.destination_id}.md"
    )


def _existing_chat_path(artifact_dir: Path) -> Path | None:
    meta = _read_json_object(artifact_dir / "agent_meta.json") or {}
    done = _read_json_object(artifact_dir / "done.json") or {}
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


def _dismissed_bundles_dir() -> Path:
    from sase.ace import dismissed_agents

    return dismissed_agents.dismissed_bundles_dir()


def _dismissed_groups_dir() -> Path:
    from sase.ace import dismissed_agents

    return dismissed_agents.dismissed_agent_groups_dir()


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


def _source_run_id(project: str, workflow: str, durable: str) -> str:
    digest = hashlib.sha256(
        "\x00".join((project, workflow, durable)).encode("utf-8")
    ).hexdigest()
    return f"run-{digest[:32]}"


def _read_json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _read_json_object(path: Path) -> dict[str, Any] | None:
    value = _read_json(path)
    return value if isinstance(value, dict) else None


__all__ = [
    "import_transaction_is_complete",
    "integrate_v2_hoods",
]
