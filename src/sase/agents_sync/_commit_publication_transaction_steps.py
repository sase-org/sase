"""Prepare and verify publication payloads for a commit transaction."""

from __future__ import annotations

from sase._interruptions import PublicationDrainTimedOut
from sase.agents_sync.git import GitRunner
from sase.agents_sync.inventory import ProjectHoodInventory
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.prompt_archive.deferred import (
    prepare_deferred_prompt_archive,
    prompt_runs_by_request,
)
from sase.agents_sync.publication_outbox import AgentPublicationOutboxItem
from sase.agents_sync.publication_planning import shared_targeted_planning
from sase.agents_sync.publication_protection import PublicationProtectionScope
from sase.agents_sync.publication_snapshot import settlement_error_for_withheld_request
from sase.agents_sync.publication_timing import DrainTiming
from sase.agents_sync.v2_io import read_owner_manifest
from sase.agents_sync.v2_models import V2ProjectIdentity, V2PublicationCounts
from sase.agents_sync._commit_publication_transaction_types import (
    PublicationTransactionHooks,
)
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity


def protection_scope(target: ProjectTarget) -> PublicationProtectionScope:
    """Build the transcript pre-stage verification scope for one project."""

    return PublicationProtectionScope(
        project_key=target.project_key,
        repository_identity=target.remote_url,
    )


def prepare_publications(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    requests: tuple[AgentPublicationOutboxItem, ...],
    identity: AgentIdentitySnapshot,
    inventory: ProjectHoodInventory,
    git_runner: GitRunner,
    *,
    hooks: PublicationTransactionHooks,
    timer: DrainTiming | None = None,
) -> tuple[
    tuple[AgentPublicationOutboxItem, ...],
    tuple[str, ...],
    tuple[tuple[str, str], ...],
    tuple[tuple[str, str], ...],
]:
    repo = target.sidecar_path
    requests_by_hood: dict[str, list[AgentPublicationOutboxItem]] = {}
    prepared: list[AgentPublicationOutboxItem] = []
    errors: list[str] = []
    withheld_runs: list[tuple[str, str]] = []
    withheld_hoods: list[tuple[str, str]] = []
    prompt_runs = prompt_runs_by_request(inventory, identity)
    for request in requests:
        requests_by_hood.setdefault(request.local_hood, []).append(request)

    published_by_hood: dict[str, list[AgentPublicationOutboxItem]] = {}
    # Targeted hood plans share validated snapshots within this prepare so
    # several selected hoods do not each re-read every snapshot file. The
    # retry path below invalidates before rebuilding from fresh upstream.
    with shared_targeted_planning():
        for hood_requests in requests_by_hood.values():
            request = hood_requests[0]
            if timer is not None:
                timer.active_keys = tuple(item.logical_key for item in hood_requests)
            try:
                if timer is not None:
                    with timer.record_stage(f"hood_publish:{request.local_hood}"):
                        counts = hooks.publish_hood(
                            target,
                            repo,
                            request.local_agent,
                            identity=identity,
                            inventory=inventory,
                            git_runner=git_runner,
                        )
                else:
                    counts = hooks.publish_hood(
                        target,
                        repo,
                        request.local_agent,
                        identity=identity,
                        inventory=inventory,
                        git_runner=git_runner,
                    )
                hood_runs, hood_withheld = _withheld_from_counts(counts)
                withheld_runs.extend(hood_runs)
                withheld_hoods.extend(hood_withheld)
                if request.local_hood in {name for name, _reason in hood_withheld}:
                    prepared.extend(hood_requests)
                    continue
                if timer is not None:
                    with timer.record_stage(
                        f"prompt_archive_prepare:{request.local_hood}"
                    ):
                        for hood_request in hood_requests:
                            prepare_deferred_prompt_archive(
                                target,
                                hood_request,
                                git_runner,
                                prompt_runs=prompt_runs,
                            )
                else:
                    for hood_request in hood_requests:
                        prepare_deferred_prompt_archive(
                            target,
                            hood_request,
                            git_runner,
                            prompt_runs=prompt_runs,
                        )
                published_by_hood[request.local_hood] = hood_requests
            except PublicationDrainTimedOut:
                raise
            except Exception as exc:  # noqa: BLE001 - durable auxiliary boundary
                error = f"could not publish agent hood {request.local_hood!r}: {exc}"
                hooks.update_publications(
                    target.project_key,
                    (item.logical_key for item in hood_requests),
                    error=error,
                    increment_attempts=True,
                    quarantine_threshold=hooks.configured_max_attempts(),
                    terminal_reason=error
                    if isinstance(exc, AgentsSyncFormatError)
                    else None,
                )
                errors.append(error)

    if timer is not None:
        timer.stage = "manifest_verify"
    try:
        if timer is not None:
            with timer.record_stage("manifest_verify"):
                entries = (
                    read_owner_manifest(
                        repo,
                        owner,
                        V2ProjectIdentity(target.project_key, target.project),
                    ).by_hood()
                    if published_by_hood
                    else {}
                )
        else:
            entries = (
                read_owner_manifest(
                    repo,
                    owner,
                    V2ProjectIdentity(target.project_key, target.project),
                ).by_hood()
                if published_by_hood
                else {}
            )
    except PublicationDrainTimedOut:
        raise
    except Exception as exc:  # noqa: BLE001 - durable auxiliary boundary
        # Shared manifest validation is repository-wide: report without charging.
        error = f"could not verify agent publication manifest: {exc}"
        errors.append(error)
        return (
            (),
            tuple(errors),
            tuple(dict.fromkeys(withheld_runs)),
            tuple(dict.fromkeys(withheld_hoods)),
        )
    for hood, hood_requests in published_by_hood.items():
        request = hood_requests[0]
        try:
            entry = entries.get(hood)
            if entry is None:
                raise RuntimeError(f"published hood {hood!r} is absent from manifest")
            hooks.update_publications(
                target.project_key,
                (item.logical_key for item in hood_requests),
                hood_digest=entry.digest,
                error=None,
            )
            prepared.extend(hood_requests)
        except PublicationDrainTimedOut:
            raise
        except Exception as exc:  # noqa: BLE001 - durable auxiliary boundary
            error = f"could not publish agent hood {request.local_hood!r}: {exc}"
            hooks.update_publications(
                target.project_key,
                (item.logical_key for item in hood_requests),
                error=error,
                increment_attempts=True,
                quarantine_threshold=hooks.configured_max_attempts(),
            )
            errors.append(error)
    prepared_keys = {item.logical_key for item in prepared}
    return (
        tuple(item for item in requests if item.logical_key in prepared_keys),
        tuple(errors),
        tuple(dict.fromkeys(withheld_runs)),
        tuple(dict.fromkeys(withheld_hoods)),
    )


def _withheld_from_counts(
    counts: object,
) -> tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]]:
    if isinstance(counts, V2PublicationCounts):
        return counts.withheld_runs, counts.withheld_hoods
    return (), ()


def acknowledge_completed(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    git_runner: GitRunner,
    identity: AgentIdentitySnapshot,
    inventory: ProjectHoodInventory,
    prepared: list[AgentPublicationOutboxItem] | tuple[AgentPublicationOutboxItem, ...],
    *,
    hooks: PublicationTransactionHooks,
    timer: DrainTiming | None = None,
    withheld_runs: tuple[tuple[str, str], ...] = (),
    withheld_hoods: tuple[tuple[str, str], ...] = (),
) -> tuple[tuple[tuple[str, str], ...], tuple[str, ...]]:
    """Acknowledge only requests whose page, revision, and prompt are complete.

    A rejected push or interruption leaves requests durable; only verified
    requests are removed. Unfulfilled requests are charged once as hood
    failures so a later drain can retry them. Withheld runs are parked or
    retried without acknowledging and without treating the missing page as
    a terminal materialization failure.
    """

    from sase.agents_sync.prompt_archive.deferred import (
        restore_deferred_prompt_archives,
    )
    from sase.agents_sync.publication_completion import publication_request_fulfilled
    from sase.agents_sync.prompt_archive.preparation import PreparedPromptArchive
    from sase.agents_sync.prompt_archive.publish import (
        record_prompt_archive_side_effects,
    )

    if not prepared:
        return (), ()
    prepared_tuple = tuple(prepared)
    prepared_archives: dict[tuple[str, str], PreparedPromptArchive] = {}
    try:
        prompt_failures = restore_deferred_prompt_archives(
            target,
            prepared_tuple,
            git_runner,
            identity=identity,
            inventory=inventory,
            prepared_archives=prepared_archives,
        )
    except PublicationDrainTimedOut:
        raise
    except Exception:  # noqa: BLE001 - prompt check must not fail a drain.
        prompt_failures = {}
    ackable: list[tuple[str, str]] = []
    gate_errors: list[str] = []
    for item in prepared_tuple:
        withheld_error = settlement_error_for_withheld_request(
            global_agent=item.global_agent,
            local_hood=item.local_hood,
            withheld_runs=withheld_runs,
            withheld_hoods=withheld_hoods,
        )
        if withheld_error is not None:
            hooks.update_publications(
                target.project_key,
                (item.logical_key,),
                error=withheld_error,
                increment_attempts=False,
                quarantine_threshold=None,
            )
            gate_errors.append(withheld_error)
            continue
        prompt_error = prompt_failures.get(item.logical_key)
        if prompt_error is not None:
            from sase.agents_sync.prompt_archive.protection import (
                should_charge_prompt_protection_failure,
            )

            charge = should_charge_prompt_protection_failure(prompt_error)
            hooks.update_publications(
                target.project_key,
                (item.logical_key,),
                error=prompt_error,
                increment_attempts=charge,
                quarantine_threshold=(
                    hooks.configured_max_attempts() if charge else None
                ),
            )
            gate_errors.append(prompt_error)
            continue
        try:
            fulfilled = publication_request_fulfilled(target, item, owner)
        except PublicationDrainTimedOut:
            raise
        except Exception as exc:  # noqa: BLE001 - durable auxiliary boundary
            error = f"could not verify publication request {item.global_agent!r}: {exc}"
            hooks.update_publications(
                target.project_key,
                (item.logical_key,),
                error=error,
                increment_attempts=True,
                quarantine_threshold=hooks.configured_max_attempts(),
            )
            gate_errors.append(error)
            continue
        if not fulfilled:
            error = (
                f"published agent page for {item.global_agent!r} "
                "did not materialize during commit drain"
            )
            hooks.update_publications(
                target.project_key,
                (item.logical_key,),
                error=error,
                increment_attempts=True,
                quarantine_threshold=hooks.configured_max_attempts(),
                terminal_reason=error,
            )
            gate_errors.append(error)
            continue
        prompt_archive = prepared_archives.get(item.logical_key)
        if prompt_archive is not None:
            side_effect_error = record_prompt_archive_side_effects(
                target,
                prompt_archive,
                global_agent=item.global_agent,
                publication_agent=item.local_agent,
                run_id=item.run_id,
            )
            if side_effect_error is not None:
                hooks.update_publications(
                    target.project_key,
                    (item.logical_key,),
                    error=side_effect_error,
                    increment_attempts=True,
                    quarantine_threshold=hooks.configured_max_attempts(),
                )
                gate_errors.append(side_effect_error)
                continue
        ackable.append(item.logical_key)
    if not ackable:
        return (), tuple(gate_errors)
    if timer is not None:
        with timer.record_stage("verify"):
            hooks.acknowledge_publications(target.project_key, ackable)
    else:
        hooks.acknowledge_publications(target.project_key, ackable)
    return tuple(ackable), tuple(gate_errors)
