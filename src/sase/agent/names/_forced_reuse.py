"""Shared forced-name-reuse cleanup for concrete owners, agent sessions, and clans.

Both the ACE/``sase agent restart`` launch boundary and deterministic bead
relaunch need the same policy: a concrete owner is wiped directly, an agent-session
container relaunch replaces every owner of the session reservation (the newest
generation found through the index plus any other owners found through the
registry's own derivation, wiped in one batch, then the registry is rebuilt
and checked for residual reservations), and a populated clan container is
refused unless the caller opts into the container-skip escape hatch. Keeping
one implementation here prevents bead and ACE forced-reuse behavior from
drifting apart again.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from sase.agent.names._registry_entries import is_agent_session_container_kind


class ForcedReuseCleanupError(RuntimeError):
    """Raised when forced-name-reuse cleanup cannot be completed."""


class ForcedReuseCleanupBatchError(ForcedReuseCleanupError):
    """Raised when a cleanup batch partially completes before failing."""

    def __init__(
        self,
        message: str,
        *,
        completed_names: Sequence[str] = (),
        remaining_names: Sequence[str] = (),
    ) -> None:
        self.completed_names = tuple(completed_names)
        self.remaining_names = tuple(remaining_names)
        super().__init__(message)


def wipe_force_reuse_owner(name: str, *, allow_container_skip: bool) -> None:
    """Wipe a single deterministic owner, raising on any cleanup failure.

    A concrete owner is wiped and verified gone. An agent-session container
    always resolves and replaces every owner of the session reservation: the
    newest generation found through the index plus any other owners found
    through the registry's own derivation. Relaunching an agent-session root
    means those concrete shells must be gone before the bare agent-session
    name is reused. A populated clan container is a rootless parallel group,
    not one replaceable agent, and is refused unless *allow_container_skip*
    allows the caller to skip past it (its members retain their own explicit
    relaunch path).
    """
    wipe_force_reuse_owners((name,), allow_container_skip=allow_container_skip)


def wipe_force_reuse_owners(
    names: Sequence[str],
    *,
    allow_container_skip: bool,
) -> None:
    """Wipe deterministic owners as one batch, preserving container policy."""
    materialized = _dedupe_names(names)
    if not materialized:
        return

    results = _wipe_batch_or_raise(materialized, materialized=materialized)
    residual = _residual_reuse_names(results)
    if residual:
        retry_results = _wipe_batch_or_raise(residual, materialized=materialized)
        results = _merge_wipe_results(results, retry_results)

    errors: list[str] = []
    agent_session_names: list[str] = []
    stale_clan_names: list[str] = []
    for result in results:
        name = result.target_name
        if result.errors:
            errors.append(
                f"agent name '{name}' reported errors: " + "; ".join(result.errors)
            )
            continue
        if is_agent_session_container_kind(result.skipped_container_kind):
            agent_session_names.append(name)
            continue
        if result.skipped_container_kind == "clan":
            if _clan_has_members(name):
                if allow_container_skip:
                    continue
                errors.append(
                    f"agent name '{name}' is reserved by a clan container and "
                    "cannot be force-reused; dismiss or clean up the "
                    "container's members, then retry"
                )
            else:
                stale_clan_names.append(name)
            continue
        if result.skipped_container_kind:
            errors.append(
                f"agent name '{name}' is reserved by a "
                f"{result.skipped_container_kind} container and cannot be "
                "force-reused; dismiss or clean up the container's members, "
                "then retry"
            )
            continue
        if result.found and name not in result.registry_names_removed:
            errors.append(_residual_owner_error(name))

    if errors:
        _raise_batch_errors(errors, materialized, results)

    if stale_clan_names:
        release_stale_containers(tuple((name, "clan") for name in stale_clan_names))
    if agent_session_names:
        _wipe_agent_sessions_for_forced_reuse(agent_session_names)


def _wipe_agent_sessions_for_forced_reuse(names: Sequence[str]) -> None:
    """Resolve and wipe every owner of several agent-session reservations."""
    from sase.agent.names._session_owners import (
        wipe_agent_sessions_for_forced_reuse as _session_impl,
    )

    return _session_impl(names)


def release_stale_container(
    name: str,
    *,
    container_kind: Literal["session", "clan"],
) -> None:
    """Remove an orphaned container's residual owner and verify its release."""
    release_stale_containers(((name, container_kind),))


def release_stale_containers(
    containers: Sequence[tuple[str, Literal["session", "clan"]]],
) -> None:
    """Remove orphaned container reservations as one cleanup batch."""
    materialized = tuple(
        (name, kind) for name, kind in containers if isinstance(name, str) and name
    )
    if not materialized:
        return

    names = tuple(name for name, _kind in materialized)
    try:
        results = _wipe_names_for_reuse_batch(names, allow_stale_container=True)
    except Exception as exc:  # noqa: BLE001
        raise ForcedReuseCleanupError(
            f"forced reuse cleanup for stale container reservations failed: {exc}"
        ) from exc

    errors: list[str] = []
    kind_by_name = dict(materialized)
    for result in results:
        name = result.target_name
        container_kind = kind_by_name.get(name, "container")
        if result.errors:
            errors.append(
                f"stale {container_kind} reservation '{name}' reported errors: "
                + "; ".join(result.errors)
            )
            continue
        if result.skipped_container_kind:
            errors.append(
                f"could not release stale {container_kind} reservation '{name}'"
            )
            continue
        if result.found and name not in result.registry_names_removed:
            errors.append(
                f"left stale {container_kind} reservation '{name}' reserved "
                "after rebuild"
            )
    if errors:
        _raise_batch_errors(errors, names, results)


def _clan_has_members(name: str) -> bool:
    from sase.agent.names import find_agent_clan

    try:
        clan = find_agent_clan(name)
    except Exception as exc:  # noqa: BLE001
        raise ForcedReuseCleanupError(
            f"forced reuse cleanup could not resolve agent clan '{name}': {exc}"
        ) from exc
    return clan is not None and bool(clan.members)


def _wipe_names_for_reuse_batch(
    names: Sequence[Any],
    *,
    allow_stale_container: bool = False,
    catalog: Any | None = None,
) -> tuple[Any, ...]:
    from sase.agent.names._session_owners import (
        wipe_names_for_reuse_batch as _shared_batch,
    )

    return _shared_batch(
        names, allow_stale_container=allow_stale_container, catalog=catalog
    )


def _wipe_batch_or_raise(
    names: Sequence[str], *, materialized: Sequence[str]
) -> tuple[Any, ...]:
    try:
        return _wipe_names_for_reuse_batch(names)
    except Exception as exc:  # noqa: BLE001
        raise ForcedReuseCleanupError(
            "forced reuse cleanup for agent names "
            f"{', '.join(repr(name) for name in materialized)} failed: {exc}"
        ) from exc


def _residual_reuse_names(results: Sequence[Any]) -> tuple[str, ...]:
    return tuple(
        result.target_name
        for result in results
        if result.found
        and not result.errors
        and not result.skipped_container_kind
        and result.target_name not in result.registry_names_removed
    )


def _merge_wipe_results(first: Sequence[Any], retry: Sequence[Any]) -> tuple[Any, ...]:
    by_name = {result.target_name: result for result in first}
    by_name.update({result.target_name: result for result in retry})
    merged = [by_name[result.target_name] for result in first]
    seen = {result.target_name for result in first}
    merged.extend(result for result in retry if result.target_name not in seen)
    return tuple(merged)


def _residual_owner_error(name: str) -> str:
    base = (
        f"forced reuse cleanup left agent name '{name}' reserved "
        "after rebuild; resolve the conflicting owner and retry"
    )
    try:
        from sase.agent.names import load_name_registry
        from sase.agent.names._session_owners import describe_residual_owner

        registry = load_name_registry()
        entries = registry.get("entries")
        if not isinstance(entries, dict):
            return base
        described = describe_residual_owner(name, entries.get(name))
    except Exception:  # noqa: BLE001
        return base
    prefix = f"{name} ("
    if described.startswith(prefix) and described.endswith(")"):
        details = described[len(prefix) - 1 :]
        return (
            f"forced reuse cleanup left agent name '{name}' reserved "
            f"after rebuild {details}; resolve the conflicting owner and retry"
        )
    return base


def _dedupe_names(names: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(name for name in names if isinstance(name, str) and name)
    )


def _raise_batch_errors(
    errors: Sequence[str],
    names: Sequence[str],
    results: Sequence[Any],
) -> None:
    from sase.agent.names._session_owners import (
        raise_forced_reuse_batch_errors as _shared_raise,
    )

    _shared_raise(errors, names, results)
