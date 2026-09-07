"""Delete persisted owners for deliberate agent-name reuse."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.agent.names._registry import lookup_registered_name
from sase.agent.names._wipe_execute import execute_wipe_plan
from sase.agent.names._wipe_plan import WipePlan, build_wipe_plan, merge_wipe_plans
from sase.agent.names._wipe_scan import WipeCatalog, load_wipe_catalog


@dataclass(frozen=True)
class AgentNameWipePreview:
    """Read-only view of the artifact closure a name wipe would remove."""

    artifact_dirs: tuple[str, ...] = ()
    bundle_paths: tuple[str, ...] = ()
    names: tuple[str, ...] = ()
    container_kind: str | None = None


@dataclass(frozen=True)
class AgentNameWipeResult:
    """Structured outcome for a forced-reuse name wipe."""

    target_name: str
    found: bool
    artifact_dirs_removed: tuple[str, ...] = ()
    bundle_paths_removed: tuple[str, ...] = ()
    registry_names_removed: tuple[str, ...] = ()
    dismissed_index_entries_removed: int = 0
    notifications_dismissed: int = 0
    killed_processes: int = 0
    errors: tuple[str, ...] = ()
    skipped_container_kind: str | None = None


@dataclass(frozen=True)
class _ResolvedWipeTarget:
    target_name: str
    owner: Mapping[str, Any] | None


def wipe_agent_name_for_reuse(
    owner_or_name: str | Mapping[str, Any],
    *,
    allow_stale_container: bool = False,
) -> AgentNameWipeResult:
    """Remove the previous owner of an agent name before forced reuse.

    The wipe is intentionally stronger than dismissal: artifact directories,
    dismissed bundles/index rows, notifications, workspace claims, and registry
    reservations tied to the owner and its descendants are removed so normal
    name lookup cannot rediscover the old agent. Clan and family container
    reservations are never wiped because their owner paths belong to members and
    the reservations are re-derived from those members during registry rebuilds.
    ``allow_stale_container`` is reserved for callers that have already proved a
    container has no concrete members and need to remove its orphaned owner data.
    """
    return wipe_agent_names_for_reuse(
        (owner_or_name,),
        allow_stale_container=allow_stale_container,
    )[0]


def wipe_agent_names_for_reuse(
    owners_or_names: Sequence[str | Mapping[str, Any]],
    *,
    allow_stale_container: bool = False,
) -> tuple[AgentNameWipeResult, ...]:
    """Remove previous owners for a forced-reuse cleanup batch.

    The batch shares one fresh registry snapshot, one artifact/bundle catalog,
    and one final registry rebuild across all actionable owners. Individual
    results preserve the single-name API shape while side effects are
    deduplicated over the union of every selected closure.
    """

    resolved = _resolve_wipe_targets(owners_or_names)
    if not resolved:
        return ()

    catalog: WipeCatalog | None = None
    plans: dict[int, WipePlan] = {}
    results: list[AgentNameWipeResult | None] = [None] * len(resolved)
    for index, target in enumerate(resolved):
        owner = target.owner
        if owner is None:
            results[index] = AgentNameWipeResult(
                target_name=target.target_name,
                found=False,
            )
            continue

        container_kind = owner.get("container_kind")
        if (
            isinstance(container_kind, str)
            and container_kind
            and not allow_stale_container
        ):
            results[index] = AgentNameWipeResult(
                target_name=target.target_name,
                found=True,
                skipped_container_kind=container_kind,
            )
            continue

        if catalog is None:
            catalog = load_wipe_catalog()
        plan = build_wipe_plan(owner, target.target_name, catalog=catalog)
        if not plan.names:
            plan.names.add(target.target_name)
        plans[index] = plan

    if plans:
        execution = execute_wipe_plan(merge_wipe_plans(tuple(plans.values())))
        single_plan = len(plans) == 1
        for index, plan in plans.items():
            target = resolved[index]
            results[index] = AgentNameWipeResult(
                target_name=target.target_name,
                found=True,
                artifact_dirs_removed=_path_result(
                    execution.artifact_dirs_removed & plan.artifact_dirs
                ),
                bundle_paths_removed=_path_result(
                    execution.bundle_paths_removed & plan.bundle_paths
                ),
                registry_names_removed=tuple(
                    sorted(execution.registry_names_removed & plan.names)
                ),
                dismissed_index_entries_removed=(
                    execution.dismissed_index_entries_removed if single_plan else 0
                ),
                notifications_dismissed=(
                    execution.notifications_dismissed if single_plan else 0
                ),
                killed_processes=execution.killed_processes if single_plan else 0,
                errors=execution.errors,
            )

    return tuple(
        result
        if result is not None
        else AgentNameWipeResult(target_name=target.target_name, found=False)
        for target, result in zip(resolved, results, strict=True)
    )


def _resolve_wipe_targets(
    owners_or_names: Sequence[str | Mapping[str, Any]],
) -> tuple[_ResolvedWipeTarget, ...]:
    if not owners_or_names:
        return ()

    snapshot = None
    if any(isinstance(item, str) for item in owners_or_names):
        from sase.agent.names import registered_name_reservation_snapshot

        snapshot = registered_name_reservation_snapshot()

    resolved: list[_ResolvedWipeTarget] = []
    for item in owners_or_names:
        if isinstance(item, str):
            owner = snapshot.lookup(item) if snapshot is not None else None
            resolved.append(_ResolvedWipeTarget(target_name=item, owner=owner))
        else:
            resolved.append(
                _ResolvedWipeTarget(
                    target_name=_str_or_empty(item.get("name")),
                    owner=item,
                )
            )
    return tuple(resolved)


def preview_agent_name_wipe(name: str) -> AgentNameWipePreview:
    """Return the wipe closure for *name* without mutating any state."""
    owner = lookup_registered_name(name)
    if owner is None:
        return AgentNameWipePreview()

    raw_kind = owner.get("container_kind")
    container_kind = raw_kind if isinstance(raw_kind, str) and raw_kind else None
    plan = build_wipe_plan(owner, name)
    if not plan.names:
        plan.names.add(name)
    return AgentNameWipePreview(
        artifact_dirs=tuple(sorted(str(path) for path in plan.artifact_dirs)),
        bundle_paths=tuple(sorted(str(path) for path in plan.bundle_paths)),
        names=tuple(sorted(plan.names)),
        container_kind=container_kind,
    )


def _path_result(paths: set[Path]) -> tuple[str, ...]:
    return tuple(sorted(str(path) for path in paths))


def _str_or_empty(value: Any) -> str:
    return value if isinstance(value, str) else ""
