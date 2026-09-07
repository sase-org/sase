"""Shared forced-name-reuse cleanup for concrete owners, families, and clans.

Both the ACE/``sase agent restart`` launch boundary and deterministic bead
relaunch need the same policy: a concrete owner is wiped directly, a family
container relaunch replaces its newest generation (every concrete member is
wiped, then the registry is rebuilt and checked for residual reservations),
and a populated clan container is refused unless the caller opts into the
container-skip escape hatch. Keeping one implementation here prevents bead
and ACE forced-reuse behavior from drifting apart again.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal


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

    A concrete owner is wiped and verified gone. A family container always
    resolves and replaces its newest generation: relaunching a family root
    means the prior generation's concrete shells must be gone before the
    bare family name is reused. A populated clan container is a rootless
    parallel group, not one replaceable agent, and is refused unless
    *allow_container_skip* allows the caller to skip past it (its members
    retain their own explicit relaunch path).
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

    try:
        results = _wipe_names_for_reuse_batch(materialized)
    except Exception as exc:  # noqa: BLE001
        raise ForcedReuseCleanupError(
            "forced reuse cleanup for agent names "
            f"{', '.join(repr(name) for name in materialized)} failed: {exc}"
        ) from exc

    errors: list[str] = []
    family_names: list[str] = []
    stale_clan_names: list[str] = []
    for result in results:
        name = result.target_name
        if result.errors:
            errors.append(
                f"agent name '{name}' reported errors: " + "; ".join(result.errors)
            )
            continue
        if result.skipped_container_kind == "family":
            family_names.append(name)
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
            errors.append(
                f"forced reuse cleanup left agent name '{name}' reserved "
                "after rebuild; resolve the conflicting owner and retry"
            )

    if errors:
        _raise_batch_errors(errors, materialized, results)

    if stale_clan_names:
        release_stale_containers(tuple((name, "clan") for name in stale_clan_names))
    if family_names:
        _wipe_families_for_forced_reuse(family_names)


def _wipe_families_for_forced_reuse(names: Sequence[str]) -> None:
    """Resolve and wipe concrete members for several family containers."""
    from sase.agent.names import (
        find_agent_family,
        load_name_registry,
    )

    materialized = _dedupe_names(names)
    members_by_family: dict[str, tuple[str, ...]] = {}
    all_member_names: set[str] = set()
    stale_families: list[str] = []
    for name in materialized:
        try:
            family = find_agent_family(name)
        except Exception as exc:  # noqa: BLE001
            raise ForcedReuseCleanupError(
                f"forced reuse cleanup could not resolve agent family '{name}': {exc}"
            ) from exc

        member_names = tuple(
            sorted(
                {
                    member.name
                    for member in family.members
                    if isinstance(member.name, str)
                    and member.name
                    and member.name != name
                }
                if family is not None
                else set()
            )
        )
        if not member_names:
            stale_families.append(name)
            continue
        members_by_family[name] = member_names
        all_member_names.update(member_names)

    if stale_families:
        release_stale_containers(tuple((name, "family") for name in stale_families))
    if not all_member_names:
        return

    try:
        results = _wipe_names_for_reuse_batch(tuple(sorted(all_member_names)))
    except Exception as exc:  # noqa: BLE001
        raise ForcedReuseCleanupError(
            f"forced reuse cleanup for agent family members failed: {exc}"
        ) from exc

    errors: list[str] = []
    for result in results:
        member_name = result.target_name
        if result.errors:
            family_name = _family_for_member(members_by_family, member_name)
            errors.append(
                f"agent family '{family_name}' member '{member_name}' "
                "reported errors: " + "; ".join(result.errors)
            )
            continue
        if result.skipped_container_kind:
            family_name = _family_for_member(members_by_family, member_name)
            errors.append(
                f"agent family '{family_name}' member '{member_name}' resolved to a "
                f"{result.skipped_container_kind} container"
            )
    if errors:
        _raise_batch_errors(errors, tuple(sorted(all_member_names)), results)

    try:
        registry = load_name_registry()
    except Exception as exc:  # noqa: BLE001
        raise ForcedReuseCleanupError(
            "forced reuse cleanup for agent families could not read the name "
            f"registry after rebuild: {exc}"
        ) from exc
    entries = registry.get("entries")
    if not isinstance(entries, dict):
        raise ForcedReuseCleanupError(
            "forced reuse cleanup for agent families received an "
            "invalid name registry after rebuild"
        )

    residual_errors: list[str] = []
    for family_name, member_names in members_by_family.items():
        residual_names = sorted({family_name, *member_names} & set(entries))
        if residual_names:
            residual_errors.append(
                f"forced reuse cleanup left agent family '{family_name}' "
                f"reservations after rebuild: {', '.join(residual_names)}"
            )
    if residual_errors:
        raise ForcedReuseCleanupError("; ".join(residual_errors))


def release_stale_container(
    name: str,
    *,
    container_kind: Literal["family", "clan"],
) -> None:
    """Remove an orphaned container's residual owner and verify its release."""
    release_stale_containers(((name, container_kind),))


def release_stale_containers(
    containers: Sequence[tuple[str, Literal["family", "clan"]]],
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


def _family_for_member(
    members_by_family: dict[str, tuple[str, ...]],
    member_name: str,
) -> str:
    for family_name, member_names in members_by_family.items():
        if member_name in member_names:
            return family_name
    return "unknown"


def _wipe_names_for_reuse_batch(
    names: Sequence[str],
    *,
    allow_stale_container: bool = False,
) -> tuple[Any, ...]:
    from sase.agent import names as names_mod
    from sase.agent.names import _wipe as wipe_module

    batch_helper = names_mod.wipe_agent_names_for_reuse
    single_helper = names_mod.wipe_agent_name_for_reuse
    if (
        single_helper is not wipe_module.wipe_agent_name_for_reuse
        and batch_helper is wipe_module.wipe_agent_names_for_reuse
    ):
        if allow_stale_container:
            return tuple(
                single_helper(name, allow_stale_container=True) for name in names
            )
        return tuple(single_helper(name) for name in names)
    return tuple(batch_helper(names, allow_stale_container=allow_stale_container))


def _dedupe_names(names: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(name for name in names if isinstance(name, str) and name)
    )


def _raise_batch_errors(
    errors: Sequence[str],
    names: Sequence[str],
    results: Sequence[Any],
) -> None:
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
