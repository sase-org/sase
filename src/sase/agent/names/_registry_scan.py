"""Source scanning for the durable agent-name registry."""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any

from sase.agent.names._common import extract_auto_name_prefix
from sase.agent.names._registry_entries import (
    imported_v1_entry_provenance,
    imported_v2_entry_provenance,
    local_entry_provenance,
    owner_namespace_entry,
)
from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
    globalize_owned_agent_name,
    present_agent_name,
)
from sase.core.paths import sase_home, sase_projects_dir, sase_subdir

_MONTH_SHARD_RE = re.compile(r"^\d{6}$")
_DAY_SHARD_RE = re.compile(r"^\d{2}$")


def _directory_entries(path: Path) -> tuple[Path, ...]:
    """List a directory only after its entry set changes.

    Directory mtimes change when children are added, removed, or renamed. The
    cache therefore bounds repeated archive enumeration by the number of shard
    directories whose membership changed, while callers still stat every
    returned source path so in-place file rewrites remain visible.
    """

    try:
        stat = path.stat()
    except OSError:
        return ()
    return _directory_entries_for_signature(
        path,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
        stat.st_size,
    )


@lru_cache(maxsize=4_096)
def _directory_entries_for_signature(
    path: Path,
    mtime_ns: int,
    ctime_ns: int,
    size: int,
) -> tuple[Path, ...]:
    del mtime_ns, ctime_ns, size
    try:
        return tuple(path.iterdir())
    except OSError:
        return ()


def source_signature_paths() -> list[Path]:
    """Return registry-relevant source entries, excluding live run contents.

    Artifact directory names are durable registry inputs. Files created inside a
    running artifact directory are not, so including that directory's mtime in
    the signature makes the registry permanently stale.
    """

    paths = [
        sase_home() / "dismissed_agents.json",
    ]
    dismissed_bundles = sase_subdir("dismissed_bundles")
    bundle_root_entries = _directory_entries(dismissed_bundles)
    paths.extend(
        path
        for path in bundle_root_entries
        if path.suffix == ".json" and path.is_file()
    )
    for shard_dir in bundle_root_entries:
        if not shard_dir.is_dir():
            continue
        paths.extend(
            path
            for path in _directory_entries(shard_dir)
            if path.suffix == ".json" and path.is_file()
        )
    projects_dir = sase_projects_dir()
    project_dirs = [p for p in _directory_entries(projects_dir) if p.is_dir()]
    for project_dir in project_dirs:
        artifacts_dir = project_dir / "artifacts"
        workflow_dirs = [p for p in _directory_entries(artifacts_dir) if p.is_dir()]
        for workflow_dir in workflow_dirs:
            paths.extend(
                _artifact_dirs_for_workflow(
                    project_dir.name,
                    workflow_dir.name,
                    projects_dir,
                    workflow_dir,
                )
            )
    return paths


def _artifact_dirs_for_workflow(
    project_name: str,
    workflow_name: str,
    projects_dir: Path,
    workflow_dir: Path,
) -> tuple[Path, ...]:
    """Cache the core artifact walk until a containing directory changes."""

    return _artifact_dirs_for_signature(
        project_name,
        workflow_name,
        projects_dir,
        _artifact_tree_signature(workflow_dir),
    )


def _artifact_tree_signature(
    workflow_dir: Path,
) -> tuple[tuple[str, int, int, int], ...]:
    """Fingerprint only artifact containers, never each artifact directory."""

    directories = [workflow_dir]
    for month_dir in _directory_entries(workflow_dir):
        if not month_dir.is_dir() or not _MONTH_SHARD_RE.fullmatch(month_dir.name):
            continue
        directories.append(month_dir)
        directories.extend(
            day_dir
            for day_dir in _directory_entries(month_dir)
            if day_dir.is_dir() and _DAY_SHARD_RE.fullmatch(day_dir.name)
        )
    signature: list[tuple[str, int, int, int]] = []
    for directory in directories:
        try:
            stat = directory.stat()
        except OSError:
            continue
        signature.append(
            (
                str(directory),
                stat.st_mtime_ns,
                stat.st_ctime_ns,
                stat.st_size,
            )
        )
    return tuple(signature)


@lru_cache(maxsize=1_024)
def _artifact_dirs_for_signature(
    project_name: str,
    workflow_name: str,
    projects_dir: Path,
    tree_signature: tuple[tuple[str, int, int, int], ...],
) -> tuple[Path, ...]:
    """Delegate actual layout interpretation to the shared core helper."""

    del tree_signature
    try:
        return tuple(
            iter_agent_artifact_dirs(
                project_name,
                workflow_name,
                projects_root=projects_dir,
            )
        )
    except OSError:
        return ()


def collect_planned_reservation_entries(
    entries: dict[str, dict[str, Any]],
    existing: dict[str, Any] | None,
    identity: AgentIdentitySnapshot | None = None,
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
        retained = dict(entry)
        if retained.get("origin") in {None, "local"} and identity is not None:
            retained.update(local_entry_provenance(name, identity))
        entries[name] = retained


def collect_artifact_entries(
    entries: dict[str, dict[str, Any]],
    identity: AgentIdentitySnapshot | None = None,
) -> None:
    if identity is None:
        identity = AgentIdentitySnapshot.current()
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
                provenance_payload = meta or done or {}
                _add_owner_clan(
                    entries,
                    _clan_from_payload(meta),
                    owner,
                    provenance_payload,
                    identity,
                )
                family = _family_from_payload(meta)
                _add_owner_family(
                    entries,
                    family,
                    owner,
                    provenance_payload,
                    identity,
                )
                names = _names_from_payloads(meta, done)
                if family is not None:
                    names.discard(family)
                _add_owner_names(
                    entries,
                    names,
                    owner,
                    provenance_payload,
                    identity,
                )


def collect_dismissed_bundle_entries(
    entries: dict[str, dict[str, Any]],
    identity: AgentIdentitySnapshot | None = None,
) -> None:
    if identity is None:
        identity = AgentIdentitySnapshot.current()
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
        _add_owner_clan(
            entries,
            _clan_from_payload(bundle),
            owner,
            bundle,
            identity,
        )
        family = _family_from_payload(bundle)
        _add_owner_family(entries, family, owner, bundle, identity)
        names = _names_from_payloads(bundle, None, bundle_name_keys=True)
        if family is not None:
            names.discard(family)
        _add_owner_names(entries, names, owner, bundle, identity)


def collect_owner_namespace_entries(
    entries: dict[str, dict[str, Any]],
    identity: AgentIdentitySnapshot,
) -> None:
    """Reserve configured and observed foreign owner roots."""
    owner = identity.owner
    for machine_name in identity.sibling_machines:
        if owner is not None and machine_name == owner.machine_name:
            continue
        entries.setdefault(
            machine_name,
            owner_namespace_entry(
                machine_name,
                namespace_kind="sibling_machine",
            ),
        )

    for entry in tuple(entries.values()):
        if not isinstance(entry, dict):
            continue
        source_owner = _source_owner_from_payload(entry)
        if source_owner is not None and (
            owner is None or source_owner.username != owner.username
        ):
            entries.setdefault(
                source_owner.username,
                owner_namespace_entry(
                    source_owner.username,
                    namespace_kind="foreign_username",
                    source_owner=source_owner,
                ),
            )
        legacy_machine = entry.get("legacy_source_machine")
        if isinstance(legacy_machine, str) and legacy_machine:
            entries.setdefault(
                legacy_machine,
                owner_namespace_entry(
                    legacy_machine,
                    namespace_kind="legacy_source_machine",
                ),
            )


def _add_owner_names(
    entries: dict[str, dict[str, Any]],
    names: set[str],
    owner: dict[str, Any],
    provenance_payload: dict[str, Any],
    identity: AgentIdentitySnapshot,
) -> None:
    for name in names:
        _add_owner_name(
            entries,
            name,
            owner,
            provenance_payload,
            identity,
            reservation_kind="claimed",
        )
        prefix = extract_auto_name_prefix(name, identity=identity)
        if prefix is None:
            continue
        # A rebuild preserves the spelling already stored in the artifact.
        # Qualified artifacts therefore derive qualified auto-prefix entries,
        # while legacy bare artifacts remain bare instead of being migrated.
        stored_prefix = _stored_prefix_for_historical_name(name, prefix, identity)
        if stored_prefix not in names:
            _add_owner_name(
                entries,
                stored_prefix,
                owner,
                provenance_payload,
                identity,
                reservation_kind="auto_prefix",
            )


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


def _family_from_payload(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict) or payload.get("agent_family_parallel") is True:
        return None
    family = payload.get("agent_family")
    return family if isinstance(family, str) and family else None


def _add_owner_clan(
    entries: dict[str, dict[str, Any]],
    clan: tuple[str, str] | None,
    owner: dict[str, Any],
    provenance_payload: dict[str, Any],
    identity: AgentIdentitySnapshot,
) -> None:
    if clan is None:
        return
    name, generation = clan
    entry = {
        **owner,
        **_entry_provenance(name, provenance_payload, identity),
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
    _add_owner_name(
        entries,
        name,
        owner,
        provenance_payload,
        identity,
        reservation_kind="claimed",
    )


def _add_owner_family(
    entries: dict[str, dict[str, Any]],
    name: str | None,
    owner: dict[str, Any],
    provenance_payload: dict[str, Any],
    identity: AgentIdentitySnapshot,
) -> None:
    if name is None:
        return
    entry = {
        **owner,
        **_entry_provenance(name, provenance_payload, identity),
        "name": name,
        "reservation_kind": "family",
        "container_kind": "family",
    }
    existing = entries.get(name)
    if not isinstance(existing, dict):
        entries[name] = entry
        return
    if existing.get("container_kind") == "family":
        return
    if _entry_owner_identity(existing) == _entry_owner_identity(entry):
        entries[name] = entry
        return
    _add_owner_name(
        entries,
        name,
        owner,
        provenance_payload,
        identity,
        reservation_kind="claimed",
    )


def _add_owner_name(
    entries: dict[str, dict[str, Any]],
    name: str,
    owner: dict[str, Any],
    provenance_payload: dict[str, Any],
    identity: AgentIdentitySnapshot,
    *,
    reservation_kind: str,
) -> None:
    entry = {
        **owner,
        **_entry_provenance(name, provenance_payload, identity),
        "name": name,
        "reservation_kind": reservation_kind,
    }
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


def _entry_provenance(
    name: str,
    payload: dict[str, Any],
    identity: AgentIdentitySnapshot,
) -> dict[str, Any]:
    source_owner = _source_owner_from_payload(payload)
    canonical_global_name = payload.get("canonical_global_name")
    digest = payload.get("imported_digest")
    if not isinstance(digest, str):
        digest = payload.get("imported_snapshot_digest")
    if (
        source_owner is not None
        and isinstance(canonical_global_name, str)
        and canonical_global_name
        and isinstance(digest, str)
    ):
        return imported_v2_entry_provenance(
            source_owner,
            canonical_global_name,
            digest,
        )
    source_machine = payload.get("imported_from_machine")
    if isinstance(source_machine, str) and source_machine:
        return imported_v1_entry_provenance(
            source_machine,
            digest if isinstance(digest, str) else "",
        )
    return local_entry_provenance(name, identity)


def _source_owner_from_payload(
    payload: dict[str, Any],
) -> AgentOwnerIdentity | None:
    value = payload.get("source_owner")
    if not isinstance(value, dict):
        value = payload.get("imported_source_owner")
    if not isinstance(value, dict):
        return None
    username = value.get("username")
    machine_name = value.get("machine_name")
    if not isinstance(username, str) or not isinstance(machine_name, str):
        return None
    return AgentOwnerIdentity(username, machine_name)


def _stored_prefix_for_historical_name(
    name: str,
    prefix: str,
    identity: AgentIdentitySnapshot,
) -> str:
    """Keep an auto-prefix beside the historical artifact's exact spelling."""
    owner = identity.owner
    if owner is None or present_agent_name(name, identity) == name:
        return prefix
    if name.startswith(f"{owner.username}.{owner.machine_name}."):
        return globalize_owned_agent_name(prefix, identity)
    if name.startswith(f"{owner.machine_name}."):
        return f"{owner.machine_name}.{prefix}"
    return prefix


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
