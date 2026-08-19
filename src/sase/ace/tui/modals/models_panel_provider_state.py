"""Provider-routing state shared by the Models panel and its modal."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
from typing import Literal

from sase.bead.config import (
    DEFAULT_BIG_EPIC_PHASE_THRESHOLD,
    get_big_epic_phase_threshold,
)
from sase.llm_provider import (
    AliasView,
    ProviderRoutingStatus,
    TemporaryProviderDisable,
    build_alias_views,
    build_provider_routing_statuses,
    get_active_provider_disables,
)
from sase.llm_provider.registry import provider_cli_status_color_map
from sase.xprompt.effort import split_model_effort

from .models_panel_duration import format_remaining
from .models_panel_rows import (
    BigEpicPhaseThresholdSettingRow,
    LaunchModelSettingRow,
    build_launch_model_setting_rows,
)


@dataclass(frozen=True)
class ProviderRoutingSnapshot:
    """One immutable provider-routing snapshot for UI rendering."""

    statuses: tuple[ProviderRoutingStatus, ...]
    provider_disables: Mapping[str, TemporaryProviderDisable]
    alias_views: tuple[AliasView, ...]
    provider_colors: Mapping[str, str]
    captured_at: float
    launch_model_rows: tuple[
        LaunchModelSettingRow | BigEpicPhaseThresholdSettingRow, ...
    ] = ()
    big_epic_phase_threshold: int = DEFAULT_BIG_EPIC_PHASE_THRESHOLD

    @property
    def visible_statuses(self) -> tuple[ProviderRoutingStatus, ...]:
        """Return human-facing providers, excluding hidden/test-only entries."""
        return tuple(
            status for status in self.statuses if not status.hidden_from_model_pickers
        )


@dataclass(frozen=True)
class ProviderWriteOutcome:
    """Result returned by a provider-routing write worker."""

    action: Literal["disable", "enable"]
    provider: str
    changed: bool
    snapshot: ProviderRoutingSnapshot | None
    error: str | None = None
    mode: str | None = None
    previous_mode: str | None = None


def load_provider_routing_snapshot(
    now: float | None = None,
) -> ProviderRoutingSnapshot:
    """Load provider routing, disables, alias views, and colors together."""
    captured_at = (
        max(float(now), 0.000001)
        if now is not None and math.isfinite(now) and now >= 0.0
        else _now()
    )
    disables = get_active_provider_disables(captured_at)
    statuses = build_provider_routing_statuses(disables)
    views = tuple(build_alias_views(now=captured_at, provider_disables=disables))
    threshold = get_big_epic_phase_threshold()
    launch_rows = build_launch_model_setting_rows(
        provider_disables=dict(disables),
        big_epic_phase_threshold=threshold,
    )
    return ProviderRoutingSnapshot(
        statuses=statuses,
        provider_disables=dict(disables),
        alias_views=views,
        launch_model_rows=launch_rows,
        big_epic_phase_threshold=threshold,
        provider_colors=provider_cli_status_color_map(),
        captured_at=captured_at,
    )


def _now() -> float:
    from .models_panel_duration import now

    return now()


def remaining_label(
    disable: TemporaryProviderDisable,
    *,
    now: float,
    include_left: bool = True,
) -> str:
    """Return a human-readable remaining-time label for a provider disable."""
    if disable.expires_at is None:
        return "until cleared"
    suffix = " left" if include_left else ""
    return f"{format_remaining(disable.expires_at - now)}{suffix}"


def active_disable(
    disable: TemporaryProviderDisable | None,
    *,
    now: float,
) -> TemporaryProviderDisable | None:
    """Return the disable if it is still in effect at ``now``."""
    if disable is None:
        return None
    if disable.expires_at is not None and now >= disable.expires_at:
        return None
    return disable


def provider_disable_route_key(
    disables: Mapping[str, TemporaryProviderDisable],
) -> tuple[tuple[str, float | None, str], ...]:
    """Return the routing-relevant shape of a provider-disable snapshot."""
    return tuple(
        sorted(
            (provider, disable.expires_at, disable.mode)
            for provider, disable in disables.items()
        )
    )


def disabled_explicit_provider_message(
    value: str,
    disables: Mapping[str, TemporaryProviderDisable],
    *,
    now: float,
) -> str | None:
    """Return feedback for a free-form explicit target using a disabled provider."""
    target, _effort = split_model_effort(value.strip())
    if target.startswith("@") or "/" not in target:
        return None
    provider, _model = target.split("/", 1)
    if not provider:
        return None
    disable = active_disable(disables.get(provider), now=now)
    if disable is None or disable.is_soft:
        return None
    return (
        f"{provider.upper()} is temporarily disabled "
        f"{remaining_label(disable, now=now)}; choose another provider "
        "or enable it in Provider Routing"
    )


def soft_explicit_provider_note(
    value: str,
    disables: Mapping[str, TemporaryProviderDisable],
    *,
    now: float,
) -> str | None:
    """Return an informational note for an explicit soft-disabled target."""
    target, _effort = split_model_effort(value.strip())
    if target.startswith("@") or "/" not in target:
        return None
    provider, _model = target.split("/", 1)
    if not provider:
        return None
    disable = active_disable(disables.get(provider), now=now)
    if disable is None or not disable.is_soft:
        return None
    return (
        f"{provider.upper()} is soft-disabled "
        f"{remaining_label(disable, now=now)}; explicit targets still run"
    )
