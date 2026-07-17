"""Private helpers shared by artifact-file modules."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.core.artifact_file_types import (
    ArtifactFile,
    ArtifactFileAssociation,
    artifact_file_association_from_dir,
)


def artifact_file_association_from_metadata(
    agent_artifacts_dir: Path | str,
    *,
    done: dict[str, Any] | None = None,
    agent_meta: dict[str, Any] | None = None,
) -> ArtifactFileAssociation:
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
    return artifact_file_association_from_dir(artifacts_dir, agent_name=agent_name)


def dedupe_artifact_files(artifact_files: list[ArtifactFile]) -> list[ArtifactFile]:
    seen: set[str] = set()
    deduped: list[ArtifactFile] = []
    for artifact_file in artifact_files:
        key = path_key(artifact_file.path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(artifact_file)
    return deduped


def matches_association(
    artifact_file: ArtifactFile,
    association: ArtifactFileAssociation,
) -> bool:
    if artifact_file.agent_artifacts_dir == association.agent_artifacts_dir:
        return True
    return (
        artifact_file.project is not None
        and artifact_file.project == association.project
        and artifact_file.raw_timestamp is not None
        and artifact_file.raw_timestamp == association.raw_timestamp
    )


def artifact_file_id(
    prefix: str,
    association: ArtifactFileAssociation,
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


def selected_plan_path(
    *,
    done: dict[str, Any],
    agent_meta: dict[str, Any],
    plan_marker: dict[str, Any],
) -> str | None:
    """Choose the single canonical plan path for an agent artifact-file list."""

    archived_plan_path = first_str(
        plan_marker.get("plan_path"),
        agent_meta.get("plan_path"),
        done.get("plan_path"),
    )
    sdd_plan_path = first_str(
        agent_meta.get("sdd_plan_path"),
        done.get("sdd_plan_path"),
    )
    plan_committed = _first_strict_bool(
        agent_meta.get("plan_committed"),
        done.get("plan_committed"),
    )
    plan_action = first_str(
        agent_meta.get("plan_action"),
        done.get("plan_action"),
    )

    return select_canonical_plan_path(
        archived_plan_path=archived_plan_path,
        sdd_plan_path=sdd_plan_path,
        plan_committed=plan_committed,
        plan_action=plan_action,
    )


def select_canonical_plan_path(
    *,
    archived_plan_path: str | None,
    sdd_plan_path: str | None,
    plan_committed: bool | None,
    plan_action: str | None = None,
) -> str | None:
    """Choose one plan path from archived and canonical SDD references.

    Explicit commit state is authoritative. ``plan_action`` remains a
    compatibility signal for records written before ``plan_committed`` was
    projected into agent snapshots.
    """

    effective_committed = plan_committed
    if effective_committed is None and plan_action in {"commit", "tale", "epic"}:
        effective_committed = True

    if effective_committed is True:
        return sdd_plan_path or archived_plan_path
    if effective_committed is False:
        return archived_plan_path or sdd_plan_path

    if not archived_plan_path:
        return sdd_plan_path
    if not sdd_plan_path:
        return archived_plan_path
    if path_key(archived_plan_path) == path_key(sdd_plan_path):
        return sdd_plan_path
    if not _path_exists(archived_plan_path) and _path_exists(sdd_plan_path):
        return sdd_plan_path
    return archived_plan_path


def _read_json_array(path: Path) -> list[Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def first_str(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None


def _first_strict_bool(*values: Any) -> bool | None:
    for value in values:
        if type(value) is bool:
            return value
    return None


def coerce_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


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


def _path_exists(path: str) -> bool:
    try:
        return Path(path).expanduser().exists()
    except OSError:
        return False
