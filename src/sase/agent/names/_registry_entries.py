"""Entry helpers for the durable agent-name registry."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.core.agent_artifact_paths import parse_agent_artifact_path


def dotted_namespace_prefixes(name: str) -> set[str]:
    """Return every dotted-segment prefix of *name* (including *name* itself)."""
    parts = name.split(".")
    return {".".join(parts[: i + 1]) for i in range(len(parts))}


def entry_belongs_to_artifact(entry: dict[str, Any], artifact_dir: Path) -> bool:
    existing_dir = entry.get("artifacts_dir")
    if not isinstance(existing_dir, str) or not existing_dir:
        return False
    existing_path = Path(existing_dir).expanduser().resolve(strict=False)
    return existing_path == artifact_dir


def entry_has_other_owner(entry: dict[str, Any], artifact_dir: Path) -> bool:
    if not entry_belongs_to_artifact(entry, artifact_dir):
        return True
    collision_owners = entry.get("collision_owners")
    if not isinstance(collision_owners, list):
        return False
    for owner in collision_owners:
        if isinstance(owner, dict) and not entry_belongs_to_artifact(
            owner, artifact_dir
        ):
            return True
    return False


def entry_owner_missing(entry: dict[str, Any]) -> bool:
    if entry.get("reservation_kind") in {"planned", "planned_clan"}:
        return False
    source = entry.get("source")
    if source == "artifact":
        artifacts_dir = entry.get("artifacts_dir")
        if isinstance(artifacts_dir, str) and not Path(artifacts_dir).exists():
            return True
    elif source == "dismissed_bundle":
        bundle_path = entry.get("bundle_path")
        if isinstance(bundle_path, str) and not Path(bundle_path).is_file():
            return True
    collision_owners = entry.get("collision_owners")
    if isinstance(collision_owners, list):
        for owner in collision_owners:
            if isinstance(owner, dict) and entry_owner_missing(owner):
                return True
    return False


def owner_from_artifact_name(
    artifact_dir: Path,
    name: str,
    *,
    reservation_kind: str,
    template_namespace: str | None = None,
) -> dict[str, Any]:
    info = parse_agent_artifact_path(artifact_dir)
    project_name: str | None
    workflow_name: str
    raw_suffix: str
    if info is not None:
        project_name = info.project_name
        workflow_name = info.workflow_dir_name
        raw_suffix = info.timestamp
    else:
        workflow_dir = artifact_dir.parent
        project_dir = (
            workflow_dir.parent.parent
            if workflow_dir.parent.name == "artifacts"
            else None
        )
        project_name = project_dir.name if project_dir is not None else None
        workflow_name = workflow_dir.name
        raw_suffix = artifact_dir.name
    entry: dict[str, Any] = {
        "source": "artifact",
        "name": name,
        "project_name": project_name,
        "workflow_dir": workflow_name,
        "raw_suffix": raw_suffix,
        "artifacts_dir": str(artifact_dir),
        "state": (
            "planned"
            if reservation_kind == "planned"
            else "done"
            if (artifact_dir / "done.json").exists()
            else "active"
        ),
        "created_at": raw_suffix,
        "reservation_kind": reservation_kind,
    }
    if reservation_kind == "planned":
        entry["reserved_at"] = datetime.now(UTC).isoformat()
    if template_namespace is not None:
        entry["template_namespace"] = template_namespace
    return entry
