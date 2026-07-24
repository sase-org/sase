"""Preflight planning for validated v2 agent-hood imports."""

from __future__ import annotations

import hashlib

from sase.agent.names import (
    ImportedV2RegistryClaim,
    preflight_imported_registered_names_v2,
)
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.v2_import_history import (
    existing_project_imports,
    find_exact_local_observation,
    preferred_timestamp,
    reserve_timestamp,
)
from sase.agents_sync.v2_import_package import ValidatedV2HoodPackage
from sase.agents_sync.v2_import_types import HoodPlan, PlannedContainer, PlannedRun
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
    localize_imported_agent_name,
    rewrite_agent_relationship_batch,
)


def preflight_hood(
    target: ProjectTarget,
    package: ValidatedV2HoodPackage,
    identity: AgentIdentitySnapshot,
) -> HoodPlan:
    if identity.owner is None:
        raise AgentsSyncFormatError("v2 import requires a configured owner identity")
    source = AgentSourceOwnerIdentity.v2(package.owner)
    classification = classify_imported_agent_owner(source, identity)
    existing = existing_project_imports(target, identity)
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
                find_exact_local_observation(target, payload, identity)
                if classification is AgentOwnershipClassification.EXACT_OWNER
                else None
            )
            if observed is not None:
                artifact = observed
                destination = artifact.name
                disposition = "observed"
                previous_digest = package.entry.digest
            else:
                destination = reserve_timestamp(
                    target,
                    preferred_timestamp(run.source_run_id, run.started_at),
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


__all__ = ["preflight_hood"]
