"""Filesystem catalog scan for the agent-name wipe pipeline."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sase.agent.names._wipe_payload import (
    payload_names,
    payload_outgoing_suffixes,
    read_json_object,
)
from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.core.paths import sase_projects_dir, sase_subdir


@dataclass
class ArtifactRecord:
    path: Path
    suffix: str
    project_name: str | None
    names: set[str] = field(default_factory=set)
    relation_refs: set[str] = field(default_factory=set)
    outgoing_suffixes: set[str] = field(default_factory=set)


@dataclass
class BundleRecord:
    path: Path
    raw_suffix: str | None
    names: set[str] = field(default_factory=set)
    relation_refs: set[str] = field(default_factory=set)
    outgoing_suffixes: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class WipeCatalog:
    artifacts: tuple[ArtifactRecord, ...]
    bundles: tuple[BundleRecord, ...]


def load_wipe_catalog() -> WipeCatalog:
    return WipeCatalog(
        artifacts=tuple(_scan_artifacts()),
        bundles=tuple(_scan_bundles()),
    )


def _scan_artifacts() -> list[ArtifactRecord]:
    projects_dir = sase_projects_dir()
    if not projects_dir.is_dir():
        return []

    records: list[ArtifactRecord] = []
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
                    meta = read_json_object(artifact_dir / "agent_meta.json")
                    done = read_json_object(artifact_dir / "done.json")
                    if meta is None and done is None:
                        continue
                    records.append(
                        ArtifactRecord(
                            path=artifact_dir.resolve(strict=False),
                            suffix=artifact_dir.name,
                            project_name=project_dir.name,
                            names=payload_names(meta) | payload_names(done),
                            relation_refs=_payload_relation_refs(meta)
                            | _payload_relation_refs(done),
                            outgoing_suffixes=payload_outgoing_suffixes(meta)
                            | payload_outgoing_suffixes(done),
                        )
                    )
            except (OSError, RuntimeError, ValueError):
                # Unreadable or malformed unrelated artifact trees must not
                # prevent cleanup of owners already discovered elsewhere.
                continue
    return records


def _scan_bundles() -> list[BundleRecord]:
    bundles_dir = sase_subdir("dismissed_bundles")
    if not bundles_dir.is_dir():
        return []

    records: list[BundleRecord] = []
    for path in bundles_dir.rglob("*.json"):
        if not path.is_file():
            continue
        payload = read_json_object(path)
        if payload is None:
            continue
        raw_suffix = payload.get("raw_suffix")
        records.append(
            BundleRecord(
                path=path.resolve(strict=False),
                raw_suffix=raw_suffix if isinstance(raw_suffix, str) else None,
                names=payload_names(payload, bundle=True),
                relation_refs=_payload_relation_refs(payload),
                outgoing_suffixes=payload_outgoing_suffixes(payload),
            )
        )
    return records


def _payload_relation_refs(payload: Mapping[str, Any] | None) -> set[str]:
    if not payload:
        return set()
    keys = ("parent_timestamp", "retry_of_timestamp", "retry_chain_root_timestamp")
    return {
        value for key in keys if isinstance((value := payload.get(key)), str) and value
    }


def _safe_iterdir(path: Path) -> list[Path]:
    try:
        return list(path.iterdir())
    except OSError:
        return []
