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

from typing import Literal


class ForcedReuseCleanupError(RuntimeError):
    """Raised when forced-name-reuse cleanup cannot be completed."""


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
    from sase.agent.names import wipe_agent_name_for_reuse

    try:
        result = wipe_agent_name_for_reuse(name)
    except Exception as exc:  # noqa: BLE001
        raise ForcedReuseCleanupError(
            f"forced reuse cleanup for agent name '{name}' failed: {exc}"
        ) from exc
    if result.errors:
        raise ForcedReuseCleanupError(
            f"forced reuse cleanup for agent name '{name}' reported errors: "
            + "; ".join(result.errors)
        )
    if result.skipped_container_kind:
        if result.skipped_container_kind == "family":
            _wipe_family_for_forced_reuse(name)
            return
        if result.skipped_container_kind == "clan":
            from sase.agent.names import find_agent_clan

            try:
                clan = find_agent_clan(name)
            except Exception as exc:  # noqa: BLE001
                raise ForcedReuseCleanupError(
                    f"forced reuse cleanup could not resolve agent clan '{name}': {exc}"
                ) from exc
            if clan is None or not clan.members:
                release_stale_container(name, container_kind="clan")
                return
            if allow_container_skip:
                return
        raise ForcedReuseCleanupError(
            f"agent name '{name}' is reserved by a "
            f"{result.skipped_container_kind} container and cannot be "
            "force-reused; dismiss or clean up the container's members, then retry"
        )
    if result.found and name not in result.registry_names_removed:
        raise ForcedReuseCleanupError(
            f"forced reuse cleanup left agent name '{name}' reserved after "
            "rebuild; resolve the conflicting owner and retry"
        )


def _wipe_family_for_forced_reuse(name: str) -> None:
    """Resolve and wipe every concrete member of the newest family generation."""
    from sase.agent.names import (
        find_agent_family,
        rebuild_name_registry,
        wipe_agent_name_for_reuse,
    )

    try:
        family = find_agent_family(name)
    except Exception as exc:  # noqa: BLE001
        raise ForcedReuseCleanupError(
            f"forced reuse cleanup could not resolve agent family '{name}': {exc}"
        ) from exc

    member_names = sorted(
        {
            member.name
            for member in family.members
            if isinstance(member.name, str) and member.name and member.name != name
        }
        if family is not None
        else set()
    )
    if not member_names:
        release_stale_container(name, container_kind="family")
        return

    for member_name in member_names:
        try:
            result = wipe_agent_name_for_reuse(member_name)
        except Exception as exc:  # noqa: BLE001
            raise ForcedReuseCleanupError(
                f"forced reuse cleanup for agent family '{name}' member "
                f"'{member_name}' failed: {exc}"
            ) from exc
        if result.errors:
            raise ForcedReuseCleanupError(
                f"forced reuse cleanup for agent family '{name}' member "
                f"'{member_name}' reported errors: " + "; ".join(result.errors)
            )
        if result.skipped_container_kind:
            raise ForcedReuseCleanupError(
                f"forced reuse cleanup for agent family '{name}' member "
                f"'{member_name}' resolved to a "
                f"{result.skipped_container_kind} container"
            )
        # A member that has already disappeared (``found is False``) is
        # tolerated: the ACE persistence proc may have removed it first, and
        # the residual-reservation check below still catches anything left.

    try:
        registry = rebuild_name_registry()
    except Exception as exc:  # noqa: BLE001
        raise ForcedReuseCleanupError(
            f"forced reuse cleanup for agent family '{name}' could not rebuild "
            f"the name registry: {exc}"
        ) from exc
    entries = registry.get("entries")
    if not isinstance(entries, dict):
        raise ForcedReuseCleanupError(
            f"forced reuse cleanup for agent family '{name}' received an "
            "invalid name registry after rebuild"
        )
    residual_names = sorted({name, *member_names} & set(entries))
    if residual_names:
        raise ForcedReuseCleanupError(
            f"forced reuse cleanup left agent family '{name}' reservations "
            f"after rebuild: {', '.join(residual_names)}"
        )


def release_stale_container(
    name: str,
    *,
    container_kind: Literal["family", "clan"],
) -> None:
    """Remove an orphaned container's residual owner and verify its release."""
    from sase.agent.names import (
        is_name_reserved,
        rebuild_name_registry,
        wipe_agent_name_for_reuse,
    )

    try:
        result = wipe_agent_name_for_reuse(name, allow_stale_container=True)
    except Exception as exc:  # noqa: BLE001
        raise ForcedReuseCleanupError(
            f"forced reuse cleanup for stale {container_kind} reservation "
            f"'{name}' failed: {exc}"
        ) from exc
    if result.errors:
        raise ForcedReuseCleanupError(
            f"forced reuse cleanup for stale {container_kind} reservation "
            f"'{name}' reported errors: " + "; ".join(result.errors)
        )
    if result.skipped_container_kind:
        raise ForcedReuseCleanupError(
            f"forced reuse cleanup could not release stale {container_kind} "
            f"reservation '{name}'"
        )

    try:
        registry = rebuild_name_registry()
    except Exception as exc:  # noqa: BLE001
        raise ForcedReuseCleanupError(
            f"forced reuse cleanup for stale {container_kind} reservation "
            f"'{name}' could not rebuild the name registry: {exc}"
        ) from exc
    if not isinstance(registry.get("entries"), dict):
        raise ForcedReuseCleanupError(
            f"forced reuse cleanup for stale {container_kind} reservation "
            f"'{name}' received an invalid name registry after rebuild"
        )
    if is_name_reserved(name):
        raise ForcedReuseCleanupError(
            f"forced reuse cleanup left stale {container_kind} reservation "
            f"'{name}' reserved after rebuild"
        )
