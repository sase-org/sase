"""Shared builders for models-panel provider-routing tests."""

from __future__ import annotations

from datetime import UTC, datetime

from sase.ace.tui.modals.models_panel_provider_state import ProviderRoutingSnapshot
from sase.ace.tui.modals.models_panel_rows import LaunchModelSettingRow
from sase.ace.tui.modals.models_panel_time import ResolvedOverrideUntil
from sase.llm_provider import ProviderRoutingStatus
from sase.llm_provider.config import (
    BIG_EPIC_LANDER_MODEL_FIELD,
    DEFAULT_MODEL_FIELD,
    EPIC_LANDER_MODEL_FIELD,
    LaunchModelSettingSnapshot,
)
from sase.llm_provider.provider_disable import (
    PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
    TemporaryProviderDisable,
)
from tests._models_panel_helpers import make_alias_view


def disable(
    provider: str,
    *,
    expires_at: float | None = None,
    source: str = "test",
) -> TemporaryProviderDisable:
    return TemporaryProviderDisable(
        version=PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
        provider=provider,
        created_at=100.0,
        expires_at=expires_at,
        source=source,
    )


def status(
    provider: str,
    *,
    model_count: int = 2,
    cli_available: bool = True,
    active_disable: TemporaryProviderDisable | None = None,
    hidden: bool = False,
    affected_aliases: tuple[str, ...] = ("medium",),
) -> ProviderRoutingStatus:
    return ProviderRoutingStatus(
        provider=provider,
        model_count=model_count,
        cli_available=cli_available,
        active_disable=active_disable,
        hidden_from_model_pickers=hidden,
        affected_aliases=affected_aliases,
    )


def launch_setting_rows() -> tuple[LaunchModelSettingRow, ...]:
    return tuple(
        LaunchModelSettingRow(
            field=field,
            label=label,
            detail="Used when a launch has no explicit %model directive.",
            snapshot=LaunchModelSettingSnapshot(
                field=field,
                config_path=f"llm_provider.{field}",
                raw_value="@large",
                provider="claude",
                model="opus",
                effort=None,
                provenance="shipped",
                referenced_alias="large",
                override_key=f"setting:{field}",
            ),
        )
        for field, label in (
            (DEFAULT_MODEL_FIELD, "launch model"),
            (EPIC_LANDER_MODEL_FIELD, "epic lander"),
            (BIG_EPIC_LANDER_MODEL_FIELD, "big epic lander"),
        )
    )


def snapshot(
    *statuses: ProviderRoutingStatus,
    disables: dict[str, TemporaryProviderDisable] | None = None,
    alias_views=None,
    launch_model_rows: tuple[LaunchModelSettingRow, ...] = (),
) -> ProviderRoutingSnapshot:
    return ProviderRoutingSnapshot(
        statuses=tuple(statuses),
        provider_disables=disables or {},
        alias_views=tuple(alias_views or (make_alias_view("medium", "role"),)),
        provider_colors={"claude": "#D97757", "codex": "#10A37F"},
        captured_at=100.0,
        launch_model_rows=launch_model_rows,
    )


def until_result() -> ResolvedOverrideUntil:
    return ResolvedOverrideUntil(
        target=datetime.fromtimestamp(5_000.0, UTC),
        expires_at=5_000.0,
        target_display="Ends Thu Jan 1 at 1:23 AM UTC",
        notification_display="Thu Jan 1, 1:23 AM UTC",
        remaining_display="1h",
        timezone_display="UTC",
    )
