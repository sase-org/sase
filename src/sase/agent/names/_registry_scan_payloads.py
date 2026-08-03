"""Payload decoding helpers for registry source scans."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home


def clan_from_payload(payload: dict[str, Any] | None) -> tuple[str, str] | None:
    if not isinstance(payload, dict):
        return None
    clan = payload.get("agent_clan")
    if not isinstance(clan, str) or not clan:
        family = payload.get("agent_family")
        if (
            payload.get("agent_family_parallel") is not True
            or not isinstance(family, str)
            or not family
        ):
            return None
        clan = family
    generation = payload.get("agent_clan_generation")
    if not isinstance(generation, str) or not generation:
        parent = payload.get("parent_timestamp")
        generation = parent if isinstance(parent, str) and parent else "legacy"
    return clan, generation


def family_from_payload(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict) or payload.get("agent_family_parallel") is True:
        return None
    family = payload.get("agent_family")
    return family if isinstance(family, str) and family else None


def names_from_payloads(
    primary: dict[str, Any] | None,
    secondary: dict[str, Any] | None,
    *,
    bundle_name_keys: bool = False,
) -> set[str]:
    names: set[str] = set()
    keys = (
        ("agent_name", "workflow_name")
        if bundle_name_keys
        else ("name", "workflow_name")
    )
    for payload in (primary, secondary):
        if not isinstance(payload, dict):
            continue
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value:
                names.add(value)
    return names


def artifact_owner(
    *,
    project_dir: Path,
    workflow_dir: Path,
    artifact_dir: Path,
    state: str,
) -> dict[str, Any]:
    return {
        "source": "artifact",
        "project_name": project_dir.name,
        "workflow_dir": workflow_dir.name,
        "raw_suffix": artifact_dir.name,
        "artifacts_dir": str(artifact_dir),
        "state": state,
        "created_at": artifact_dir.name,
    }


def bundle_owner(path: Path, bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "dismissed_bundle",
        "project_name": _project_name_from_bundle(bundle),
        "workflow_dir": "ace-run",
        "raw_suffix": _str_or_none(bundle.get("raw_suffix")) or path.stem,
        "artifacts_dir": _str_or_none(bundle.get("artifacts_dir")),
        "bundle_path": str(path),
        "state": "dismissed",
        "created_at": _str_or_none(bundle.get("raw_suffix")) or path.stem,
    }


def _project_name_from_bundle(bundle: dict[str, Any]) -> str | None:
    project_file = bundle.get("project_file")
    if isinstance(project_file, str) and project_file:
        return Path(project_file).parent.name
    artifacts_dir = bundle.get("artifacts_dir")
    if isinstance(artifacts_dir, str) and artifacts_dir:
        parts = Path(artifacts_dir).parts
        try:
            idx = parts.index("projects")
        except ValueError:
            return None
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return None


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def load_dismissed_suffixes() -> set[str]:
    path = sase_home() / "dismissed_agents.json"
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(data, list):
        return set()
    suffixes: set[str] = set()
    for entry in data:
        raw_suffix: object | None = None
        if isinstance(entry, list) and len(entry) == 3:
            raw_suffix = entry[2]
        elif isinstance(entry, dict):
            raw_suffix = entry.get("raw_suffix")
        if isinstance(raw_suffix, str):
            suffixes.add(raw_suffix)
    return suffixes
