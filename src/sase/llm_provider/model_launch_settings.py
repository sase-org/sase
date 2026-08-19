"""Launch model settings and effective routing snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from .load_balancing import (
    MemberAvailability,
    ModelAliasSelectorError,
    concatenated_selector_members,
    parse_model_alias_selector,
    select_model_alias_selector_index,
)
from .model_alias_resolution import normalize_model_alias_reference
from .types import ModelTier

if TYPE_CHECKING:
    from .model_alias_resolution import ModelAliasSelectorMember
    from .provider_disable import TemporaryProviderDisable
    from .temporary_override_state import TemporaryLLMOverride


LaunchModelField = Literal[
    "default_model",
    "epic_lander_model",
    "big_epic_lander_model",
]
LaunchModelProvenance = Literal[
    "temporary",
    "configured",
    "shipped",
    "launch_override",
]

DEFAULT_MODEL_FIELD: LaunchModelField = "default_model"
EPIC_LANDER_MODEL_FIELD: LaunchModelField = "epic_lander_model"
BIG_EPIC_LANDER_MODEL_FIELD: LaunchModelField = "big_epic_lander_model"

DEFAULT_MODEL_DEFAULT = "@large"
EPIC_LANDER_MODEL_DEFAULT = "@large"
BIG_EPIC_LANDER_MODEL_DEFAULT = "@xlarge"

_FIELD_DEFAULTS: Mapping[LaunchModelField, str] = {
    DEFAULT_MODEL_FIELD: DEFAULT_MODEL_DEFAULT,
    EPIC_LANDER_MODEL_FIELD: EPIC_LANDER_MODEL_DEFAULT,
    BIG_EPIC_LANDER_MODEL_FIELD: BIG_EPIC_LANDER_MODEL_DEFAULT,
}

_SETTING_OVERRIDE_KEYS: Mapping[LaunchModelField, str] = {
    DEFAULT_MODEL_FIELD: "setting:default_model",
    EPIC_LANDER_MODEL_FIELD: "setting:epic_lander_model",
    BIG_EPIC_LANDER_MODEL_FIELD: "setting:big_epic_lander_model",
}


@dataclass(frozen=True, slots=True)
class LaunchModelSettingSnapshot:
    """Display/runtime snapshot for one scalar launch model setting."""

    field: LaunchModelField
    config_path: str
    raw_value: str
    provider: str
    model: str
    effort: str | None
    provenance: LaunchModelProvenance
    referenced_alias: str | None
    override_key: str
    alias_trail: tuple[str, ...] = ()
    override: TemporaryLLMOverride | None = None
    selector_mode: str | None = None
    selector_members: tuple[ModelAliasSelectorMember, ...] = ()
    override_paused_by_provider_disable: TemporaryProviderDisable | None = None


def get_default_model() -> str:
    """Return the validated no-``%model`` launch expression."""
    return _get_launch_model_field(DEFAULT_MODEL_FIELD)


def get_epic_lander_model() -> str:
    """Return the validated normal epic-land expression."""
    return _get_launch_model_field(EPIC_LANDER_MODEL_FIELD)


def get_big_epic_lander_model() -> str:
    """Return the validated big-epic land expression."""
    return _get_launch_model_field(BIG_EPIC_LANDER_MODEL_FIELD)


def launch_model_setting_override_key(field: LaunchModelField) -> str:
    """Return the namespaced temporary-override key for *field*."""
    return _SETTING_OVERRIDE_KEYS[field]


def launch_model_setting_override_keys() -> frozenset[str]:
    """Return every namespaced temporary-override key for launch settings."""
    return frozenset(_SETTING_OVERRIDE_KEYS.values())


def launch_model_setting_alias(
    field: LaunchModelField,
    model_alias_overrides: Mapping[str, str] | None = None,
    *,
    provider_disables: Mapping[str, TemporaryProviderDisable] | None = None,
) -> str | None:
    """Return the referenced alias that should be recorded for *field*, if any."""
    snapshot = build_launch_model_setting_snapshot(
        field,
        model_alias_overrides,
        consume=False,
        provider_disables=provider_disables,
    )
    return snapshot.referenced_alias


def build_launch_model_setting_snapshot(
    field: LaunchModelField,
    model_alias_overrides: Mapping[str, str] | None = None,
    *,
    model_tier: ModelTier = "large",
    consume: bool = False,
    provider_disables: Mapping[str, TemporaryProviderDisable] | None = None,
) -> LaunchModelSettingSnapshot:
    """Resolve one scalar launch model setting into a display/runtime snapshot."""
    from .launch_alias_overrides import active_launch_alias_overrides
    from .provider_disable import get_active_provider_disables
    from .registry import (
        get_configured_default_provider_name,
        resolve_model_provider_with_effort,
        resolve_model_provider_with_trail,
    )
    from .temporary_override import get_active_alias_override
    from .config import model_alias_selector_details
    from .model_alias_resolution import (
        ModelAliasSelectorMember,
        provider_for_resolved_target,
        resolved_target_availability,
        resolved_target_is_available,
        resolve_model_alias_with_effort,
    )

    overrides = active_launch_alias_overrides(model_alias_overrides)
    disables = (
        get_active_provider_disables()
        if provider_disables is None
        else provider_disables
    )
    override_key = launch_model_setting_override_key(field)
    raw_value, provenance = _launch_model_field_value(field, overrides)
    override = get_active_alias_override(override_key)
    paused_disable = disables.get(override.provider) if override is not None else None
    if paused_disable is not None and paused_disable.is_soft:
        paused_disable = None
    if override is not None and paused_disable is None:
        return LaunchModelSettingSnapshot(
            field=field,
            config_path=f"llm_provider.{field}",
            raw_value=raw_value,
            provider=override.provider,
            model=override.model,
            effort=override.effort,
            provenance="temporary",
            referenced_alias=None,
            override_key=override_key,
            override=override,
        )

    referenced_alias, _alias_effort = normalize_model_alias_reference(raw_value)
    selector = (
        model_alias_selector_details(referenced_alias, provider_disables=disables)
        if referenced_alias is not None
        else None
    )
    selector_members: tuple[ModelAliasSelectorMember, ...] = ()
    selector_mode = selector.mode if selector is not None else None
    alias_trail: tuple[str, ...] = ()
    if selector is not None:
        provider, model, effort, alias_trail = resolve_model_provider_with_trail(
            raw_value,
            overrides,
            consume=consume,
            model_tier=model_tier,
            provider_disables=disables,
        )
        selector_members = selector.members
    else:
        raw_selector = parse_model_alias_selector(raw_value)
        if raw_selector is not None:
            values = concatenated_selector_members(raw_selector)
            pool_count = len(raw_selector.members)
            weights = raw_selector.weights + (1,) * len(raw_selector.fallback_members)
            resolved_members = [
                resolve_model_alias_with_effort(
                    member,
                    overrides,
                    model_tier=model_tier,
                    provider_disables=disables,
                )
                for member in values
            ]
            availability = [
                member.valid
                and resolved_target_is_available(
                    member.target,
                    provider_disables=disables,
                )
                for member in resolved_members
            ]
            states = [
                resolved_target_availability(
                    member.target, disables, available=is_available
                )
                for member, is_available in zip(
                    resolved_members, availability, strict=True
                )
            ]
            selected_index = select_model_alias_selector_index(
                override_key,
                raw_selector,
                states,
                consume=consume,
            )
            selected = resolved_members[selected_index]
            provider, model, _target_effort = resolve_model_provider_with_effort(
                selected.target,
                overrides,
                consume=False,
                model_tier=model_tier,
                provider_disables=disables,
            )
            effort = selected.effort
            alias_trail = selected.alias_trail
            selector_mode = raw_selector.mode
            selector_members = tuple(
                ModelAliasSelectorMember(
                    value=value,
                    target=result.target,
                    effort=result.effort,
                    provider=provider_for_resolved_target(result.target)
                    if result.valid
                    else None,
                    available=available,
                    valid=result.valid,
                    selected=index == selected_index,
                    weight=weight,
                    sparing=state == MemberAvailability.SPARING,
                    last_resort=index >= pool_count,
                )
                for index, (value, result, available, weight, state) in enumerate(
                    zip(
                        values,
                        resolved_members,
                        availability,
                        weights,
                        states,
                        strict=True,
                    )
                )
            )
        else:
            provider, model, effort, alias_trail = resolve_model_provider_with_trail(
                raw_value,
                overrides,
                consume=consume,
                model_tier=model_tier,
                provider_disables=disables,
            )
    return LaunchModelSettingSnapshot(
        field=field,
        config_path=f"llm_provider.{field}",
        raw_value=raw_value,
        provider=(
            provider or get_configured_default_provider_name(provider_disables=disables)
        ),
        model=model,
        effort=effort,
        provenance=provenance,
        referenced_alias=referenced_alias,
        override_key=override_key,
        alias_trail=alias_trail,
        override=override,
        selector_mode=selector_mode,
        selector_members=selector_members,
        override_paused_by_provider_disable=paused_disable,
    )


def resolve_default_launch_provider_model(
    model_tier: ModelTier = "large",
    model_alias_overrides: Mapping[str, str] | None = None,
    *,
    consume: bool = False,
    provider_disables: Mapping[str, TemporaryProviderDisable] | None = None,
) -> tuple[str, str]:
    """Return the provider/model selected for a launch with no ``%model``."""
    provider, model, _effort = resolve_default_launch_provider_model_with_effort(
        model_tier,
        model_alias_overrides,
        consume=consume,
        provider_disables=provider_disables,
    )
    return provider, model


def resolve_default_launch_provider_model_with_effort(
    model_tier: ModelTier = "large",
    model_alias_overrides: Mapping[str, str] | None = None,
    *,
    consume: bool = False,
    provider_disables: Mapping[str, TemporaryProviderDisable] | None = None,
) -> tuple[str, str, str | None]:
    """Return provider/model/alias effort for a launch with no ``%model``."""
    provider, model, effort, _alias_trail = (
        resolve_default_launch_provider_model_with_trail(
            model_tier,
            model_alias_overrides,
            consume=consume,
            provider_disables=provider_disables,
        )
    )
    return provider, model, effort


def resolve_default_launch_provider_model_with_trail(
    model_tier: ModelTier = "large",
    model_alias_overrides: Mapping[str, str] | None = None,
    *,
    consume: bool = False,
    provider_disables: Mapping[str, TemporaryProviderDisable] | None = None,
) -> tuple[str, str, str | None, tuple[str, ...]]:
    """Return provider/model/effort plus alias hops for no-``%model`` launch."""
    snapshot = build_launch_model_setting_snapshot(
        DEFAULT_MODEL_FIELD,
        model_alias_overrides,
        model_tier=model_tier,
        consume=consume,
        provider_disables=provider_disables,
    )
    return snapshot.provider, snapshot.model, snapshot.effort, snapshot.alias_trail


def select_epic_land_model_expression(
    explicit_model: str | None,
    *,
    total_phase_count: int,
    threshold: int,
) -> str:
    """Return the configured/explicit model expression for an epic land agent."""
    from sase.core.model_route_facade import select_epic_land_model

    route = select_epic_land_model(
        explicit_model,
        phase_count=total_phase_count,
        threshold=threshold,
        epic_lander_model=get_epic_lander_model(),
        big_epic_lander_model=get_big_epic_lander_model(),
    )
    return route["model"]


def _get_launch_model_field(field: LaunchModelField) -> str:
    value, _provenance = _launch_model_field_value(field)
    return value


def _launch_model_field_value(
    field: LaunchModelField,
    launch_overrides: Mapping[str, str] | None = None,
) -> tuple[str, LaunchModelProvenance]:
    override_key = launch_model_setting_override_key(field)
    if launch_overrides is not None:
        override = launch_overrides.get(override_key)
        if override is not None and override.strip():
            return override.strip(), "launch_override"

    raw = _llm_provider_config().get(field)
    if isinstance(raw, str) and _is_valid_model_expression(raw):
        return raw.strip(), "configured"
    return _FIELD_DEFAULTS[field], "shipped"


def _is_valid_model_expression(value: str) -> bool:
    cleaned = value.strip()
    if not cleaned or any(ord(char) < 32 for char in cleaned):
        return False
    try:
        parse_model_alias_selector(cleaned)
    except ModelAliasSelectorError:
        return False
    return True


def _llm_provider_config() -> dict[str, Any]:
    from . import config

    return config.get_llm_provider_config()


__all__ = [
    "BIG_EPIC_LANDER_MODEL_DEFAULT",
    "BIG_EPIC_LANDER_MODEL_FIELD",
    "DEFAULT_MODEL_DEFAULT",
    "DEFAULT_MODEL_FIELD",
    "EPIC_LANDER_MODEL_DEFAULT",
    "EPIC_LANDER_MODEL_FIELD",
    "LaunchModelField",
    "LaunchModelProvenance",
    "LaunchModelSettingSnapshot",
    "build_launch_model_setting_snapshot",
    "get_big_epic_lander_model",
    "get_default_model",
    "get_epic_lander_model",
    "launch_model_setting_alias",
    "launch_model_setting_override_key",
    "launch_model_setting_override_keys",
    "resolve_default_launch_provider_model",
    "resolve_default_launch_provider_model_with_effort",
    "resolve_default_launch_provider_model_with_trail",
    "select_epic_land_model_expression",
]
