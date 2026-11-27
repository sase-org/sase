"""Session-reservation owner enumeration for forced reuse.

Builds the wipe target set from the same derivation the registry rebuild uses,
so an index view that omits the root (or an older generation, or a
bundle-only owner) cannot leave a residual reservation behind.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def _session_owner_wipe_targets(
    session_names: Sequence[str],
    *,
    catalog: Any | None = None,
    identity: Any | None = None,
) -> list[dict[str, Any]]:
    """Return wipe mappings for every artifact/bundle deriving these sessions.

    Each mapping matches the shape ``wipe_agent_names_for_reuse`` accepts:
    ``name`` (concrete owner, falling back to the session name), plus
    ``artifacts_dir`` and/or ``bundle_path`` and ``raw_suffix``, with no
    ``container_kind`` so the owner is wiped rather than skipped.
    """

    from sase.agent.names._wipe_scan import load_wipe_catalog
    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        current_owner_agent_name_lookup_candidates,
    )

    materialized = tuple(dict.fromkeys(name for name in session_names if name))
    if not materialized:
        return []

    resolved_identity = (
        identity if identity is not None else AgentIdentitySnapshot.current()
    )
    active_catalog = (
        catalog if catalog is not None else load_wipe_catalog(resolved_identity)
    )

    candidates_by_session: dict[str, set[str]] = {}
    for session_name in materialized:
        candidates_by_session[session_name] = set(
            current_owner_agent_name_lookup_candidates(session_name, resolved_identity)
        )

    targets: list[dict[str, Any]] = []
    seen_keys: set[tuple[str | None, str | None]] = set()

    for record in active_catalog.artifacts:
        if not record.sessions:
            continue
        matched = _matching_session(record.sessions, candidates_by_session)
        if matched is None:
            continue
        concrete = sorted(record.names)[0] if record.names else matched
        artifact_dir = str(record.path)
        artifact_key_pair: tuple[str | None, str | None] = (
            _resolve_key(artifact_dir),
            None,
        )
        if artifact_key_pair in seen_keys:
            continue
        seen_keys.add(artifact_key_pair)
        targets.append(
            {
                "name": concrete,
                "artifacts_dir": artifact_dir,
                "raw_suffix": record.suffix,
            }
        )

    for record in active_catalog.bundles:
        if not record.sessions:
            continue
        matched_bundle = _matching_session(record.sessions, candidates_by_session)
        if matched_bundle is None:
            continue
        concrete_bundle = sorted(record.names)[0] if record.names else matched_bundle
        bundle_path = str(record.path)
        raw_suffix = record.raw_suffix or Path(bundle_path).stem
        artifact_key = (
            _resolve_key(record.artifacts_dir) if record.artifacts_dir else None
        )
        bundle_key_pair: tuple[str | None, str | None] = (
            artifact_key,
            _resolve_key(bundle_path),
        )
        if bundle_key_pair in seen_keys:
            continue
        seen_keys.add(bundle_key_pair)
        target: dict[str, Any] = {
            "name": concrete_bundle,
            "bundle_path": bundle_path,
            "raw_suffix": raw_suffix,
        }
        if record.artifacts_dir:
            target["artifacts_dir"] = record.artifacts_dir
        targets.append(target)

    return targets


def _matching_session(
    record_sessions: set[str],
    candidates_by_session: Mapping[str, set[str]],
) -> str | None:
    for session_name, candidates in candidates_by_session.items():
        if record_sessions & candidates:
            return session_name
    return None


def _resolve_key(value: str) -> str:
    try:
        return str(Path(value).expanduser().resolve(strict=False))
    except (OSError, RuntimeError, ValueError):
        return value


def resolve_scan_identity(identity: Any | None) -> Any:
    """Return the identity used for session localization in wipe scans."""
    if identity is not None:
        return identity
    from sase.core.agent_identity_facade import AgentIdentitySnapshot

    return AgentIdentitySnapshot.current()


def localized_session_for_scan(
    raw_session: str | None,
    payload: Mapping[str, Any] | None,
    identity: Any,
) -> set[str]:
    """Localize one raw session value exactly like the wipe scan does."""
    if not raw_session:
        return set()
    from sase.agent.names._registry_scan_entries import localize_payload_name

    localized = localize_payload_name(raw_session, dict(payload or {}), identity)
    return {localized} if localized else set()


def _resolve_path_key(value: str) -> str:
    from pathlib import Path as _Path

    try:
        return str(_Path(value).expanduser().resolve(strict=False))
    except (OSError, RuntimeError, ValueError):
        return value


def _target_path_key(target: Any) -> tuple[str | None, str | None]:
    if not isinstance(target, dict):
        return (None, None)
    artifacts_dir = target.get("artifacts_dir")
    bundle_path = target.get("bundle_path")
    artifact_key = (
        _resolve_path_key(artifacts_dir)
        if isinstance(artifacts_dir, str) and artifacts_dir
        else None
    )
    bundle_key = (
        _resolve_path_key(bundle_path)
        if isinstance(bundle_path, str) and bundle_path
        else None
    )
    if artifact_key is None and bundle_key is None:
        name = target.get("name")
        fallback = name if isinstance(name, str) and name else ""
        return (fallback or None, None)
    return (artifact_key, bundle_key)


def _owner_path_key(owner: Any, *, fallback_name: str) -> tuple[str | None, str | None]:
    if not isinstance(owner, dict):
        return (fallback_name, None)
    artifacts_dir = owner.get("artifacts_dir")
    bundle_path = owner.get("bundle_path")
    artifact_key = (
        _resolve_path_key(artifacts_dir)
        if isinstance(artifacts_dir, str) and artifacts_dir
        else None
    )
    bundle_key = (
        _resolve_path_key(bundle_path)
        if isinstance(bundle_path, str) and bundle_path
        else None
    )
    if artifact_key is None and bundle_key is None:
        return (fallback_name, None)
    return (artifact_key, bundle_key)


def describe_residual_owner(name: str, entry: Any) -> str:
    if not isinstance(entry, dict):
        return name
    parts = [name]
    source = entry.get("source")
    if isinstance(source, str) and source:
        parts.append(f"source={source}")
    artifacts_dir = entry.get("artifacts_dir")
    if isinstance(artifacts_dir, str) and artifacts_dir:
        parts.append(f"artifacts_dir={artifacts_dir}")
    bundle_path = entry.get("bundle_path")
    if isinstance(bundle_path, str) and bundle_path:
        parts.append(f"bundle_path={bundle_path}")
    collision_owners = entry.get("collision_owners")
    count = len(collision_owners) if isinstance(collision_owners, list) else 0
    parts.append(f"collision_owners={count}")
    return f"{name} ({', '.join(parts[1:])})"


def _agent_session_for_member(
    members_by_agent_session: dict[str, tuple[str, ...]],
    member_name: str,
) -> str:
    for agent_session_name, member_names in members_by_agent_session.items():
        if member_name in member_names:
            return agent_session_name
    return "unknown"


def _dedupe_session_names(names: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(name for name in names if name))


def wipe_agent_sessions_for_forced_reuse(
    names: Sequence[str], *, retry_residual: bool = True
) -> None:
    """Resolve and wipe every owner of several agent-session reservations.

    Lazily-loaded implementation behind
    ``sase.agent.names._forced_reuse._wipe_agent_sessions_for_forced_reuse`` so
    the TUI startup closure does not pay for this session-only path.
    *retry_residual* re-runs this wipe once for names still reserved after
    rebuild so a late catalog writer is absorbed; the recursive call passes
    ``False``.
    """
    from sase.agent.names import find_agent_session, load_name_registry
    from sase.agent.names._registry_entries import AGENT_SESSION_CONTAINER_KIND
    from sase.agent.names._wipe_scan import load_wipe_catalog
    from sase.core.agent_identity_facade import AgentIdentitySnapshot

    from sase.agent.names._forced_reuse import (
        ForcedReuseCleanupError,
        release_stale_containers,
    )

    materialized = _dedupe_session_names(names)
    members_by_agent_session: dict[str, tuple[str, ...]] = {}
    stale_agent_sessions: list[str] = []
    for name in materialized:
        try:
            agent_session = find_agent_session(name)
        except Exception as exc:  # noqa: BLE001
            raise ForcedReuseCleanupError(
                f"forced reuse cleanup could not resolve agent session '{name}': {exc}"
            ) from exc
        member_names = tuple(
            sorted(
                {
                    member.name
                    for member in agent_session.members
                    if isinstance(member.name, str)
                    and member.name
                    and member.name != name
                }
                if agent_session is not None
                else set()
            )
        )
        members_by_agent_session[name] = member_names

    identity = AgentIdentitySnapshot.current()
    try:
        catalog = load_wipe_catalog(identity)
    except Exception as exc:  # noqa: BLE001
        raise ForcedReuseCleanupError(
            f"forced reuse cleanup could not scan session owners: {exc}"
        ) from exc
    try:
        owner_targets = _session_owner_wipe_targets(
            materialized, catalog=catalog, identity=identity
        )
    except Exception as exc:  # noqa: BLE001
        raise ForcedReuseCleanupError(
            f"forced reuse cleanup could not resolve session owners: {exc}"
        ) from exc

    targets_by_session: dict[str, list[Any]] = {name: [] for name in materialized}
    from sase.core.agent_identity_facade import (
        current_owner_agent_name_lookup_candidates as _candidates,
    )

    candidates_map = {
        session_name: set(_candidates(session_name, identity))
        for session_name in materialized
    }
    path_to_sessions: dict[str, set[str]] = {}
    for artifact_record in catalog.artifacts:
        catalog_key = str(artifact_record.path)
        path_to_sessions[catalog_key] = set(artifact_record.sessions)
    for bundle_record in catalog.bundles:
        catalog_key = str(bundle_record.path)
        path_to_sessions[catalog_key] = set(bundle_record.sessions)
    for target in owner_targets:
        if not isinstance(target, dict):
            continue
        target_paths: list[str] = []
        artifacts_dir = target.get("artifacts_dir")
        if isinstance(artifacts_dir, str) and artifacts_dir:
            target_paths.append(_resolve_path_key(artifacts_dir))
        bundle_path = target.get("bundle_path")
        if isinstance(bundle_path, str) and bundle_path:
            target_paths.append(_resolve_path_key(bundle_path))
        matched: str | None = None
        for session_name in materialized:
            wanted = candidates_map[session_name]
            for target_path in target_paths:
                for catalog_path, sessions in path_to_sessions.items():
                    if (
                        _resolve_path_key(catalog_path) == target_path
                        and sessions & wanted
                    ):
                        matched = session_name
                        break
                if matched is not None:
                    break
            if matched is not None:
                break
        if matched is None:
            matched = materialized[0]
        targets_by_session[matched].append(target)

    for name in materialized:
        if not members_by_agent_session.get(name) and not targets_by_session.get(name):
            stale_agent_sessions.append(name)

    if stale_agent_sessions:
        release_stale_containers(
            tuple((name, AGENT_SESSION_CONTAINER_KIND) for name in stale_agent_sessions)
        )
    active_sessions = [
        name for name in materialized if name not in stale_agent_sessions
    ]
    if not active_sessions:
        return

    from collections.abc import Mapping

    union_targets: list[str | Mapping[str, Any]] = []
    seen_path_keys: set[tuple[str | None, str | None]] = set()
    for session_name in active_sessions:
        for target in targets_by_session.get(session_name, []):
            if not isinstance(target, dict):
                continue
            target_key = _target_path_key(target)
            if target_key in seen_path_keys:
                continue
            seen_path_keys.add(target_key)
            union_targets.append(target)

    snapshot_owners: dict[str, Any] = {}
    try:
        from sase.agent.names import registered_name_reservation_snapshot

        snapshot = registered_name_reservation_snapshot()
        for session_name in active_sessions:
            for member_name in members_by_agent_session.get(session_name, ()):
                owner = snapshot.lookup(member_name)
                snapshot_owners[member_name] = owner
    except Exception:
        snapshot_owners = {}

    for session_name in active_sessions:
        for member_name in members_by_agent_session.get(session_name, ()):
            owner = snapshot_owners.get(member_name)
            owner_key = _owner_path_key(owner, fallback_name=member_name)
            if owner_key in seen_path_keys:
                continue
            seen_path_keys.add(owner_key)
            union_targets.append(member_name)

    if not union_targets:
        return

    try:
        results = wipe_names_for_reuse_batch(tuple(union_targets), catalog=catalog)
    except Exception as exc:  # noqa: BLE001
        raise ForcedReuseCleanupError(
            f"forced reuse cleanup for agent session members failed: {exc}"
        ) from exc

    errors: list[str] = []
    for result in results:
        member_name = result.target_name
        if result.errors:
            agent_session_name = _agent_session_for_member(
                members_by_agent_session, member_name
            )
            errors.append(
                f"agent session '{agent_session_name}' member '{member_name}' "
                "reported errors: " + "; ".join(result.errors)
            )
            continue
        if result.skipped_container_kind:
            agent_session_name = _agent_session_for_member(
                members_by_agent_session, member_name
            )
            errors.append(
                f"agent session '{agent_session_name}' member '{member_name}' resolved to a "
                f"{result.skipped_container_kind} container"
            )
    if errors:
        error_target_names: list[str] = []
        for union_target in union_targets:
            if isinstance(union_target, str):
                error_target_names.append(union_target)
            elif isinstance(union_target, dict):
                raw_name = union_target.get("name")
                if isinstance(raw_name, str) and raw_name:
                    error_target_names.append(raw_name)
        raise_forced_reuse_batch_errors(errors, tuple(error_target_names), results)

    try:
        registry = load_name_registry()
    except Exception as exc:  # noqa: BLE001
        raise ForcedReuseCleanupError(
            "forced reuse cleanup for agent sessions could not read the name "
            f"registry after rebuild: {exc}"
        ) from exc
    entries = registry.get("entries")
    if not isinstance(entries, dict):
        raise ForcedReuseCleanupError(
            "forced reuse cleanup for agent sessions received an "
            "invalid name registry after rebuild"
        )

    residual_errors: list[str] = []
    residual_session_names: list[str] = []
    for agent_session_name in active_sessions:
        member_names = members_by_agent_session.get(agent_session_name, ())
        residual_names = sorted({agent_session_name, *member_names} & set(entries))
        if residual_names:
            residual_session_names.append(agent_session_name)
            details = [
                describe_residual_owner(name, entries.get(name))
                for name in residual_names
            ]
            residual_errors.append(
                f"forced reuse cleanup left agent session '{agent_session_name}' "
                f"reservations after rebuild: {', '.join(details)}"
            )
    if residual_errors:
        if retry_residual:
            wipe_agent_sessions_for_forced_reuse(
                residual_session_names, retry_residual=False
            )
            return
        raise ForcedReuseCleanupError("; ".join(residual_errors))


def wipe_names_for_reuse_batch(
    names: Sequence[Any],
    *,
    allow_stale_container: bool = False,
    catalog: Any | None = None,
) -> tuple[Any, ...]:
    """Shared batch dispatch for forced-reuse wipes, including patched fakes."""
    from collections.abc import Mapping as _Mapping

    from sase.agent import names as names_mod
    from sase.agent.names import _wipe as wipe_module

    batch_helper = names_mod.wipe_agent_names_for_reuse
    single_helper = names_mod.wipe_agent_name_for_reuse
    if (
        single_helper is not wipe_module.wipe_agent_name_for_reuse
        and batch_helper is wipe_module.wipe_agent_names_for_reuse
    ):
        cleaned: list[Any] = [
            item
            for item in names
            if isinstance(item, str) or isinstance(item, _Mapping)
        ]
        if allow_stale_container:
            return tuple(
                single_helper(  # type: ignore[call-arg]
                    item, allow_stale_container=True
                )
                for item in cleaned
                if isinstance(item, str)
            )
        return tuple(
            single_helper(item)
            for item in cleaned
            if isinstance(item, str)  # type: ignore[call-arg]
        )
    return tuple(
        batch_helper(
            names, allow_stale_container=allow_stale_container, catalog=catalog
        )
    )


def raise_forced_reuse_batch_errors(
    errors: Sequence[str],
    names: Sequence[str],
    results: Sequence[Any],
) -> None:
    """Raise the shared batch error for forced-reuse cleanup failures."""
    from sase.agent.names._forced_reuse import ForcedReuseCleanupBatchError

    completed_names = tuple(
        result.target_name
        for result in results
        if not result.errors
        and not result.skipped_container_kind
        and (not result.found or result.target_name in result.registry_names_removed)
    )
    completed = set(completed_names)
    remaining_names = tuple(name for name in names if name not in completed)
    detail = "; ".join(errors)
    if completed_names:
        detail += "; completed cleanup for " + ", ".join(completed_names)
    if remaining_names:
        detail += "; remaining cleanup targets: " + ", ".join(remaining_names)
    raise ForcedReuseCleanupBatchError(
        "forced reuse cleanup batch failed: " + detail,
        completed_names=completed_names,
        remaining_names=remaining_names,
    )
