"""Private helpers shared by agent artifact modules."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.core.agent_artifact_types import (
    AgentArtifact,
    AgentArtifactAssociation,
    artifact_association_from_dir,
)


def association_from_metadata(
    agent_artifacts_dir: Path | str,
    *,
    done: dict[str, Any] | None = None,
    agent_meta: dict[str, Any] | None = None,
) -> AgentArtifactAssociation:
    artifacts_dir = Path(agent_artifacts_dir).expanduser()
    done_data = (
        done if done is not None else read_json_object(artifacts_dir / "done.json")
    )
    meta_data = (
        agent_meta
        if agent_meta is not None
        else read_json_object(artifacts_dir / "agent_meta.json")
    )
    agent_name = first_str(done_data.get("name"), meta_data.get("name"))
    return artifact_association_from_dir(artifacts_dir, agent_name=agent_name)


def dedupe_artifacts(artifacts: list[AgentArtifact]) -> list[AgentArtifact]:
    seen: set[str] = set()
    deduped: list[AgentArtifact] = []
    for artifact in artifacts:
        key = path_key(artifact.path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(artifact)
    return deduped


def matches_association(
    artifact: AgentArtifact,
    association: AgentArtifactAssociation,
) -> bool:
    if artifact.agent_artifacts_dir == association.agent_artifacts_dir:
        return True
    return (
        artifact.project is not None
        and artifact.project == association.project
        and artifact.raw_timestamp is not None
        and artifact.raw_timestamp == association.raw_timestamp
    )


def artifact_id(
    prefix: str,
    association: AgentArtifactAssociation,
    path: Path | str,
    label: str,
) -> str:
    identity = "|".join(
        [
            association.project or "",
            association.workflow or "",
            association.raw_timestamp or "",
            association.agent_artifacts_dir,
            path_key(path),
            label,
        ]
    )
    return f"{prefix}:{hash_text(identity)[:24]}"


def path_key(path: Path | str) -> str:
    expanded = Path(path).expanduser()
    return str(expanded.resolve(strict=False))


def hash_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def safe_segment(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    return safe.strip(".-")[:80]


def read_json_object(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def read_markdown_pdf_source_paths(artifacts_dir: Path) -> dict[str, str]:
    rows = _read_json_array(artifacts_dir / "markdown_pdfs" / "index.json")
    sources_by_pdf: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        pdf_path = row.get("pdf_path")
        source_path = row.get("source_path")
        if isinstance(pdf_path, str) and pdf_path and isinstance(source_path, str):
            sources_by_pdf[path_key(pdf_path)] = source_path
    return sources_by_pdf


def filter_duplicate_home_plan_paths(
    plan_paths: list[str],
    *,
    workspace_dir: str | None,
) -> list[str]:
    workspace_plan_names = {
        Path(plan_path).name
        for plan_path in plan_paths
        if _is_inside_dir(plan_path, workspace_dir)
    }
    if not workspace_plan_names:
        return plan_paths
    return [
        plan_path
        for plan_path in plan_paths
        if not (
            Path(plan_path).name in workspace_plan_names
            and _is_home_plan_path(plan_path)
        )
    ]


def _read_json_array(path: Path) -> list[Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _is_home_plan_path(path: Path | str) -> bool:
    return _is_inside_dir(path, Path.home() / ".sase" / "plans")


def _is_inside_dir(path: Path | str, parent: Path | str | None) -> bool:
    if parent is None:
        return False
    try:
        _resolved_path(path).relative_to(_resolved_path(parent))
    except (OSError, ValueError):
        return False
    return True


def _resolved_path(path: Path | str) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def first_str(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None


def coerce_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def unique_values(*values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        key = path_key(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def label_for_path(path: str, *, fallback: str) -> str:
    name = Path(path).name
    return name or fallback


def file_created_at(path: Path | str) -> str | None:
    try:
        stat = Path(path).expanduser().stat()
    except OSError:
        return None
    return datetime.fromtimestamp(stat.st_mtime, UTC).isoformat()


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
