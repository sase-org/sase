"""Source scanning for the durable agent-name registry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sase.agent.names._common import extract_auto_name_prefix
from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.core.paths import sase_home, sase_projects_dir, sase_subdir


def source_signature_paths() -> list[Path]:
    paths = [
        sase_projects_dir(),
        sase_home() / "dismissed_agents.json",
        sase_subdir("dismissed_bundles"),
    ]
    projects_dir = sase_projects_dir()
    try:
        project_dirs = [p for p in projects_dir.iterdir() if p.is_dir()]
    except OSError:
        project_dirs = []
    for project_dir in project_dirs:
        artifacts_dir = project_dir / "artifacts"
        paths.append(artifacts_dir)
        try:
            workflow_dirs = [p for p in artifacts_dir.iterdir() if p.is_dir()]
        except OSError:
            workflow_dirs = []
        paths.extend(workflow_dirs)
        for workflow_dir in workflow_dirs:
            try:
                children = [p for p in workflow_dir.iterdir() if p.is_dir()]
            except OSError:
                continue
            paths.extend(children)
            for child in children:
                if not _looks_like_month_shard(child.name):
                    continue
                try:
                    paths.extend(p for p in child.iterdir() if p.is_dir())
                except OSError:
                    continue
    return paths


def _looks_like_month_shard(name: str) -> bool:
    return len(name) == 6 and name.isdigit()


def collect_planned_reservation_entries(
    entries: dict[str, dict[str, Any]],
    existing: dict[str, Any] | None,
) -> None:
    if existing is None:
        return
    existing_entries = existing.get("entries")
    if not isinstance(existing_entries, dict):
        return
    for name, entry in existing_entries.items():
        if not isinstance(name, str) or not isinstance(entry, dict):
            continue
        if entry.get("reservation_kind") not in {"planned", "planned_clan"}:
            continue
        entries[name] = dict(entry)


def collect_artifact_entries(entries: dict[str, dict[str, Any]]) -> None:
    projects_dir = sase_projects_dir()
    if not projects_dir.is_dir():
        return
    dismissed_suffixes = _load_dismissed_suffixes()
    try:
        project_iter = projects_dir.iterdir()
    except OSError:
        return
    for project_dir in project_iter:
        artifacts_root = project_dir / "artifacts"
        if not project_dir.is_dir() or not artifacts_root.is_dir():
            continue
        try:
            workflow_iter = artifacts_root.iterdir()
        except OSError:
            continue
        for workflow_dir in workflow_iter:
            if not workflow_dir.is_dir():
                continue
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
                state = "done" if done is not None else "active"
                if artifact_dir.name in dismissed_suffixes:
                    state = "dismissed"
                owner = _artifact_owner(
                    project_dir=project_dir,
                    workflow_dir=workflow_dir,
                    artifact_dir=artifact_dir,
                    state=state,
                )
                _add_owner_clan(entries, _clan_from_payload(meta), owner)
                names = _names_from_payloads(meta, done)
                _add_owner_names(entries, names, owner)


def collect_dismissed_bundle_entries(entries: dict[str, dict[str, Any]]) -> None:
    bundles_dir = sase_subdir("dismissed_bundles")
    if not bundles_dir.is_dir():
        return
    try:
        paths = list(bundles_dir.rglob("*.json"))
    except OSError:
        return
    for path in paths:
        if not path.is_file():
            continue
        bundle = _read_json_object(path)
        if bundle is None:
            continue
        owner = _bundle_owner(path, bundle)
        _add_owner_clan(entries, _clan_from_payload(bundle), owner)
        names = _names_from_payloads(bundle, None, bundle_name_keys=True)
        _add_owner_names(entries, names, owner)


def _add_owner_names(
    entries: dict[str, dict[str, Any]],
    names: set[str],
    owner: dict[str, Any],
) -> None:
    for name in names:
        _add_owner_name(entries, name, owner, reservation_kind="claimed")
        prefix = extract_auto_name_prefix(name)
        if prefix is not None and prefix not in names:
            _add_owner_name(entries, prefix, owner, reservation_kind="auto_prefix")


def _clan_from_payload(payload: dict[str, Any] | None) -> tuple[str, str] | None:
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


def _add_owner_clan(
    entries: dict[str, dict[str, Any]],
    clan: tuple[str, str] | None,
    owner: dict[str, Any],
) -> None:
    if clan is None:
        return
    name, generation = clan
    entry = {
        **owner,
        "name": name,
        "reservation_kind": "clan",
        "container_kind": "clan",
        "clan_generation": generation,
    }
    existing = entries.get(name)
    if not isinstance(existing, dict):
        entries[name] = entry
        return
    if existing.get("container_kind") == "clan":
        if existing.get("reservation_kind") == "planned_clan" and (
            _entry_owner_identity(existing) == _entry_owner_identity(entry)
        ):
            entries[name] = entry
        return
    _add_owner_name(entries, name, owner, reservation_kind="claimed")


def _add_owner_name(
    entries: dict[str, dict[str, Any]],
    name: str,
    owner: dict[str, Any],
    *,
    reservation_kind: str,
) -> None:
    entry = {**owner, "name": name, "reservation_kind": reservation_kind}
    existing = entries.get(name)
    if not isinstance(existing, dict):
        entries[name] = entry
        return
    if _entry_owner_identity(existing) == _entry_owner_identity(entry):
        return
    collision_owners = existing.setdefault("collision_owners", [])
    if not isinstance(collision_owners, list):
        collision_owners = []
        existing["collision_owners"] = collision_owners
    new_identity = _entry_owner_identity(entry)
    for owner_entry in collision_owners:
        if (
            isinstance(owner_entry, dict)
            and _entry_owner_identity(owner_entry) == new_identity
        ):
            return
    collision_owners.append(entry)


def _entry_owner_identity(entry: dict[str, Any]) -> tuple[str, str] | None:
    source = entry.get("source")
    if source == "artifact":
        artifacts_dir = entry.get("artifacts_dir")
        if isinstance(artifacts_dir, str) and artifacts_dir:
            return source, artifacts_dir
    if source == "dismissed_bundle":
        bundle_path = entry.get("bundle_path")
        if isinstance(bundle_path, str) and bundle_path:
            return source, bundle_path
    return None


def _names_from_payloads(
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


def _artifact_owner(
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


def _bundle_owner(path: Path, bundle: dict[str, Any]) -> dict[str, Any]:
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


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _load_dismissed_suffixes() -> set[str]:
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
