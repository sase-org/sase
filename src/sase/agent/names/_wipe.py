"""Delete persisted owners for deliberate agent-name reuse."""

from __future__ import annotations

import json
import os
import signal
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sase.agent.names._common import is_process_alive
from sase.agent.names._registry import lookup_registered_name, rebuild_name_registry
from sase.core.agent_artifact_index_lifecycle import (
    delete_agent_artifact_index_artifacts,
    sync_dismissed_agent_artifact_index,
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.core.paths import sase_home, sase_projects_dir, sase_subdir


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


@dataclass
class _ArtifactRecord:
    path: Path
    suffix: str
    project_name: str | None
    names: set[str] = field(default_factory=set)
    relation_refs: set[str] = field(default_factory=set)
    outgoing_suffixes: set[str] = field(default_factory=set)


@dataclass
class _BundleRecord:
    path: Path
    raw_suffix: str | None
    names: set[str] = field(default_factory=set)
    relation_refs: set[str] = field(default_factory=set)
    outgoing_suffixes: set[str] = field(default_factory=set)


@dataclass
class _WipePlan:
    target_name: str
    artifact_dirs: set[Path] = field(default_factory=set)
    bundle_paths: set[Path] = field(default_factory=set)
    suffixes: set[str] = field(default_factory=set)
    names: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class _ResolvedWipeTarget:
    target_name: str
    owner: Mapping[str, Any] | None


@dataclass(frozen=True)
class _WipeCatalog:
    artifacts: tuple[_ArtifactRecord, ...]
    bundles: tuple[_BundleRecord, ...]


@dataclass(frozen=True)
class _WipeExecution:
    artifact_dirs_removed: set[Path]
    bundle_paths_removed: set[Path]
    registry_names_removed: set[str]
    dismissed_index_entries_removed: int
    notifications_dismissed: int
    killed_processes: int
    errors: tuple[str, ...]


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

    catalog: _WipeCatalog | None = None
    plans: dict[int, _WipePlan] = {}
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
            catalog = _load_wipe_catalog()
        plan = _build_wipe_plan(owner, target.target_name, catalog=catalog)
        if not plan.names:
            plan.names.add(target.target_name)
        plans[index] = plan

    if plans:
        execution = _execute_wipe_plan(_merge_wipe_plans(tuple(plans.values())))
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
    plan = _build_wipe_plan(owner, name)
    if not plan.names:
        plan.names.add(name)
    return AgentNameWipePreview(
        artifact_dirs=tuple(sorted(str(path) for path in plan.artifact_dirs)),
        bundle_paths=tuple(sorted(str(path) for path in plan.bundle_paths)),
        names=tuple(sorted(plan.names)),
        container_kind=container_kind,
    )


def _build_wipe_plan(
    owner: Mapping[str, Any],
    target_name: str,
    *,
    catalog: _WipeCatalog | None = None,
) -> _WipePlan:
    plan = _WipePlan(target_name=target_name)
    plan.names.add(target_name)
    _seed_owner(plan, owner)

    if catalog is None:
        catalog = _load_wipe_catalog()
    changed = True
    while changed:
        changed = False
        for artifact_record in catalog.artifacts:
            if (
                _artifact_related(artifact_record, plan)
                and artifact_record.path not in plan.artifact_dirs
            ):
                _add_artifact_record(plan, artifact_record)
                changed = True
        for bundle_record in catalog.bundles:
            if (
                _bundle_related(bundle_record, plan)
                and bundle_record.path not in plan.bundle_paths
            ):
                _add_bundle_record(plan, bundle_record)
                changed = True
    return plan


def _load_wipe_catalog() -> _WipeCatalog:
    return _WipeCatalog(
        artifacts=tuple(_scan_artifacts()),
        bundles=tuple(_scan_bundles()),
    )


def _merge_wipe_plans(plans: Sequence[_WipePlan]) -> _WipePlan:
    merged = _WipePlan(target_name="batch")
    for plan in plans:
        merged.artifact_dirs.update(plan.artifact_dirs)
        merged.bundle_paths.update(plan.bundle_paths)
        merged.suffixes.update(plan.suffixes)
        merged.names.update(plan.names)
    return merged


def _execute_wipe_plan(plan: _WipePlan) -> _WipeExecution:
    errors: list[str] = []
    killed = _terminate_live_artifacts(plan, errors)
    removed_artifacts = _remove_artifact_dirs(plan.artifact_dirs, errors)
    delete_agent_artifact_index_artifacts(removed_artifacts)
    removed_bundles = _remove_bundle_paths(plan.bundle_paths, plan.suffixes, errors)
    dismissed_removed = _remove_dismissed_index_entries(plan.suffixes, errors)
    if plan.bundle_paths or dismissed_removed:
        try:
            sync_dismissed_agent_artifact_index(force=True)
        except Exception:
            pass
    notifications = _dismiss_related_notifications(plan, errors)

    registry_names_removed = set(plan.names)
    try:
        registry = rebuild_name_registry()
        entries = registry.get("entries")
        if isinstance(entries, dict):
            remaining = set(entries)
            registry_names_removed = {
                name for name in plan.names if name not in remaining
            }
    except Exception as exc:  # pragma: no cover - defensive best effort
        errors.append(f"registry rebuild failed: {exc}")

    return _WipeExecution(
        artifact_dirs_removed=removed_artifacts,
        bundle_paths_removed=removed_bundles,
        registry_names_removed=registry_names_removed,
        dismissed_index_entries_removed=dismissed_removed,
        notifications_dismissed=notifications,
        killed_processes=killed,
        errors=tuple(errors),
    )


def _path_result(paths: set[Path]) -> tuple[str, ...]:
    return tuple(sorted(str(path) for path in paths))


def _seed_owner(plan: _WipePlan, owner: Mapping[str, Any]) -> None:
    raw_suffix = owner.get("raw_suffix")
    if isinstance(raw_suffix, str) and raw_suffix:
        plan.suffixes.add(raw_suffix)

    for key in ("name", "workflow_name", "agent_name"):
        value = owner.get(key)
        if isinstance(value, str) and value:
            plan.names.add(value)

    artifacts_dir = owner.get("artifacts_dir")
    if isinstance(artifacts_dir, str) and artifacts_dir:
        path = Path(artifacts_dir).expanduser().resolve(strict=False)
        plan.artifact_dirs.add(path)
        _seed_payload_path(plan, path / "agent_meta.json")
        _seed_payload_path(plan, path / "done.json")

    bundle_path = owner.get("bundle_path")
    if isinstance(bundle_path, str) and bundle_path:
        path = Path(bundle_path).expanduser().resolve(strict=False)
        plan.bundle_paths.add(path)
        _seed_payload_path(plan, path, bundle=True)


def _seed_payload_path(plan: _WipePlan, path: Path, *, bundle: bool = False) -> None:
    payload = _read_json_object(path)
    if payload is None:
        return
    plan.names.update(_payload_names(payload, bundle=bundle))
    raw_suffix = payload.get("raw_suffix")
    if isinstance(raw_suffix, str) and raw_suffix:
        plan.suffixes.add(raw_suffix)
    plan.suffixes.update(_payload_outgoing_suffixes(payload))


def _artifact_related(record: _ArtifactRecord, plan: _WipePlan) -> bool:
    return (
        record.path in plan.artifact_dirs
        or record.suffix in plan.suffixes
        or bool(record.names & plan.names)
        or bool(record.relation_refs & plan.suffixes)
    )


def _bundle_related(record: _BundleRecord, plan: _WipePlan) -> bool:
    return (
        record.path in plan.bundle_paths
        or (record.raw_suffix is not None and record.raw_suffix in plan.suffixes)
        or bool(record.names & plan.names)
        or bool(record.relation_refs & plan.suffixes)
    )


def _add_artifact_record(plan: _WipePlan, record: _ArtifactRecord) -> None:
    plan.artifact_dirs.add(record.path)
    plan.suffixes.add(record.suffix)
    plan.suffixes.update(record.outgoing_suffixes)
    plan.names.update(record.names)


def _add_bundle_record(plan: _WipePlan, record: _BundleRecord) -> None:
    plan.bundle_paths.add(record.path)
    if record.raw_suffix:
        plan.suffixes.add(record.raw_suffix)
    plan.suffixes.update(record.outgoing_suffixes)
    plan.names.update(record.names)


def _scan_artifacts() -> list[_ArtifactRecord]:
    projects_dir = sase_projects_dir()
    if not projects_dir.is_dir():
        return []

    records: list[_ArtifactRecord] = []
    for project_dir in _safe_iterdir(projects_dir):
        artifacts_root = project_dir / "artifacts"
        if not project_dir.is_dir() or not artifacts_root.is_dir():
            continue
        for workflow_dir in _safe_iterdir(artifacts_root):
            if not workflow_dir.is_dir():
                continue
            try:
                for artifact_dir in iter_agent_artifact_dirs(
                    project_dir.name,
                    workflow_dir.name,
                    projects_root=projects_dir,
                ):
                    if not artifact_dir.is_dir():
                        continue
                    meta = _read_json_object(artifact_dir / "agent_meta.json")
                    done = _read_json_object(artifact_dir / "done.json")
                    if meta is None and done is None:
                        continue
                    records.append(
                        _ArtifactRecord(
                            path=artifact_dir.resolve(strict=False),
                            suffix=artifact_dir.name,
                            project_name=project_dir.name,
                            names=_payload_names(meta) | _payload_names(done),
                            relation_refs=_payload_relation_refs(meta)
                            | _payload_relation_refs(done),
                            outgoing_suffixes=_payload_outgoing_suffixes(meta)
                            | _payload_outgoing_suffixes(done),
                        )
                    )
            except (OSError, RuntimeError, ValueError):
                # Unreadable or malformed unrelated artifact trees must not
                # prevent cleanup of owners already discovered elsewhere.
                continue
    return records


def _scan_bundles() -> list[_BundleRecord]:
    bundles_dir = sase_subdir("dismissed_bundles")
    if not bundles_dir.is_dir():
        return []

    records: list[_BundleRecord] = []
    for path in bundles_dir.rglob("*.json"):
        if not path.is_file():
            continue
        payload = _read_json_object(path)
        if payload is None:
            continue
        raw_suffix = payload.get("raw_suffix")
        records.append(
            _BundleRecord(
                path=path.resolve(strict=False),
                raw_suffix=raw_suffix if isinstance(raw_suffix, str) else None,
                names=_payload_names(payload, bundle=True),
                relation_refs=_payload_relation_refs(payload),
                outgoing_suffixes=_payload_outgoing_suffixes(payload),
            )
        )
    return records


def _terminate_live_artifacts(plan: _WipePlan, errors: list[str]) -> int:
    killed = 0
    for path in sorted(plan.artifact_dirs):
        if _terminate_artifact_process(path, errors):
            killed += 1
        _release_artifact_workspace(path)
    return killed


def _terminate_artifact_process(path: Path, errors: list[str]) -> bool:
    if (path / "done.json").exists():
        return False
    meta = _read_json_object(path / "agent_meta.json") or {}
    if not is_process_alive(meta, path):
        return False
    pid = meta.get("pid")
    if not isinstance(pid, int):
        return False
    try:
        os.killpg(pid, signal.SIGTERM)
        return True
    except ProcessLookupError:
        return False
    except PermissionError as exc:
        errors.append(f"permission denied killing pid {pid}: {exc}")
    except OSError as exc:
        errors.append(f"failed killing pid {pid}: {exc}")
    return False


def _release_artifact_workspace(path: Path) -> None:
    running_json = path / "running.json"
    if running_json.exists():
        try:
            running_json.unlink()
        except OSError:
            pass
        else:
            try:
                update_agent_artifact_index_for_marker_mutation(path)
            except Exception:
                pass

    project_dir = _project_dir_from_artifact(path)
    if project_dir is None or project_dir.name == "home":
        return
    from sase.ace.patch.project_spec_path import preferred_project_spec_path

    project_file = Path(preferred_project_spec_path(str(project_dir), project_dir.name))
    if not project_file.exists():
        return

    try:
        from sase.running_field import get_claimed_workspaces, release_workspace

        for claim in get_claimed_workspaces(str(project_file)):
            if claim.artifacts_timestamp != path.name:
                continue
            release_workspace(
                str(project_file), claim.workspace_num, claim.workflow, claim.cl_name
            )
    except Exception:
        pass


def _remove_artifact_dirs(paths: set[Path], errors: list[str]) -> set[Path]:
    removed: set[Path] = set()
    for path in sorted(paths):
        if not path.exists():
            continue
        try:
            shutil.rmtree(path)
            removed.add(path)
        except FileNotFoundError:
            # A concurrent cleanup proc (or a second forced-reuse pass) may
            # have already removed this directory between the exists()
            # check above and rmtree(); that race is a success, not a
            # failure, matching the already-missing-bundle case below.
            continue
        except OSError as exc:
            errors.append(f"failed removing artifact dir {path}: {exc}")
    return removed


def _remove_bundle_paths(
    paths: set[Path], suffixes: set[str], errors: list[str]
) -> set[Path]:
    removed: set[Path] = set()
    for path in sorted(paths):
        try:
            path.unlink()
            removed.add(path)
        except FileNotFoundError:
            continue
        except OSError as exc:
            errors.append(f"failed removing dismissed bundle {path}: {exc}")

    try:
        from sase.ace import dismissed_agents
        from sase.ace.dismissed_bundle_index import delete_bundle_summaries_for_suffixes

        delete_bundle_summaries_for_suffixes(
            dismissed_agents.dismissed_bundles_dir(), suffixes
        )
    except Exception:
        pass
    return removed


def _remove_dismissed_index_entries(suffixes: set[str], errors: list[str]) -> int:
    if not suffixes:
        return 0
    path = sase_home() / "dismissed_agents.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return 0
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"failed reading dismissed index {path}: {exc}")
        return 0
    if not isinstance(data, list):
        return 0

    kept: list[Any] = []
    removed = 0
    for entry in data:
        raw_suffix = _dismissed_index_raw_suffix(entry)
        if raw_suffix in suffixes:
            removed += 1
        else:
            kept.append(entry)
    if removed == 0:
        return 0

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(kept, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        errors.append(f"failed writing dismissed index {path}: {exc}")
    return removed


def _dismiss_related_notifications(plan: _WipePlan, errors: list[str]) -> int:
    try:
        from sase.notifications import load_notifications, mark_many_dismissed

        notifications = load_notifications(include_dismissed=True)
        ids: list[str] = []
        for notification in notifications:
            if notification.dismissed:
                continue
            data = notification.action_data or {}
            if (
                data.get("raw_suffix") in plan.suffixes
                or data.get("agent_name") in plan.names
                or data.get("name") in plan.names
            ):
                ids.append(notification.id)
        return mark_many_dismissed(ids)
    except Exception as exc:
        errors.append(f"failed dismissing notifications: {exc}")
        return 0


def _payload_names(
    payload: Mapping[str, Any] | None, *, bundle: bool = False
) -> set[str]:
    if not payload:
        return set()
    keys = (
        ("agent_name", "workflow_name", "name") if bundle else ("name", "workflow_name")
    )
    return {
        value for key in keys if isinstance((value := payload.get(key)), str) and value
    }


def _payload_relation_refs(payload: Mapping[str, Any] | None) -> set[str]:
    if not payload:
        return set()
    keys = ("parent_timestamp", "retry_of_timestamp", "retry_chain_root_timestamp")
    return {
        value for key in keys if isinstance((value := payload.get(key)), str) and value
    }


def _payload_outgoing_suffixes(payload: Mapping[str, Any] | None) -> set[str]:
    if not payload:
        return set()
    value = payload.get("retried_as_timestamp")
    return {value} if isinstance(value, str) and value else set()


def _dismissed_index_raw_suffix(entry: Any) -> str | None:
    if isinstance(entry, list) and len(entry) == 3 and isinstance(entry[2], str):
        return entry[2]
    if isinstance(entry, dict):
        raw = entry.get("raw_suffix")
        if isinstance(raw, str):
            return raw
    return None


def _project_dir_from_artifact(path: Path) -> Path | None:
    parts = path.parts
    try:
        idx = parts.index("projects")
    except ValueError:
        return None
    if idx + 1 >= len(parts):
        return None
    return Path(*parts[: idx + 2])


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _safe_iterdir(path: Path) -> list[Path]:
    try:
        return list(path.iterdir())
    except OSError:
        return []


def _str_or_empty(value: Any) -> str:
    return value if isinstance(value, str) else ""
