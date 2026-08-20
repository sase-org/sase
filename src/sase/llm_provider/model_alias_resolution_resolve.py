"""Alias-chain resolution for configured and implicit model aliases."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from sase.xprompt.effort import split_model_effort

from .load_balancing import (
    MemberAvailability,
    ModelAliasSelector,
    ModelAliasSelectorError,
    concatenated_selector_members,
    parse_model_alias_selector,
    select_model_alias_selector_index,
)
from .model_alias_policy import implicit_alias_targets, role_alias_fallbacks
from .model_alias_resolution_types import (
    ProviderDisableSnapshot,
    ResolvedModelAlias,
    _ALIAS_RESOLUTION_DEPTH_LIMIT,
    capture_provider_disables,
    resolved_target_availability,
    resolved_target_is_available,
    target_is_available,
)
from .types import ModelTier

if TYPE_CHECKING:
    from .provider_disable import TemporaryProviderDisable


def _with_suspended_override(
    result: ResolvedModelAlias,
    override: Any,
    disable: TemporaryProviderDisable,
) -> ResolvedModelAlias:
    return ResolvedModelAlias(
        result.target,
        result.effort,
        result.selector_alias,
        result.applied_override,
        override,
        disable,
        result.valid,
        result.alias_trail,
    )


def _selector_member_states(
    member_results: Sequence[ResolvedModelAlias],
    disables: ProviderDisableSnapshot,
) -> list[MemberAvailability]:
    from . import config

    availability_check = config.__dict__.get(
        "_resolved_target_is_available",
        resolved_target_is_available,
    )
    return [
        resolved_target_availability(
            result.target,
            disables,
            available=target_is_available(
                availability_check,
                result.target,
                disables,
            ),
        )
        for result in member_results
    ]


def _pick_selector_member(
    *,
    alias: str,
    selector: ModelAliasSelector,
    member_results: Sequence[ResolvedModelAlias],
    disables: ProviderDisableSnapshot,
    consume: bool,
) -> ResolvedModelAlias | None:
    if any(not result.valid for result in member_results):
        return None
    index = select_model_alias_selector_index(
        alias,
        selector,
        _selector_member_states(member_results, disables),
        consume=consume,
    )
    return member_results[index]


def _resolve_model_alias_result(
    model: str,
    model_alias_overrides: Mapping[str, str] | None = None,
    *,
    consume: bool = False,
    model_tier: ModelTier = "large",
    provider_disables: ProviderDisableSnapshot | None = None,
    initial_seen: set[str] | None = None,
    active_selector: str | None = None,
) -> ResolvedModelAlias:
    """Internal alias resolver retaining effort and selector provenance."""
    from . import config
    from .launch_alias_overrides import active_launch_alias_overrides

    aliases = config._get_model_aliases()
    launch_overrides = active_launch_alias_overrides(model_alias_overrides)
    original = model
    # Bound once and shared by recursive member resolutions rather than
    # re-calling the (cheap but cached-lookup-backed) accessors per step.
    role_fallbacks = role_alias_fallbacks()
    role_targets = implicit_alias_targets()
    disables = capture_provider_disables(provider_disables)
    # Loaded lazily and shared by recursive member resolutions.
    overrides: dict[str, Any] | None = None

    def fail() -> ResolvedModelAlias:
        return ResolvedModelAlias(original, valid=False)

    def resolve(
        value: str,
        *,
        seen: set[str],
        steps: int,
        selector_owner: str | None,
        inherited_effort: str | None,
        trail: tuple[str, ...],
    ) -> ResolvedModelAlias:
        nonlocal overrides
        current = value.strip()
        effort = inherited_effort

        def resolve_selector(
            selector: ModelAliasSelector,
            *,
            owner: str,
            member_trail: tuple[str, ...],
        ) -> ResolvedModelAlias | None:
            member_results = [
                resolve(
                    member,
                    seen=set(seen),
                    steps=steps + 1,
                    selector_owner=owner,
                    inherited_effort=effort,
                    trail=member_trail,
                )
                for member in concatenated_selector_members(selector)
            ]
            return _pick_selector_member(
                alias=owner,
                selector=selector,
                member_results=member_results,
                disables=disables,
                consume=consume,
            )

        while steps < _ALIAS_RESOLUTION_DEPTH_LIMIT:
            current, current_effort = split_model_effort(current.strip())
            if effort is None:
                effort = current_effort
            bare = current[1:].strip() if current.startswith("@") else current
            if not bare:
                return fail()

            known_alias = (
                bare in aliases or bare in role_fallbacks or bare in role_targets
            )
            launch_target = launch_overrides.get(bare) if known_alias else None
            if launch_target is not None:
                if bare in seen:
                    return fail()
                seen.add(bare)
                trail = trail + (bare,)
                current = launch_target
                steps += 1
                continue

            # A temporary override suspends selector behavior for that alias,
            # including ``default``.
            if known_alias:
                if overrides is None:
                    overrides = config._active_alias_overrides()
                override = overrides.get(bare)
                if override is not None:
                    override_effort = getattr(override, "effort", None)
                    if not isinstance(override_effort, str):
                        override_effort = None
                    from .registry import provider_disable_for

                    suspended_disable = provider_disable_for(
                        getattr(override, "provider", None),
                        disables,
                    )
                    if suspended_disable is not None and suspended_disable.is_hard:
                        underlying_target = aliases.get(bare)
                        if underlying_target is None:
                            underlying_target = role_targets.get(bare)
                        if underlying_target is not None:
                            if bare in seen or not underlying_target:
                                return fail()
                            seen.add(bare)
                            next_trail = trail + (bare,)
                            try:
                                selector = parse_model_alias_selector(underlying_target)
                            except ModelAliasSelectorError:
                                return fail()
                            if selector is not None:
                                if selector_owner is not None:
                                    return fail()
                                picked = resolve_selector(
                                    selector, owner=bare, member_trail=next_trail
                                )
                                if picked is None:
                                    return fail()
                                return _with_suspended_override(
                                    picked,
                                    override,
                                    suspended_disable,
                                )
                            result = resolve(
                                underlying_target,
                                seen=set(seen),
                                steps=steps + 1,
                                selector_owner=selector_owner,
                                inherited_effort=effort,
                                trail=next_trail,
                            )
                            return _with_suspended_override(
                                result, override, suspended_disable
                            )
                        fallback = config.implicit_model_alias_fallback_reference(bare)
                        if fallback is not None:
                            if bare in seen:
                                return fail()
                            seen.add(bare)
                            next_trail = trail + (bare,)
                            result = resolve(
                                fallback,
                                seen=set(seen),
                                steps=steps + 1,
                                selector_owner=selector_owner,
                                inherited_effort=effort,
                                trail=next_trail,
                            )
                            return _with_suspended_override(
                                result, override, suspended_disable
                            )
                    return ResolvedModelAlias(
                        f"{override.provider}/{override.model}",
                        effort or override_effort,
                        selector_owner,
                        applied_override=override,
                        alias_trail=trail + (bare,),
                    )

            target: str | None = None
            if bare in aliases:
                target = aliases[bare].strip()
            elif bare in role_targets:
                target = role_targets[bare]

            if target is not None:
                if bare in seen or not target:
                    return fail()
                seen.add(bare)
                trail = trail + (bare,)
                try:
                    selector = parse_model_alias_selector(target)
                except ModelAliasSelectorError:
                    return fail()
                if selector is not None:
                    # A selector reached from a member of another selector is
                    # invalid, matching cycle/depth fail-closed behavior.
                    if selector_owner is not None:
                        return fail()
                    picked = resolve_selector(selector, owner=bare, member_trail=trail)
                    if picked is None:
                        return fail()
                    return picked
                current = target
                steps += 1
                continue

            fallback_reference = config.implicit_model_alias_fallback_reference(bare)
            if fallback_reference is not None:
                if bare in seen:
                    return fail()
                seen.add(bare)
                trail = trail + (bare,)
                current = fallback_reference
                steps += 1
                continue

            # A concrete model name (or dangling alias reference) is terminal.
            return ResolvedModelAlias(
                bare if current.startswith("@") else current,
                effort,
                selector_owner,
                alias_trail=trail,
            )
        return fail()

    return resolve(
        model,
        seen=set() if initial_seen is None else set(initial_seen),
        steps=0,
        selector_owner=active_selector,
        inherited_effort=None,
        trail=(),
    )


def resolve_model_alias_with_effort(
    model: str,
    model_alias_overrides: Mapping[str, str] | None = None,
    *,
    consume: bool = False,
    model_tier: ModelTier = "large",
    provider_disables: ProviderDisableSnapshot | None = None,
    initial_seen: set[str] | None = None,
    active_selector: str | None = None,
) -> ResolvedModelAlias:
    """Resolve *model*, retaining alias-borne effort and selector provenance.

    ``consume=False`` is the safe default for display, completion, doctor, and
    preview callers. Authoritative launch lanes pass ``consume=True`` so each
    launched agent advances a round-robin cursor exactly once.

    ``initial_seen`` and ``active_selector`` are used when resolving a selector
    member so nested selectors and cycles fail closed.
    """
    return _resolve_model_alias_result(
        model,
        model_alias_overrides,
        consume=consume,
        model_tier=model_tier,
        provider_disables=provider_disables,
        initial_seen=initial_seen,
        active_selector=active_selector,
    )


def resolve_model_alias(
    model: str,
    model_alias_overrides: Mapping[str, str] | None = None,
    *,
    consume: bool = False,
    model_tier: ModelTier = "large",
    provider_disables: ProviderDisableSnapshot | None = None,
) -> str:
    """Resolve a model alias to its concrete target string.

    Alias values may be round-robin pools, ordered fallback chains, or a
    parenthesized pool with a last-resort tail. Launch overrides win first,
    followed by temporary overrides, configured aliases, and implicit role
    fallbacks. Invalid chains fail closed to the input.
    """
    return resolve_model_alias_with_effort(
        model,
        model_alias_overrides,
        consume=consume,
        model_tier=model_tier,
        provider_disables=provider_disables,
    ).target
