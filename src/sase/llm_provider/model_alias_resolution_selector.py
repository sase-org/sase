"""Selector diagnostics and validation for model-alias values."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sase.xprompt.effort import split_model_effort

from .load_balancing import (
    MemberAvailability,
    ModelAliasSelector,
    ModelAliasSelectorError,
    ModelAliasSelectorMode,
    concatenated_selector_members,
    parse_model_alias_selector,
    select_model_alias_selector_index,
    split_pool_member_weight_prefix,
)
from .model_alias_resolution_resolve import resolve_model_alias_with_effort
from .model_alias_resolution_types import (
    ModelAliasSelectorMember,
    ProviderDisableSnapshot,
    ResolvedModelAlias,
    _ALIAS_RESOLUTION_DEPTH_LIMIT,
    capture_provider_disables,
    provider_for_resolved_target,
    resolved_target_availability,
    resolved_target_is_available,
    target_is_available,
)


@dataclass(frozen=True, slots=True)
class _ModelAliasSelectorDetails:
    """Selector mode and resolved member metadata for one alias."""

    mode: ModelAliasSelectorMode
    members: tuple[ModelAliasSelectorMember, ...]


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
    disables = capture_provider_disables(provider_disables)
    values = concatenated_selector_members(selector)
    pool_count = len(selector.members)
    weights = selector.weights + (1,) * len(selector.fallback_members)
    resolved: list[
        tuple[str, ResolvedModelAlias, str | None, bool, MemberAvailability]
    ] = []
    for value in values:
        result = resolve_model_alias_with_effort(
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
        available = result.valid and target_is_available(
            availability_check,
            result.target,
            disables,
        )
        state = resolved_target_availability(
            result.target, disables, available=available
        )
        resolved.append((value, result, provider, available, state))

    selected_index = select_model_alias_selector_index(
        alias,
        selector,
        [item[4] for item in resolved],
        consume=False,
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
                weight=weights[index],
                sparing=state == MemberAvailability.SPARING,
                last_resort=index >= pool_count,
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
    groups: list[tuple[str, tuple[str, ...]]] = []
    if selector.mode == "round_robin":
        groups.append(("pool member", selector.members))
        if selector.fallback_members:
            groups.append(("last-resort candidate", selector.fallback_members))
    else:
        groups.append(("fallback candidate", selector.members))
    for member_label, group in groups:
        errors.extend(
            _validate_selector_member_group(
                group,
                member_label=member_label,
                owner=owner,
                aliases=aliases,
            )
        )
    return tuple(dict.fromkeys(errors))


def _validate_selector_member_group(
    members: tuple[str, ...],
    *,
    member_label: str,
    owner: str,
    aliases: Mapping[str, str],
) -> list[str]:
    from . import config

    errors: list[str] = []
    for position, member in enumerate(members, start=1):
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
    return errors
