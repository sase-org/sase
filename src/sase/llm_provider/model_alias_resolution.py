"""Resolution and selector validation for configured and implicit model aliases."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sase.xprompt.effort import split_model_effort

from .load_balancing import (
    MemberAvailability,
    ModelAliasSelector,
    ModelAliasSelectorError,
    ModelAliasSelectorMode,
    fallback_availability_mask,
    parse_model_alias_selector,
    pool_availability_mask,
    select_model_alias_fallback_member,
    select_model_alias_pool_member,
    split_pool_member_weight_prefix,
)
from .model_alias_policy import (
    DEFAULT_MODEL_ALIAS_NAME,
    implicit_alias_targets,
    role_alias_fallbacks,
)
from .types import ModelTier

if TYPE_CHECKING:
    from .provider_disable import TemporaryProviderDisable

_ALIAS_RESOLUTION_DEPTH_LIMIT = 16

ProviderDisableSnapshot = Mapping[str, "TemporaryProviderDisable"]


def normalize_model_alias_reference(value: str) -> tuple[str | None, str | None]:
    """Return the clean alias name and canonical effort from *value*.

    Only a known trailing effort token is removed. Unknown ``@`` suffixes stay
    attached to the alias name so model identifiers and future syntax are not
    silently reinterpreted.
    """
    clean_value, effort = split_model_effort(value.strip())
    if not clean_value.startswith("@"):
        return None, effort
    alias = clean_value[1:].strip()
    return alias or None, effort


def active_alias_overrides() -> dict[str, Any]:
    """Return active temporary alias overrides, failing safely to none."""
    try:
        from .temporary_override import get_active_alias_overrides

        return get_active_alias_overrides()
    except Exception:
        return {}


def _active_provider_disables() -> dict[str, TemporaryProviderDisable]:
    """Return active provider disables for one routing operation."""
    from .provider_disable import get_active_provider_disables

    return get_active_provider_disables()


def _capture_provider_disables(
    provider_disables: ProviderDisableSnapshot | None,
) -> ProviderDisableSnapshot:
    if provider_disables is not None:
        return provider_disables
    return _active_provider_disables()


def resolve_default_alias_target(
    model_tier: ModelTier = "large",
    *,
    provider_disables: ProviderDisableSnapshot | None = None,
) -> str:
    """Return the fallback target for a user-defined ``@default`` alias.

    Only reached when ``default`` is neither temporarily overridden nor
    configured with an explicit target.
    """
    try:
        # Lazy import to avoid an import cycle: registry imports config.
        from .registry import (
            get_configured_default_provider_name,
            get_provider,
            provider_disable_for,
        )

        disables = _capture_provider_disables(provider_disables)
        provider_name = get_configured_default_provider_name(provider_disables=disables)
        disable = provider_disable_for(provider_name, disables)
        if disable is not None and disable.is_hard:
            return f"{provider_name}/unknown"
        model = get_provider(
            provider_name,
            provider_disables=disables,
        ).resolve_model_name(model_tier)
        return f"{provider_name}/{model}"
    except Exception:
        return DEFAULT_MODEL_ALIAS_NAME


@dataclass(frozen=True, slots=True)
class _ResolvedModelAlias:
    """Concrete target plus config-derived effort and selector provenance."""

    target: str
    effort: str | None = None
    selector_alias: str | None = None
    applied_override: Any | None = None
    suspended_override: Any | None = None
    suspended_provider_disable: TemporaryProviderDisable | None = None
    valid: bool = True
    alias_trail: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ModelAliasSelectorMember:
    """Display/diagnostic information for one alias-selector member."""

    value: str
    target: str
    effort: str | None
    provider: str | None
    available: bool
    valid: bool = True
    selected: bool = False
    weight: int = 1
    sparing: bool = False


@dataclass(frozen=True, slots=True)
class _ModelAliasSelectorDetails:
    """Selector mode and resolved member metadata for one alias."""

    mode: ModelAliasSelectorMode
    members: tuple[ModelAliasSelectorMember, ...]


def provider_for_resolved_target(target: str) -> str | None:
    """Return the explicit or metadata-inferred provider for *target*."""
    from .registry import model_to_provider_map, registered_provider_names

    if "/" in target:
        provider, _ = target.split("/", 1)
        return provider if provider else None
    inferred_provider = model_to_provider_map().get(target)
    return (
        inferred_provider if inferred_provider in registered_provider_names() else None
    )


def resolved_target_is_available(
    target: str,
    *,
    provider_disables: ProviderDisableSnapshot | None = None,
) -> bool:
    """Return whether *target* resolves to a registered, installed provider."""
    from .registry import provider_routing_available

    provider = provider_for_resolved_target(target)
    return provider_routing_available(provider, provider_disables)


def resolved_target_availability(
    target: str,
    provider_disables: ProviderDisableSnapshot | None = None,
    *,
    available: bool,
) -> MemberAvailability:
    """Layer the hard/soft disable mode on top of an already-known bool.

    ``UNAVAILABLE`` when *available* is ``False``; otherwise ``SPARING`` when
    *target*'s provider carries an active soft disable; otherwise
    ``PREFERRED``.
    """
    if not available:
        return MemberAvailability.UNAVAILABLE
    from .registry import provider_disable_for

    provider = provider_for_resolved_target(target)
    disable = provider_disable_for(provider, provider_disables)
    if disable is not None and disable.is_soft:
        return MemberAvailability.SPARING
    return MemberAvailability.PREFERRED


def _target_is_available(
    check: Callable[..., bool],
    target: str,
    provider_disables: ProviderDisableSnapshot,
) -> bool:
    try:
        return check(target, provider_disables=provider_disables)
    except TypeError:
        return check(target)


def _with_suspended_override(
    result: _ResolvedModelAlias,
    override: Any,
    disable: TemporaryProviderDisable,
) -> _ResolvedModelAlias:
    return _ResolvedModelAlias(
        result.target,
        result.effort,
        result.selector_alias,
        result.applied_override,
        override,
        disable,
        result.valid,
        result.alias_trail,
    )


def _resolve_model_alias_result(
    model: str,
    model_alias_overrides: Mapping[str, str] | None = None,
    *,
    consume: bool = False,
    model_tier: ModelTier = "large",
    provider_disables: ProviderDisableSnapshot | None = None,
    initial_seen: set[str] | None = None,
    active_selector: str | None = None,
) -> _ResolvedModelAlias:
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
    disables = _capture_provider_disables(provider_disables)
    # Loaded lazily and shared by recursive member resolutions.
    overrides: dict[str, Any] | None = None

    def fail() -> _ResolvedModelAlias:
        return _ResolvedModelAlias(original, valid=False)

    def resolve(
        value: str,
        *,
        seen: set[str],
        steps: int,
        selector_owner: str | None,
        inherited_effort: str | None,
        trail: tuple[str, ...],
    ) -> _ResolvedModelAlias:
        nonlocal overrides
        current = value.strip()
        effort = inherited_effort
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
                                member_results = [
                                    resolve(
                                        member,
                                        seen=set(seen),
                                        steps=steps + 1,
                                        selector_owner=bare,
                                        inherited_effort=effort,
                                        trail=next_trail,
                                    )
                                    for member in selector.members
                                ]
                                if any(not result.valid for result in member_results):
                                    return fail()
                                availability_check = config.__dict__.get(
                                    "_resolved_target_is_available",
                                    resolved_target_is_available,
                                )
                                states = [
                                    resolved_target_availability(
                                        result.target,
                                        disables,
                                        available=_target_is_available(
                                            availability_check,
                                            result.target,
                                            disables,
                                        ),
                                    )
                                    for result in member_results
                                ]
                                if selector.mode == "round_robin":
                                    index = select_model_alias_pool_member(
                                        bare,
                                        selector,
                                        pool_availability_mask(states),
                                        consume=consume,
                                    )
                                else:
                                    index = select_model_alias_fallback_member(
                                        fallback_availability_mask(states)
                                    )
                                return _with_suspended_override(
                                    member_results[index],
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
                    return _ResolvedModelAlias(
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
                    member_results = [
                        resolve(
                            member,
                            seen=set(seen),
                            steps=steps + 1,
                            selector_owner=bare,
                            inherited_effort=effort,
                            trail=trail,
                        )
                        for member in selector.members
                    ]
                    if any(not result.valid for result in member_results):
                        return fail()
                    availability_check = config.__dict__.get(
                        "_resolved_target_is_available",
                        resolved_target_is_available,
                    )
                    states = [
                        resolved_target_availability(
                            result.target,
                            disables,
                            available=_target_is_available(
                                availability_check,
                                result.target,
                                disables,
                            ),
                        )
                        for result in member_results
                    ]
                    if selector.mode == "round_robin":
                        index = select_model_alias_pool_member(
                            bare,
                            selector,
                            pool_availability_mask(states),
                            consume=consume,
                        )
                    else:
                        index = select_model_alias_fallback_member(
                            fallback_availability_mask(states)
                        )
                    return member_results[index]
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
            return _ResolvedModelAlias(
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
) -> _ResolvedModelAlias:
    """Resolve *model*, retaining alias-borne effort and selector provenance.

    ``consume=False`` is the safe default for display, completion, doctor, and
    preview callers. Authoritative launch lanes pass ``consume=True`` so each
    launched agent advances a round-robin cursor exactly once.
    """
    return _resolve_model_alias_result(
        model,
        model_alias_overrides,
        consume=consume,
        model_tier=model_tier,
        provider_disables=provider_disables,
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

    Alias values may be round-robin pools or ordered fallback chains. Launch
    overrides win first, followed by temporary overrides, configured aliases,
    and implicit role fallbacks. Invalid chains fail closed to the input.
    """
    return resolve_model_alias_with_effort(
        model,
        model_alias_overrides,
        consume=consume,
        model_tier=model_tier,
        provider_disables=provider_disables,
    ).target


def _model_alias_selector(name: str) -> ModelAliasSelector | None:
    """Return the configured/implicit selector owned by alias *name*, if any."""
    from . import config

    alias = name.strip()
    value = config._get_model_aliases().get(alias)
    if value is None:
        value = config.implicit_model_alias_value(alias)
    if value is None:
        return None
    try:
        return parse_model_alias_selector(value)
    except ModelAliasSelectorError:
        return None


def model_alias_selector_details(
    name: str,
    *,
    provider_disables: ProviderDisableSnapshot | None = None,
) -> _ModelAliasSelectorDetails | None:
    """Return selector mode and resolved member details for alias *name*."""
    from . import config

    alias = name.strip()
    selector = _model_alias_selector(alias)
    if selector is None:
        return None
    disables = _capture_provider_disables(provider_disables)
    resolved: list[
        tuple[str, _ResolvedModelAlias, str | None, bool, MemberAvailability]
    ] = []
    for value in selector.members:
        result = _resolve_model_alias_result(
            value,
            provider_disables=disables,
            initial_seen={alias},
            active_selector=alias,
        )
        provider_lookup = config.__dict__.get(
            "_provider_for_resolved_target",
            provider_for_resolved_target,
        )
        provider = provider_lookup(result.target) if result.valid else None
        availability_check = config.__dict__.get(
            "_resolved_target_is_available",
            resolved_target_is_available,
        )
        available = result.valid and _target_is_available(
            availability_check,
            result.target,
            disables,
        )
        state = resolved_target_availability(
            result.target, disables, available=available
        )
        resolved.append((value, result, provider, available, state))

    states = [item[4] for item in resolved]
    if selector.mode == "round_robin":
        selected_index = select_model_alias_pool_member(
            alias, selector, pool_availability_mask(states), consume=False
        )
    else:
        selected_index = select_model_alias_fallback_member(
            fallback_availability_mask(states)
        )

    members: list[ModelAliasSelectorMember] = []
    for index, (value, result, provider, available, state) in enumerate(resolved):
        members.append(
            ModelAliasSelectorMember(
                value=value,
                target=result.target,
                effort=result.effort,
                provider=provider,
                available=available,
                valid=result.valid,
                selected=index == selected_index,
                weight=selector.weights[index],
                sparing=state == MemberAvailability.SPARING,
            )
        )
    return _ModelAliasSelectorDetails(mode=selector.mode, members=tuple(members))


def validate_model_alias_selector_value(name: str, value: str) -> tuple[str, ...]:
    """Return actionable validation errors for an alias selector value."""
    from . import config

    try:
        selector = parse_model_alias_selector(value)
    except ModelAliasSelectorError as exc:
        return (str(exc),)
    if selector is None:
        prefix = split_pool_member_weight_prefix(value)
        if prefix is not None:
            token, _rest = prefix
            return (
                "weights only apply to '|' load-balanced pool members; "
                f"remove the '{token} ' prefix",
            )
        return ()

    aliases = config._get_model_aliases()
    errors: list[str] = []
    owner = name.strip() or "<alias>"
    member_label = (
        "pool member" if selector.mode == "round_robin" else "fallback candidate"
    )
    for position, member in enumerate(selector.members, start=1):
        current, _ = split_model_effort(member)
        seen = {owner}
        for _ in range(_ALIAS_RESOLUTION_DEPTH_LIMIT):
            if not current.startswith("@"):
                if not current.strip():
                    errors.append(
                        f"{member_label} {position} resolves to an empty target"
                    )
                break
            referenced = current[1:].strip()
            referenced, _ = split_model_effort(referenced)
            if not referenced:
                errors.append(f"{member_label} {position} has an empty alias reference")
                break
            if referenced in seen:
                errors.append(
                    f"{member_label} {position} creates an alias cycle through "
                    f"'@{referenced}'"
                )
                break
            seen.add(referenced)
            target = aliases.get(referenced)
            if target is None:
                target = config.implicit_model_alias_value(referenced)
            if target is None:
                target = config.implicit_model_alias_fallback_reference(referenced)
            if target is None:
                errors.append(
                    f"{member_label} {position} references unknown alias "
                    f"'@{referenced}'"
                )
                break
            try:
                nested = parse_model_alias_selector(target)
            except ModelAliasSelectorError as exc:
                errors.append(
                    f"{member_label} {position} reaches malformed alias "
                    f"'@{referenced}': {exc}"
                )
                break
            if nested is not None:
                nested_name = (
                    "load-balanced pool"
                    if nested.mode == "round_robin"
                    else "ordered fallback"
                )
                errors.append(
                    f"{member_label} {position} reaches nested {nested_name} "
                    f"'@{referenced}'; selector members must resolve to a single "
                    "target"
                )
                break
            current, _ = split_model_effort(target.strip())
        else:
            errors.append(
                f"{member_label} {position} exceeds the alias resolution depth limit"
            )
    return tuple(dict.fromkeys(errors))
