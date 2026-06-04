"""Persistent reservation index for permanent agent names.

Registry rebuilds scan artifacts across every project lifecycle state so
archiving or closing a project does not free names that still belong to stored
agent history.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import UTC, datetime
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from sase.agent.names._common import extract_auto_name_prefix
from sase.core.paths import sase_home, sase_projects_dir, sase_subdir

SCHEMA_VERSION = 1
INDEX_FILENAME = "agent_name_registry.json"

_CACHE_PATH: Path | None = None
_CACHE_SIGNATURE: tuple[int, int] | None = None
_CACHE_DATA: dict[str, Any] | None = None


def _registry_path() -> Path:
    """Return the durable agent-name registry path."""
    return sase_home() / INDEX_FILENAME


def lookup_registered_name(name: str) -> dict[str, Any] | None:
    """Return registry owner metadata for *name*, if reserved."""
    entry = load_name_registry()["entries"].get(name)
    return dict(entry) if isinstance(entry, dict) else None


def is_name_reserved(name: str) -> bool:
    """Return whether *name* is reserved by an existing agent."""
    return name in load_name_registry()["entries"]


def get_reserved_agent_names() -> set[str]:
    """Return every name currently reserved by the registry."""
    return set(load_name_registry()["entries"])


def get_reserved_agent_name_map() -> dict[str, str]:
    """Return ``{name: owner_path}`` for registered names with a known owner path."""
    out: dict[str, str] = {}
    for name, entry in load_name_registry()["entries"].items():
        if not isinstance(entry, dict):
            continue
        owner_path = entry.get("artifacts_dir") or entry.get("bundle_path")
        if isinstance(owner_path, str) and owner_path:
            out[name] = owner_path
    return out


def lowest_name_suggestion(base: str) -> str:
    """Return the lowest available ``<base><N>`` suggestion."""
    reserved = get_reserved_agent_names()
    n = 1
    while True:
        candidate = f"{base}{n}"
        if candidate not in reserved:
            return candidate
        n += 1


def claim_registered_name(
    name: str, claiming_dir: str | Path, *, replace_existing: bool = False
) -> None:
    """Best-effort upsert of a claimed name into the registry."""
    with _registry_mutation_lock():
        artifact_dir = Path(claiming_dir).expanduser().resolve(strict=False)
        entries = dict(load_name_registry()["entries"])
        existing = entries.get(name)
        if isinstance(existing, dict) and not replace_existing:
            if _entry_has_other_owner(existing, artifact_dir):
                from sase.agent.names._common import NameCollisionError

                suggestion = lowest_name_suggestion(name)
                raise NameCollisionError(
                    f"agent name '{name}' is already taken; try '{suggestion}'"
                )
        entry = _owner_from_artifact_name(
            artifact_dir, name, reservation_kind="claimed"
        )
        entries[name] = entry
        _save_entries(entries)


def reserve_registered_name(name: str, claiming_dir: str | Path) -> None:
    """Reserve *name* for a not-yet-started agent artifacts directory.

    Planned launch reservations are intentionally collision-checked like
    explicit claims, but they use ``reservation_kind="planned"`` so callers can
    roll them back if the child process never starts. The child runner's later
    regular claim is idempotent because it uses the same artifacts owner.
    """
    with _registry_mutation_lock():
        artifact_dir = Path(claiming_dir).expanduser().resolve(strict=False)
        entries = dict(load_name_registry()["entries"])
        existing = entries.get(name)
        if isinstance(existing, dict) and _entry_has_other_owner(
            existing, artifact_dir
        ):
            from sase.agent.names._common import NameCollisionError

            suggestion = lowest_name_suggestion(name)
            raise NameCollisionError(
                f"agent name '{name}' is already taken; try '{suggestion}'"
            )
        entry = _owner_from_artifact_name(
            artifact_dir, name, reservation_kind="planned"
        )
        entries[name] = entry
        _save_entries(entries)


def release_planned_registered_name(name: str, claiming_dir: str | Path) -> None:
    """Remove a still-planned reservation for *name* owned by *claiming_dir*."""
    with _registry_mutation_lock():
        artifact_dir = Path(claiming_dir).expanduser().resolve(strict=False)
        entries = dict(load_name_registry()["entries"])
        existing = entries.get(name)
        if not isinstance(existing, dict):
            return
        if existing.get("reservation_kind") != "planned":
            return
        if not _entry_belongs_to_artifact(existing, artifact_dir):
            return
        entries.pop(name, None)
        _save_entries(entries)


def delete_registered_name(name: str) -> None:
    """Remove *name* from the registry."""
    with _registry_mutation_lock():
        entries = load_name_registry()["entries"]
        if name not in entries:
            return
        entries = dict(entries)
        entries.pop(name, None)
        _save_entries(entries)


def _entry_belongs_to_artifact(entry: dict[str, Any], artifact_dir: Path) -> bool:
    existing_dir = entry.get("artifacts_dir")
    if not isinstance(existing_dir, str) or not existing_dir:
        return False
    existing_path = Path(existing_dir).expanduser().resolve(strict=False)
    return existing_path == artifact_dir


def _entry_has_other_owner(entry: dict[str, Any], artifact_dir: Path) -> bool:
    if not _entry_belongs_to_artifact(entry, artifact_dir):
        return True
    collision_owners = entry.get("collision_owners")
    if not isinstance(collision_owners, list):
        return False
    for owner in collision_owners:
        if isinstance(owner, dict) and not _entry_belongs_to_artifact(
            owner, artifact_dir
        ):
            return True
    return False


def load_name_registry() -> dict[str, Any]:
    """Load the name registry, rebuilding once when absent or stale."""
    path = _registry_path()
    cached = _cached_registry(path)
    if cached is not None:
        return cached

    data = _read_registry(path)
    if data is None or _registry_file_is_stale(data):
        return rebuild_name_registry()

    _set_cache(path, data)
    return data


def rebuild_name_registry() -> dict[str, Any]:
    """Rebuild the registry by scanning existing artifacts and dismissed bundles."""
    with _registry_mutation_lock():
        entries: dict[str, dict[str, Any]] = {}
        _collect_planned_reservation_entries(entries)
        _collect_artifact_entries(entries)
        _collect_dismissed_bundle_entries(entries)
        data = _registry_data(entries)
        _write_registry(_registry_path(), data)
        _set_cache(_registry_path(), data)
        return data


def _registry_mutation_lock() -> AbstractContextManager[None]:
    from sase.agent.names._resume import agent_name_allocation_lock

    return agent_name_allocation_lock()


def _cached_registry(path: Path) -> dict[str, Any] | None:
    if _CACHE_PATH != path or _CACHE_DATA is None:
        return None
    try:
        signature = _file_signature(path)
    except OSError:
        return None
    if signature != _CACHE_SIGNATURE:
        return None
    if _registry_file_is_stale(_CACHE_DATA):
        return None
    return _CACHE_DATA


def _set_cache(path: Path, data: dict[str, Any]) -> None:
    global _CACHE_DATA, _CACHE_PATH, _CACHE_SIGNATURE
    _CACHE_PATH = path
    _CACHE_DATA = data
    try:
        _CACHE_SIGNATURE = _file_signature(path)
    except OSError:
        _CACHE_SIGNATURE = None


def _read_registry(path: Path) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("schema_version") != SCHEMA_VERSION:
        return None
    entries = data.get("entries")
    if not isinstance(entries, dict):
        return None
    return data


def _write_registry(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    replaced = False
    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        tmp_path = Path(tmp_name)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp_path, path)
        replaced = True
    finally:
        if tmp_path is not None and not replaced:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass


def _save_entries(entries: dict[str, Any]) -> None:
    with _registry_mutation_lock():
        data = _registry_data(entries)
        path = _registry_path()
        _write_registry(path, data)
        _set_cache(path, data)


def _registry_data(entries: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "source_signature": _source_signature(),
        "entries": dict(sorted(entries.items())),
    }


def _registry_file_is_stale(data: dict[str, Any]) -> bool:
    if data.get("source_signature") != _source_signature():
        return True
    entries = data.get("entries")
    if not isinstance(entries, dict):
        return True
    for entry in entries.values():
        if not isinstance(entry, dict):
            return True
        if _entry_owner_missing(entry):
            return True
    return False


def _entry_owner_missing(entry: dict[str, Any]) -> bool:
    if entry.get("reservation_kind") == "planned":
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
            if isinstance(owner, dict) and _entry_owner_missing(owner):
                return True
    return False


def _source_signature() -> dict[str, int]:
    paths = _source_signature_paths()
    count = 0
    max_mtime_ns = 0
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            continue
        count += 1
        max_mtime_ns = max(max_mtime_ns, stat.st_mtime_ns)
    return {"count": count, "max_mtime_ns": max_mtime_ns}


def _source_signature_paths() -> list[Path]:
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
                paths.extend(p for p in workflow_dir.iterdir() if p.is_dir())
            except OSError:
                continue
    return paths


def _file_signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return (stat.st_mtime_ns, stat.st_size)


def _collect_artifact_entries(entries: dict[str, dict[str, Any]]) -> None:
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
            try:
                artifact_iter = workflow_dir.iterdir()
            except OSError:
                continue
            for artifact_dir in artifact_iter:
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
                names = _names_from_payloads(meta, done)
                _add_owner_names(entries, names, owner)


def _collect_dismissed_bundle_entries(entries: dict[str, dict[str, Any]]) -> None:
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
        names = _names_from_payloads(bundle, None, bundle_name_keys=True)
        _add_owner_names(entries, names, owner)


def _collect_planned_reservation_entries(entries: dict[str, dict[str, Any]]) -> None:
    existing = _read_registry(_registry_path())
    if existing is None:
        return
    existing_entries = existing.get("entries")
    if not isinstance(existing_entries, dict):
        return
    for name, entry in existing_entries.items():
        if not isinstance(name, str) or not isinstance(entry, dict):
            continue
        if entry.get("reservation_kind") != "planned":
            continue
        entries[name] = dict(entry)


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


def _owner_from_artifact_name(
    artifact_dir: Path,
    name: str,
    *,
    reservation_kind: str,
) -> dict[str, Any]:
    workflow_dir = artifact_dir.parent
    project_dir = (
        workflow_dir.parent.parent if workflow_dir.parent.name == "artifacts" else None
    )
    entry: dict[str, Any] = {
        "source": "artifact",
        "name": name,
        "project_name": project_dir.name if project_dir is not None else None,
        "workflow_dir": workflow_dir.name,
        "raw_suffix": artifact_dir.name,
        "artifacts_dir": str(artifact_dir),
        "state": (
            "planned"
            if reservation_kind == "planned"
            else "done"
            if (artifact_dir / "done.json").exists()
            else "active"
        ),
        "created_at": artifact_dir.name,
        "reservation_kind": reservation_kind,
    }
    if reservation_kind == "planned":
        entry["reserved_at"] = datetime.now(UTC).isoformat()
    return entry


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
