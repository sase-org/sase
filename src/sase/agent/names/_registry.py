"""Persistent reservation index for permanent agent names.

Registry rebuilds scan artifacts across every project lifecycle state so
archiving or closing a project does not free names that still belong to stored
agent history.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from contextlib import AbstractContextManager
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from sase.agent.names._registry_entries import (
    dotted_namespace_prefixes as _dotted_namespace_prefixes,
    entry_belongs_to_artifact as _entry_belongs_to_artifact,
    entry_has_other_owner as _entry_has_other_owner,
    entry_owner_missing as _entry_owner_missing,
    owner_from_artifact_name as _owner_from_artifact_name,
)
from sase.agent.names._registry_scan import (
    collect_artifact_entries as _collect_artifact_entries,
    collect_dismissed_bundle_entries as _collect_dismissed_bundle_entries,
    collect_planned_reservation_entries as _collect_planned_reservation_entries,
    source_signature_paths,
)
from sase.core.paths import sase_home
from sase.core.machine_hood_facade import (
    MachineHoodIdentity,
    canonical_local_agent_name_key,
    local_agent_name_lookup_candidates,
    qualify_local_agent_name,
    strip_local_agent_name,
)

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
    entries = load_name_registry()["entries"]
    identity = MachineHoodIdentity.current()
    for candidate in local_agent_name_lookup_candidates(name, identity):
        entry = entries.get(candidate)
        if isinstance(entry, dict):
            return dict(entry)
    return None


def is_name_reserved(name: str) -> bool:
    """Return whether *name* is reserved by an existing agent."""
    entries = load_name_registry()["entries"]
    identity = MachineHoodIdentity.current()
    return any(
        candidate in entries
        for candidate in local_agent_name_lookup_candidates(name, identity)
    )


def get_reserved_agent_names() -> set[str]:
    """Return every name currently reserved by the registry."""
    return set(load_name_registry()["entries"])


def get_reserved_clan_names() -> set[str]:
    """Return every name owned by a clan container."""
    return {
        name
        for name, entry in load_name_registry()["entries"].items()
        if isinstance(entry, dict) and entry.get("container_kind") == "clan"
    }


def get_reserved_family_names() -> set[str]:
    """Return every name owned by a sequential family container."""
    return {
        name
        for name, entry in load_name_registry()["entries"].items()
        if isinstance(entry, dict) and entry.get("container_kind") == "family"
    }


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
    identity = MachineHoodIdentity.current()
    visible_base = strip_local_agent_name(base, identity)
    reserved = {
        canonical_local_agent_name_key(name, identity)
        for name in get_reserved_agent_names()
    }
    n = 1
    while True:
        candidate = f"{visible_base}{n}"
        if canonical_local_agent_name_key(candidate, identity) not in reserved:
            return candidate
        n += 1


def claim_registered_name(
    name: str, claiming_dir: str | Path, *, replace_existing: bool = False
) -> None:
    """Best-effort upsert of a claimed name into the registry."""
    with _registry_mutation_lock():
        identity = MachineHoodIdentity.current()
        name = qualify_local_agent_name(name, identity)
        artifact_dir = Path(claiming_dir).expanduser().resolve(strict=False)
        entries = dict(load_name_registry()["entries"])
        storage_name, existing = _equivalent_entry(entries, name, identity)
        if isinstance(existing, dict) and existing.get("container_kind"):
            _raise_container_name_collision(name, existing)
        if isinstance(existing, dict) and not replace_existing:
            if _entry_has_other_owner(existing, artifact_dir):
                from sase.agent.names._common import NameCollisionError

                visible_name = strip_local_agent_name(name, identity)
                suggestion = lowest_name_suggestion(visible_name)
                raise NameCollisionError(
                    f"agent name '{visible_name}' is already taken; try '{suggestion}'"
                )
        entry = _owner_from_artifact_name(
            artifact_dir, storage_name, reservation_kind="claimed"
        )
        entries[storage_name] = entry
        _save_entries(entries)


def claim_imported_registered_name(
    name: str,
    source_machine: str,
    claiming_dir: str | Path,
    *,
    digest: str,
) -> None:
    """Claim an exact foreign machine-qualified imported agent name.

    Imported names deliberately bypass local qualification: a previously
    unknown hood such as ``zeus.worker`` must remain exactly that spelling,
    rather than becoming ``<local>.zeus.worker``. The source machine must
    match the durable prefix, and only the same imported owner may refresh its
    digest.
    """

    from sase.agents_sync.io import validate_machine, validate_qualified_name

    source_machine = validate_machine(source_machine)
    name = validate_qualified_name(name, source_machine)
    artifact_dir = Path(claiming_dir).expanduser().resolve(strict=False)
    with _registry_mutation_lock():
        entries = dict(load_name_registry()["entries"])
        existing = entries.get(name)
        if isinstance(existing, dict):
            same_import = (
                existing.get("reservation_kind") == "imported"
                and existing.get("imported_from_machine") == source_machine
                and _entry_belongs_to_artifact(existing, artifact_dir)
            )
            if not same_import:
                from sase.agent.names._common import NameCollisionError

                raise NameCollisionError(
                    f"imported agent name '{name}' is already reserved"
                )
        entry = _owner_from_artifact_name(
            artifact_dir,
            name,
            reservation_kind="imported",
        )
        entry["imported_from_machine"] = source_machine
        entry["imported_digest"] = digest
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
        identity = MachineHoodIdentity.current()
        name = qualify_local_agent_name(name, identity)
        artifact_dir = Path(claiming_dir).expanduser().resolve(strict=False)
        entries = dict(load_name_registry()["entries"])
        storage_name, existing = _equivalent_entry(entries, name, identity)
        if isinstance(existing, dict) and existing.get("container_kind"):
            _raise_container_name_collision(name, existing)
        if isinstance(existing, dict) and _entry_has_other_owner(
            existing, artifact_dir
        ):
            from sase.agent.names._common import NameCollisionError

            visible_name = strip_local_agent_name(name, identity)
            suggestion = lowest_name_suggestion(visible_name)
            raise NameCollisionError(
                f"agent name '{visible_name}' is already taken; try '{suggestion}'"
            )
        entry = _owner_from_artifact_name(
            artifact_dir, storage_name, reservation_kind="planned"
        )
        entries[storage_name] = entry
        _save_entries(entries)


def reserve_registered_clan_name(
    name: str,
    generation: str,
    claiming_dir: str | Path,
    *,
    create_only: bool = False,
) -> str:
    """Reserve a clan and return its allocation-locked generation.

    ``create_only`` makes an existing clan a collision. The check and new
    reservation happen under the same allocation lock so concurrent clan
    declarations cannot both succeed.
    """
    with _registry_mutation_lock():
        identity = MachineHoodIdentity.current()
        name = qualify_local_agent_name(name, identity)
        artifact_dir = Path(claiming_dir).expanduser().resolve(strict=False)
        entries = dict(load_name_registry()["entries"])
        storage_name, existing = _equivalent_entry(entries, name, identity)
        if isinstance(existing, dict):
            if existing.get("container_kind") == "clan":
                if create_only:
                    from sase.agent.names._common import NameCollisionError

                    visible_name = strip_local_agent_name(name, identity)
                    raise NameCollisionError(
                        f"clan '{visible_name}' already exists; join it with "
                        f"%id(<id>, clan={visible_name})"
                    )
                existing_generation = existing.get("clan_generation")
                return (
                    existing_generation
                    if isinstance(existing_generation, str) and existing_generation
                    else generation
                )
            from sase.agent.names._common import NameCollisionError

            visible_name = strip_local_agent_name(name, identity)
            raise NameCollisionError(
                f"clan name '{visible_name}' is already reserved by an agent; "
                "choose a different clan name"
            )
        entry = _owner_from_artifact_name(
            artifact_dir,
            storage_name,
            reservation_kind="planned_clan",
        )
        entry["container_kind"] = "clan"
        entry["clan_generation"] = generation
        entries[storage_name] = entry
        _save_entries(entries)
        return generation


def claim_registered_clan_name(
    name: str,
    generation: str,
    claiming_dir: str | Path,
) -> None:
    """Persist a clan container after one of its members publishes metadata."""
    with _registry_mutation_lock():
        identity = MachineHoodIdentity.current()
        name = qualify_local_agent_name(name, identity)
        artifact_dir = Path(claiming_dir).expanduser().resolve(strict=False)
        entries = dict(load_name_registry()["entries"])
        storage_name, existing = _equivalent_entry(entries, name, identity)
        if isinstance(existing, dict):
            if existing.get("container_kind") != "clan":
                from sase.agent.names._common import NameCollisionError

                visible_name = strip_local_agent_name(name, identity)
                raise NameCollisionError(
                    f"clan name '{visible_name}' is already reserved by an agent; "
                    "choose a different clan name"
                )
            if existing.get(
                "reservation_kind"
            ) != "planned_clan" and not _entry_belongs_to_artifact(
                existing, artifact_dir
            ):
                return
        entry = _owner_from_artifact_name(
            artifact_dir,
            storage_name,
            reservation_kind="clan",
        )
        entry["container_kind"] = "clan"
        entry["clan_generation"] = generation
        entries[storage_name] = entry
        _save_entries(entries)


def convert_registered_agent_to_family(
    name: str,
    member_name: str,
    claiming_dir: str | Path,
) -> None:
    """Convert one agent claim into a family container plus member claim."""
    with _registry_mutation_lock():
        identity = MachineHoodIdentity.current()
        name = qualify_local_agent_name(name, identity)
        member_name = qualify_local_agent_name(member_name, identity)
        artifact_dir = Path(claiming_dir).expanduser().resolve(strict=False)
        entries = dict(load_name_registry()["entries"])
        family_storage_name, existing = _equivalent_entry(entries, name, identity)
        if isinstance(existing, dict):
            container_kind = existing.get("container_kind")
            if container_kind == "clan":
                _raise_container_name_collision(name, existing)
            if container_kind not in {None, "family"}:
                _raise_container_name_collision(name, existing)
            if container_kind is None and _entry_has_other_owner(
                existing, artifact_dir
            ):
                _raise_name_collision(name)

        member_storage_name, member_existing = _equivalent_entry(
            entries, member_name, identity
        )
        if isinstance(member_existing, dict) and _entry_has_other_owner(
            member_existing, artifact_dir
        ):
            _raise_name_collision(member_name)

        family_entry = _owner_from_artifact_name(
            artifact_dir,
            family_storage_name,
            reservation_kind="family",
        )
        family_entry["container_kind"] = "family"
        entries[family_storage_name] = family_entry
        entries[member_storage_name] = _owner_from_artifact_name(
            artifact_dir,
            member_storage_name,
            reservation_kind="claimed",
        )
        _save_entries(entries)


def release_planned_registered_clan_name(
    name: str,
    generation: str,
    claiming_dir: str | Path,
) -> None:
    """Release a clan reservation when no member in its batch spawned."""
    with _registry_mutation_lock():
        identity = MachineHoodIdentity.current()
        name = qualify_local_agent_name(name, identity)
        artifact_dir = Path(claiming_dir).expanduser().resolve(strict=False)
        entries = dict(load_name_registry()["entries"])
        storage_name, existing = _equivalent_entry(entries, name, identity)
        if not isinstance(existing, dict):
            return
        if existing.get("reservation_kind") != "planned_clan":
            return
        if existing.get("clan_generation") != generation:
            return
        if not _entry_belongs_to_artifact(existing, artifact_dir):
            return
        entries.pop(storage_name, None)
        _save_entries(entries)


def reserve_registered_template_name(
    name: str,
    namespace: str,
    claiming_dir: str | Path,
    *,
    allowed_existing_names: Collection[str] = (),
) -> None:
    """Reserve a template-allocated *name* after checking *namespace*."""
    reserve_registered_template_names(
        [(name, namespace, claiming_dir)],
        allowed_existing_names=allowed_existing_names,
    )


def reserve_registered_template_names(
    reservations: Sequence[tuple[str, str, str | Path]],
    *,
    allowed_existing_names: Collection[str] = (),
) -> None:
    """Reserve template-allocated names atomically with namespace checks.

    Names in the same batch may share a namespace, but an existing registry
    entry blocks a namespace when it is exactly that namespace or a dotted
    descendant of it. ``allowed_existing_names`` lets one parent-side template
    group add later siblings beneath namespaces it already reserved.
    """
    if not reservations:
        return

    identity = MachineHoodIdentity.current()
    materialized_reservations = [
        (
            qualify_local_agent_name(name, identity),
            qualify_local_agent_name(namespace, identity),
            claiming_dir,
        )
        for name, namespace, claiming_dir in reservations
    ]
    names = [name for name, _, _ in materialized_reservations]
    name_keys = [canonical_local_agent_name_key(name, identity) for name in names]
    if len(set(name_keys)) != len(name_keys):
        from sase.agent.names._common import NameCollisionError

        raise NameCollisionError(
            "template allocation group rendered duplicate concrete names"
        )

    allowed = {
        canonical_local_agent_name_key(name, identity)
        for name in allowed_existing_names
    }
    with _registry_mutation_lock():
        entries = dict(load_name_registry()["entries"])
        # Build the occupied-namespace set once from the existing entries so each
        # reservation is a set-membership check instead of a full scan. A batch
        # is checked against the pre-batch entries, so same-batch siblings may
        # still share a namespace.
        occupied_namespaces = {
            prefix
            for existing_name, existing_entry in entries.items()
            if not (
                isinstance(existing_entry, dict)
                and existing_entry.get("container_kind") == "clan"
            )
            if canonical_local_agent_name_key(existing_name, identity) not in allowed
            for prefix in _dotted_namespace_prefixes(
                canonical_local_agent_name_key(existing_name, identity)
            )
        }
        materialized = [
            (
                name,
                namespace,
                Path(claiming_dir).expanduser().resolve(strict=False),
            )
            for name, namespace, claiming_dir in materialized_reservations
        ]
        for name, namespace, artifact_dir in materialized:
            _storage_name, existing = _equivalent_entry(entries, name, identity)
            if isinstance(existing, dict) and _entry_has_other_owner(
                existing, artifact_dir
            ):
                _raise_name_collision(name)
            if (
                canonical_local_agent_name_key(namespace, identity)
                in occupied_namespaces
            ):
                _raise_name_collision(name)

        for name, namespace, artifact_dir in materialized:
            storage_name, _existing = _equivalent_entry(entries, name, identity)
            entry = _owner_from_artifact_name(
                artifact_dir,
                storage_name,
                reservation_kind="planned",
                template_namespace=namespace,
            )
            entries[storage_name] = entry
        _save_entries(entries)


def release_planned_registered_name(name: str, claiming_dir: str | Path) -> None:
    """Remove a still-planned reservation for *name* owned by *claiming_dir*."""
    with _registry_mutation_lock():
        identity = MachineHoodIdentity.current()
        name = qualify_local_agent_name(name, identity)
        artifact_dir = Path(claiming_dir).expanduser().resolve(strict=False)
        entries = dict(load_name_registry()["entries"])
        storage_name, existing = _equivalent_entry(entries, name, identity)
        if not isinstance(existing, dict):
            return
        if existing.get("reservation_kind") != "planned":
            return
        if not _entry_belongs_to_artifact(existing, artifact_dir):
            return
        entries.pop(storage_name, None)
        _save_entries(entries)


def delete_registered_name(name: str) -> None:
    """Remove *name* from the registry."""
    with _registry_mutation_lock():
        identity = MachineHoodIdentity.current()
        entries = load_name_registry()["entries"]
        candidates = local_agent_name_lookup_candidates(name, identity)
        if not any(candidate in entries for candidate in candidates):
            return
        entries = dict(entries)
        for candidate in candidates:
            entries.pop(candidate, None)
        _save_entries(entries)


def _equivalent_entry(
    entries: Mapping[str, Any],
    durable_name: str,
    identity: MachineHoodIdentity,
) -> tuple[str, dict[str, Any] | None]:
    """Return the exact-first stored key and owner for a local identity."""
    for candidate in local_agent_name_lookup_candidates(durable_name, identity):
        entry = entries.get(candidate)
        if isinstance(entry, dict):
            return candidate, entry
    return durable_name, None


def _raise_name_collision(name: str) -> None:
    from sase.agent.names._common import NameCollisionError

    visible_name = strip_local_agent_name(name)
    suggestion = lowest_name_suggestion(visible_name)
    raise NameCollisionError(
        f"agent name '{visible_name}' is already taken; try '{suggestion}'"
    )


def _raise_container_name_collision(name: str, entry: dict[str, Any]) -> None:
    from sase.agent.names._common import NameCollisionError

    name = strip_local_agent_name(name)
    if entry.get("container_kind") == "clan":
        raise NameCollisionError(
            f"agent name '{name}' is reserved for clan '{name}'; "
            f"choose a name inside the clan hood, such as '{name}.member'"
        )
    raise NameCollisionError(
        f"agent name '{name}' is reserved for agent family '{name}'; "
        "attach a member with %i(suffix, family=parent) instead"
    )


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
        _collect_planned_reservation_entries(entries, _read_registry(_registry_path()))
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
    return source_signature_paths()


def _file_signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return (stat.st_mtime_ns, stat.st_size)
