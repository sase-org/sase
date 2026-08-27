"""Persistent reservation index for permanent agent names.

Registry rebuilds scan artifacts across every project lifecycle state so
archiving or closing a project does not free names that still belong to stored
agent history.
"""

from __future__ import annotations

from collections.abc import Collection, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
import os
from pathlib import Path
import time
from typing import Any, NoReturn

from sase.agent.names import _registry_mutations, _registry_queries
from sase.agent.names._registry_entries import (
    dotted_namespace_prefixes as _dotted_namespace_prefixes,
    entry_belongs_to_artifact as _entry_belongs_to_artifact,
    entry_has_other_claim_owner as _entry_has_other_claim_owner,
    entry_has_other_owner as _entry_has_other_owner,
    owner_from_artifact_name as _owner_from_artifact_name,
)
from sase.agent.names._registry_mutations import (
    ImportedV2RegistryClaim,
    RegistryMutationOperations,
)
from sase.agent.names.registry_freshness import (
    agent_name_registry_freshness_token,
    invalidate_agent_name_registry_freshness,
)
from sase.agent.names._registry_scan import (
    collect_artifact_entries as _collect_artifact_entries,
    collect_dismissed_bundle_entries as _collect_dismissed_bundle_entries,
    collect_owner_namespace_entries as _collect_owner_namespace_entries,
    collect_planned_reservation_entries as _collect_planned_reservation_entries,
    reset_registry_scan_caches as _reset_registry_scan_caches,
)
from sase.agent.names._registry_store import (
    INDEX_FILENAME,
    SCHEMA_VERSION,
    file_signature as _store_file_signature,
    read_registry as _store_read_registry,
    registry_data as _store_registry_data,
    registry_file_is_stale as _store_registry_file_is_stale,
    registry_path as _store_registry_path,
    source_signature_load_session as _store_source_signature_load_session,
    write_registry as _store_write_registry,
)
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
    LegacyV1GroupOwnershipClassification,
    current_owner_agent_name_lookup_candidates,
    present_agent_name,
)

_CACHE_PATH: Path | None = None
_CACHE_SIGNATURE: tuple[int, int] | None = None
_CACHE_DATA: dict[str, Any] | None = None
_LOAD_SESSION_ACTIVE: ContextVar[bool] = ContextVar(
    "agent_name_registry_load_session_active",
    default=False,
)

# A cache hit's own file signature is cheap to check; the expensive part is
# proving the artifact/dismissed-bundle sources it was built from have not
# moved (``_registry_file_is_stale``). Memoize a "proved not stale" result
# against the in-process freshness generation plus a short TTL, so a burst of
# loads inside one paint or launch flow pays that proof at most once. Any
# registry mutation bumps the generation (via
# ``invalidate_agent_name_registry_freshness``), which invalidates the memo
# immediately regardless of the TTL.
#
# What the memo trades away is visibility of artifact directories that appear
# or vanish without a registry write -- another process's launch, a manual
# wipe -- for up to one TTL. Reads that only display registry state can absorb
# that; reads that decide whether a name is free cannot, because a stale
# "free" answer hands out a name someone else already owns. Reservation reads
# therefore go through ``_load_registry_for_reservations`` and skip the memo.
_STALE_PROOF_TTL_SECONDS = 2.0
_STALE_PROOF_GENERATION: int | None = None
_STALE_PROOF_MONOTONIC: float | None = None


def _registry_path() -> Path:
    """Return the durable agent-name registry path."""
    return _store_registry_path()


def lookup_registered_name(name: str) -> dict[str, Any] | None:
    """Return registry owner metadata for *name*, if reserved."""
    return _registry_queries.lookup_registered_name(
        name, load_registry=_load_registry_for_reservations
    )


def is_name_reserved(name: str) -> bool:
    """Return whether *name* is reserved by an existing agent."""
    return _registry_queries.is_name_reserved(
        name, load_registry=_load_registry_for_reservations
    )


def get_reserved_agent_names() -> set[str]:
    """Return every name currently reserved by the registry."""
    return _registry_queries.get_reserved_agent_names(
        load_registry=_load_registry_for_reservations
    )


def get_reserved_clan_names() -> set[str]:
    """Return every name owned by a clan container."""
    return _registry_queries.get_reserved_clan_names(
        load_registry=_load_registry_for_reservations
    )


def get_reserved_family_names() -> set[str]:
    """Return every name owned by a sequential family container."""
    return _registry_queries.get_reserved_family_names(
        load_registry=_load_registry_for_reservations
    )


def get_reserved_family_names_for_display() -> set[str]:
    """Return family-container names for a render, never forcing a rebuild.

    Link rendering only needs to know which names are family containers so it
    can shape a URL. Unlike :func:`get_reserved_family_names`, which gates
    allocation and must pay the full staleness proof, this read tolerates a
    stale answer rather than take the name-allocation lock.
    """
    return _registry_queries.get_reserved_family_names(
        load_registry=_load_registry_for_display
    )


def get_reserved_agent_name_map() -> dict[str, str]:
    """Return ``{name: owner_path}`` for registered names with a known owner path."""
    return _registry_queries.get_reserved_agent_name_map(
        load_registry=_load_registry_for_reservations
    )


def lowest_name_suggestion(base: str) -> str:
    """Return the lowest available ``<base><N>`` suggestion."""
    return _registry_queries.lowest_name_suggestion(
        base, load_registry=_load_registry_for_reservations
    )


def claim_registered_name(
    name: str, claiming_dir: str | Path, *, replace_existing: bool = False
) -> None:
    """Best-effort upsert of a claimed name into the registry."""
    _registry_mutations.claim_registered_name(
        _mutation_operations(),
        name,
        claiming_dir,
        replace_existing=replace_existing,
    )


def claim_imported_registered_name(
    name: str,
    source_machine: str,
    claiming_dir: str | Path,
    *,
    digest: str,
    target_owner: AgentOwnerIdentity | None = None,
    group_ownership: LegacyV1GroupOwnershipClassification = (
        LegacyV1GroupOwnershipClassification.FOREIGN
    ),
) -> None:
    """Claim an exact foreign machine-qualified imported agent name.

    Imported names deliberately bypass local qualification: a previously
    unknown hood such as ``zeus.worker`` must remain exactly that spelling,
    rather than becoming ``<local>.zeus.worker``. The source machine must
    match the durable prefix, and only the same imported owner may refresh its
    digest.
    """

    _registry_mutations.claim_imported_registered_name(
        _mutation_operations(),
        name,
        source_machine,
        claiming_dir,
        digest=digest,
        target_owner=target_owner,
        group_ownership=group_ownership,
    )


def claim_imported_registered_name_v2(
    source_owner: AgentOwnerIdentity,
    canonical_global_name: str,
    localized_name: str,
    claiming_dir: str | Path,
    *,
    digest: str,
) -> None:
    """Claim an imported name with explicit v2 owner provenance."""
    _registry_mutations.claim_imported_registered_name_v2(
        _mutation_operations(),
        source_owner,
        canonical_global_name,
        localized_name,
        claiming_dir,
        digest=digest,
    )


def preflight_imported_registered_names_v2(
    claims: Sequence[ImportedV2RegistryClaim],
    *,
    identity: AgentIdentitySnapshot | None = None,
) -> None:
    """Validate an entire imported v2 claim batch without registry writes."""

    _registry_mutations.preflight_imported_registered_names_v2(
        _mutation_operations(),
        claims,
        identity=identity,
    )


def claim_imported_registered_names_v2(
    claims: Sequence[ImportedV2RegistryClaim],
    *,
    identity: AgentIdentitySnapshot | None = None,
) -> None:
    """Persist an entire imported v2 run/container claim batch atomically."""

    _registry_mutations.claim_imported_registered_names_v2(
        _mutation_operations(),
        claims,
        identity=identity,
    )


def reserve_registered_name(name: str, claiming_dir: str | Path) -> None:
    """Reserve *name* for a not-yet-started agent artifacts directory.

    Planned launch reservations are intentionally collision-checked like
    explicit claims, but they use ``reservation_kind="planned"`` so callers can
    roll them back if the child process never starts. The child runner's later
    regular claim is idempotent because it uses the same artifacts owner.
    """
    _registry_mutations.reserve_registered_name(
        _mutation_operations(), name, claiming_dir
    )


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
    return _registry_mutations.reserve_registered_clan_name(
        _mutation_operations(),
        name,
        generation,
        claiming_dir,
        create_only=create_only,
    )


def claim_registered_clan_name(
    name: str,
    generation: str,
    claiming_dir: str | Path,
) -> None:
    """Persist a clan container after one of its members publishes metadata."""
    _registry_mutations.claim_registered_clan_name(
        _mutation_operations(), name, generation, claiming_dir
    )


def convert_registered_agent_to_family(
    name: str,
    member_name: str,
    claiming_dir: str | Path,
) -> None:
    """Convert one agent claim into a family container plus member claim."""
    _registry_mutations.convert_registered_agent_to_family(
        _mutation_operations(), name, member_name, claiming_dir
    )


def release_planned_registered_clan_name(
    name: str,
    generation: str,
    claiming_dir: str | Path,
) -> None:
    """Release a clan reservation when no member in its batch spawned."""
    _registry_mutations.release_planned_registered_clan_name(
        _mutation_operations(), name, generation, claiming_dir
    )


def reserve_registered_template_name(
    name: str,
    namespace: str,
    claiming_dir: str | Path,
    *,
    allowed_existing_names: Collection[str] = (),
) -> None:
    """Reserve a template-allocated *name* after checking *namespace*."""
    _registry_mutations.reserve_registered_template_name(
        _mutation_operations(),
        name,
        namespace,
        claiming_dir,
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
    _registry_mutations.reserve_registered_template_names(
        _mutation_operations(),
        reservations,
        allowed_existing_names=allowed_existing_names,
    )


def release_planned_registered_name(name: str, claiming_dir: str | Path) -> None:
    """Remove a still-planned reservation for *name* owned by *claiming_dir*."""
    _registry_mutations.release_planned_registered_name(
        _mutation_operations(), name, claiming_dir
    )


def delete_registered_name(name: str) -> None:
    """Remove *name* from the registry."""
    _registry_mutations.delete_registered_name(_mutation_operations(), name)


def _mutation_operations() -> RegistryMutationOperations:
    """Bind mutation dependencies through this compatibility facade."""
    return RegistryMutationOperations(
        lock=_registry_mutation_lock,
        load=load_name_registry,
        save_entries=_save_entries,
        owner_from_artifact_name=_owner_from_artifact_name,
        entry_belongs_to_artifact=_entry_belongs_to_artifact,
        entry_has_other_owner=_entry_has_other_owner,
        entry_has_other_claim_owner=_entry_has_other_claim_owner,
        dotted_namespace_prefixes=_dotted_namespace_prefixes,
        equivalent_entry=_equivalent_entry,
        raise_name_collision=_raise_name_collision,
        raise_container_name_collision=_raise_container_name_collision,
        lowest_name_suggestion=lowest_name_suggestion,
    )


def _equivalent_entry(
    entries: Mapping[str, Any],
    durable_name: str,
    identity: AgentIdentitySnapshot,
) -> tuple[str, dict[str, Any] | None]:
    """Return the exact-first stored key and owner for a local identity."""
    for candidate in current_owner_agent_name_lookup_candidates(durable_name, identity):
        entry = entries.get(candidate)
        if isinstance(entry, dict):
            return candidate, entry
    return durable_name, None


def _raise_name_collision(name: str) -> NoReturn:
    from sase.agent.names._common import NameCollisionError

    visible_name = present_agent_name(name)
    suggestion = lowest_name_suggestion(visible_name)
    raise NameCollisionError(
        f"agent name '{visible_name}' is already taken; try '{suggestion}'"
    )


def _raise_container_name_collision(name: str, entry: dict[str, Any]) -> NoReturn:
    from sase.agent.names._common import NameCollisionError

    name = present_agent_name(name)
    if entry.get("container_kind") == "clan":
        raise NameCollisionError(
            f"agent name '{name}' is reserved for clan '{name}'; "
            f"choose a name inside the clan hood, such as '{name}.member'"
        )
    if entry.get("container_kind") == "owner_namespace":
        raise NameCollisionError(
            f"agent name '{name}' is reserved as a foreign owner namespace"
        )
    raise NameCollisionError(
        f"agent name '{name}' is reserved for agent family '{name}'; "
        "attach a member with %i(suffix, family=parent) instead"
    )


def load_name_registry(*, trust_stale_proof_memo: bool = True) -> dict[str, Any]:
    """Load the name registry, rebuilding once when absent or stale.

    Pass ``trust_stale_proof_memo=False`` to force the full staleness proof
    even when a recent one is memoized; see ``_load_registry_for_reservations``.
    """
    path = _registry_path()
    cached = _cached_registry(path, trust_stale_proof_memo=trust_stale_proof_memo)
    if cached is not None:
        return cached

    data = _read_registry(path)
    if data is None or _registry_file_is_stale(data):
        return rebuild_name_registry()

    _set_cache(path, data)
    _record_stale_proof_memo()
    return data


@contextmanager
def name_registry_load_session() -> Iterator[None]:
    """Reuse one validated registry snapshot during a bounded import loop."""

    with _store_source_signature_load_session():
        token = _LOAD_SESSION_ACTIVE.set(True)
        try:
            yield
        finally:
            _LOAD_SESSION_ACTIVE.reset(token)


def rebuild_name_registry() -> dict[str, Any]:
    """Rebuild the registry by scanning existing artifacts and dismissed bundles."""
    with _registry_mutation_lock():
        entries: dict[str, dict[str, Any]] = {}
        identity = AgentIdentitySnapshot.current()
        _collect_planned_reservation_entries(
            entries,
            _read_registry(_registry_path()),
            identity,
        )
        _collect_artifact_entries(entries, identity)
        _collect_dismissed_bundle_entries(entries, identity)
        _collect_owner_namespace_entries(entries, identity)
        data = _registry_data(entries)
        _write_registry(_registry_path(), data)
        _set_cache(_registry_path(), data)
        invalidate_agent_name_registry_freshness()
        return data


def reset_name_registry_caches_for_tests() -> None:
    """Clear process-local registry state after tests switch ``SASE_HOME``."""
    global _CACHE_DATA, _CACHE_PATH, _CACHE_SIGNATURE
    _CACHE_PATH = None
    _CACHE_SIGNATURE = None
    _CACHE_DATA = None
    _clear_stale_proof_memo()
    _reset_registry_scan_caches()
    invalidate_agent_name_registry_freshness()
    from sase.config.core import clear_config_cache

    clear_config_cache()


def _registry_mutation_lock() -> AbstractContextManager[None]:
    from sase.agent.names._resume import agent_name_allocation_lock

    return agent_name_allocation_lock()


def _cached_registry(
    path: Path, *, trust_stale_proof_memo: bool = True
) -> dict[str, Any] | None:
    if _CACHE_PATH != path or _CACHE_DATA is None:
        return None
    try:
        signature = _file_signature(path)
    except OSError:
        return None
    if signature != _CACHE_SIGNATURE:
        return None
    if _LOAD_SESSION_ACTIVE.get():
        return _CACHE_DATA
    if trust_stale_proof_memo and _stale_proof_memo_valid():
        return _CACHE_DATA
    if _registry_file_is_stale(_CACHE_DATA):
        return None
    _record_stale_proof_memo()
    return _CACHE_DATA


def _load_registry_for_reservations() -> dict[str, Any]:
    """Load the registry for an answer that gates name allocation.

    Name reservation answers must observe an artifact directory that appeared
    or vanished since the last staleness proof, so they pay the full proof
    instead of reusing the memo a display read would accept.
    """
    _reset_registry_scan_caches()
    return load_name_registry(trust_stale_proof_memo=False)


def _load_registry_for_display() -> dict[str, Any]:
    """Load the registry for a render that must never gate a launch.

    A rebuild holds the process-wide name-allocation flock for as long as a
    full artifact scan takes, so a render that rebuilds stalls every
    concurrent ``sase run`` behind it. A render only labels names it is
    already showing, where a momentarily stale answer costs a stale label
    rather than a double-allocated name, so staleness alone does not earn a
    rebuild here: the registry file is reused exactly as written. Only a
    missing or unreadable registry falls through to a rebuild, because then
    there is nothing to render at all.
    """
    path = _registry_path()
    # Renders run on several TUI workers at once, so read each half of the
    # cache into a local before comparing them: a concurrent ``_set_cache``
    # must not be observed half-applied.
    cached_data = _CACHE_DATA
    cached_signature = _CACHE_SIGNATURE
    if cached_data is not None and _CACHE_PATH == path:
        try:
            if _file_signature(path) == cached_signature:
                return cached_data
        except OSError:
            pass
    data = _read_registry(path)
    if data is None:
        return rebuild_name_registry()
    _set_cache(path, data)
    return data


def _stale_proof_memo_valid() -> bool:
    """Return whether the last full staleness proof is still trustworthy."""
    if _STALE_PROOF_GENERATION is None or _STALE_PROOF_MONOTONIC is None:
        return False
    if _STALE_PROOF_GENERATION != agent_name_registry_freshness_token():
        return False
    return (time.monotonic() - _STALE_PROOF_MONOTONIC) < _STALE_PROOF_TTL_SECONDS


def _record_stale_proof_memo() -> None:
    global _STALE_PROOF_GENERATION, _STALE_PROOF_MONOTONIC
    _STALE_PROOF_GENERATION = agent_name_registry_freshness_token()
    _STALE_PROOF_MONOTONIC = time.monotonic()


def _clear_stale_proof_memo() -> None:
    global _STALE_PROOF_GENERATION, _STALE_PROOF_MONOTONIC
    _STALE_PROOF_GENERATION = None
    _STALE_PROOF_MONOTONIC = None


def _set_cache(path: Path, data: dict[str, Any]) -> None:
    global _CACHE_DATA, _CACHE_PATH, _CACHE_SIGNATURE
    _CACHE_PATH = path
    _CACHE_DATA = data
    try:
        _CACHE_SIGNATURE = _file_signature(path)
    except OSError:
        _CACHE_SIGNATURE = None


def _read_registry(path: Path) -> dict[str, Any] | None:
    return _store_read_registry(path)


def _write_registry(path: Path, data: dict[str, Any]) -> None:
    _store_write_registry(path, data, replace_file=os.replace)


def _save_entries(entries: dict[str, Any]) -> None:
    with _registry_mutation_lock():
        data = _registry_data(entries)
        path = _registry_path()
        _write_registry(path, data)
        _set_cache(path, data)
        invalidate_agent_name_registry_freshness()


def _registry_data(entries: dict[str, Any]) -> dict[str, Any]:
    return _store_registry_data(entries)


def _registry_file_is_stale(data: dict[str, Any]) -> bool:
    return _store_registry_file_is_stale(data)


def _file_signature(path: Path) -> tuple[int, int]:
    return _store_file_signature(path)
