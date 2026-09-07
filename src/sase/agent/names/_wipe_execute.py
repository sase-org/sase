"""Wipe-plan execution for the agent-name wipe pipeline."""

from __future__ import annotations

import json
import os
import shutil
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.agent.names._common import is_process_alive
from sase.agent.names._registry import rebuild_name_registry
from sase.agent.names._wipe_payload import read_json_object
from sase.agent.names._wipe_plan import WipePlan
from sase.core.agent_artifact_index_lifecycle import (
    delete_agent_artifact_index_artifacts,
    sync_dismissed_agent_artifact_index,
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.paths import sase_home


@dataclass(frozen=True)
class _WipeExecution:
    artifact_dirs_removed: set[Path]
    bundle_paths_removed: set[Path]
    registry_names_removed: set[str]
    dismissed_index_entries_removed: int
    notifications_dismissed: int
    killed_processes: int
    errors: tuple[str, ...]


def execute_wipe_plan(plan: WipePlan) -> _WipeExecution:
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


def _terminate_live_artifacts(plan: WipePlan, errors: list[str]) -> int:
    killed = 0
    for path in sorted(plan.artifact_dirs):
        if _terminate_artifact_process(path, errors):
            killed += 1
        _release_artifact_workspace(path)
    return killed


def _terminate_artifact_process(path: Path, errors: list[str]) -> bool:
    if (path / "done.json").exists():
        return False
    meta = read_json_object(path / "agent_meta.json") or {}
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


def _dismiss_related_notifications(plan: WipePlan, errors: list[str]) -> int:
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
