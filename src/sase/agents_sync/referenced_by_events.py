"""Emit prompt `cites` as artifact-link outbox events in fenced projects."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path

from sase._interruptions import PublicationDrainTimedOut
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.referenced_by_outbox import (
    ReferencedByOutboxItem,
    acknowledge_referenced_by_requests,
    configured_publication_max_attempts,
    list_referenced_by_requests,
    update_referenced_by_requests,
)
from sase.sdd._artifact_link_projection import artifact_link_row
from sase.sdd._artifact_link_store_support import validate_artifact_link_row

TRUSTED_CITES_PRODUCER = "sase"
_MIGRATED_ORIGIN = "migrated"
_FENCED_BACKLOG_ORIGIN = _MIGRATED_ORIGIN


def _machine_sidecar_roots_for_fence_probe(
    target: ProjectTarget,
) -> dict[str, Path]:
    """Return machine-lane sidecar roots without lock, pull, or clone setup.

    Prefers an already-present hidden host-owned clone; otherwise uses the
    primary nested clone so a fenced marker is still visible before the
    hidden lane exists.
    """

    from sase._linked_repo_paths import hidden_sidecar_clone_dir
    from sase.sdd.store import document_sidecar_roles, resolve_sdd_store
    from sase.workspace_provider.store import PRIMARY_WORKSPACE_NUM

    try:
        store = resolve_sdd_store(target.primary_checkout, PRIMARY_WORKSPACE_NUM)
    except PublicationDrainTimedOut:
        raise
    except Exception:
        return _existing_hidden_roots(target.project_key, ("plans", "research"))
    roles = document_sidecar_roles(store.split_sidecar_roles(), include_plans=True)
    roots: dict[str, Path] = {}
    for role in roles:
        hidden = Path(hidden_sidecar_clone_dir(target.project_key, role))
        if hidden.is_dir():
            roots[role] = hidden
            continue
        try:
            primary_root = (
                store.repo_root_for_kind(role).expanduser().resolve(strict=False)
            )
        except PublicationDrainTimedOut:
            raise
        except Exception:
            continue
        if primary_root.is_dir():
            roots[role] = primary_root
    return roots


def legacy_referenced_by_writes_fenced(target: ProjectTarget) -> bool:
    """Return whether this project's legacy Referenced By writes are fenced."""

    from sase.sdd._artifact_link_cutover_state import legacy_artifact_link_writes_fenced

    roots = _machine_sidecar_roots_for_fence_probe(target)
    if not roots:
        return False
    try:
        return legacy_artifact_link_writes_fenced(
            roots,
            project_key=target.project_key,
        )
    except PublicationDrainTimedOut:
        raise
    except Exception:
        return False


def cites_outbox_identity(
    *,
    agent_name: str,
    run_id: str | None,
) -> tuple[str, str]:
    """Return ``(agent_name, run_id)`` for one cites outbox append.

    A committing run identity is used when *run_id* is present so the commit
    path's pass-C drain can publish the events. Callers without release
    evidence (the approved-planner archive) omit *run_id* and get the trusted
    machine lane.
    """

    cleaned_run = (run_id or "").strip()
    if cleaned_run:
        return agent_name, cleaned_run
    from sase.sdd.artifact_link_event_publisher import artifact_link_machine_run_id

    return TRUSTED_CITES_PRODUCER, artifact_link_machine_run_id()


def emit_referenced_by_cites_events(
    items: Iterable[ReferencedByOutboxItem],
    *,
    project_key: str,
    agent_name: str,
    run_id: str,
    origin: str | None = None,
) -> tuple[str, ...]:
    """Append one outbox event per request. Never enqueues Referenced By rows."""

    from sase.sdd.artifact_link_event_publisher import (
        observation_or_put_event_from_row,
        stable_artifact_link_operation_id,
    )
    from sase.sdd.artifact_link_outbox import append_artifact_link_outbox_event

    diagnostics: list[str] = []
    for item in items:
        try:
            row = _event_row(item, origin=origin)
            validated = validate_artifact_link_row(row)
            operation_id = stable_artifact_link_operation_id(
                "prompt-cites",
                project_key,
                validated["source_ref"],
                validated["relation"],
                validated["target_ref"],
                validated["origin"],
            )
            event = observation_or_put_event_from_row(
                validated,
                project_key=project_key,
                operation_id=operation_id,
            )
            append_artifact_link_outbox_event(
                project_key=project_key,
                agent_name=agent_name,
                run_id=run_id,
                event=event,
            )
        except (RuntimeError, TypeError, ValueError) as exc:
            diagnostics.append(
                f"referenced-by cites event for {item.artifact_id}: {exc}"
            )
    return tuple(diagnostics)


def convert_fenced_referenced_by_backlog(
    target: ProjectTarget,
) -> tuple[str, ...]:
    """Replay active legacy requests as trusted migrated cites events."""

    from sase.sdd.artifact_link_event_publisher import artifact_link_machine_run_id

    requests = list_referenced_by_requests(
        target.project_key,
        include_quarantined=False,
    )
    if not requests:
        return ()
    agent_name = TRUSTED_CITES_PRODUCER
    run_id = artifact_link_machine_run_id()
    diagnostics: list[str] = []
    acknowledged: list[ReferencedByOutboxItem] = []
    failed: list[ReferencedByOutboxItem] = []
    for item in requests:
        errors = emit_referenced_by_cites_events(
            (item,),
            project_key=target.project_key,
            agent_name=agent_name,
            run_id=run_id,
            origin=_FENCED_BACKLOG_ORIGIN,
        )
        if errors:
            diagnostics.extend(errors)
            failed.append(item)
            continue
        acknowledged.append(item)
    if acknowledged:
        acknowledge_referenced_by_requests(
            target.project_key,
            (item.logical_key for item in acknowledged),
        )
    if failed:
        update_referenced_by_requests(
            target.project_key,
            (item.logical_key for item in failed),
            error="; ".join(diagnostics) or "cites event append failed",
            increment_attempts=True,
            quarantine_threshold=configured_publication_max_attempts(),
        )
    return tuple(diagnostics)


def _event_row(
    item: ReferencedByOutboxItem,
    *,
    origin: str | None,
) -> dict[str, object]:
    if origin is None or origin == item.origin:
        return artifact_link_row(item)
    return artifact_link_row(replace(item, origin=origin))


def _existing_hidden_roots(project_key: str, roles: Iterable[str]) -> dict[str, Path]:
    from sase._linked_repo_paths import hidden_sidecar_clone_dir

    roots: dict[str, Path] = {}
    for role in roles:
        try:
            hidden = Path(hidden_sidecar_clone_dir(project_key, role))
        except ValueError:
            continue
        if hidden.is_dir():
            roots[role] = hidden
    return roots


def store_legacy_writes_fenced(
    store: object,
    *,
    project_key: str,
) -> bool:
    """Return whether *store*'s document sidecar roots are link-v2 fenced."""

    from sase.sdd._artifact_link_cutover_state import legacy_artifact_link_writes_fenced
    from sase.sdd.store import document_sidecar_roles

    split = getattr(store, "split_sidecar_roles", None)
    repo_root_for_kind = getattr(store, "repo_root_for_kind", None)
    if not callable(split) or not callable(repo_root_for_kind):
        return False
    roles = document_sidecar_roles(split(), include_plans=True)
    roots: dict[str, Path] = {}
    for role in roles:
        try:
            roots[role] = repo_root_for_kind(role).expanduser().resolve(strict=False)
        except PublicationDrainTimedOut:
            raise
        except Exception:
            continue
    if not roots:
        return False
    return legacy_artifact_link_writes_fenced(roots, project_key=project_key)


__all__ = [
    "TRUSTED_CITES_PRODUCER",
    "cites_outbox_identity",
    "convert_fenced_referenced_by_backlog",
    "emit_referenced_by_cites_events",
    "legacy_referenced_by_writes_fenced",
    "store_legacy_writes_fenced",
]
