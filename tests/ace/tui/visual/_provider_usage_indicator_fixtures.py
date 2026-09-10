"""Shared fixtures for the provider usage indicator PNG snapshot scenes."""

from __future__ import annotations

from typing import Any

import pytest

import sase.ace.tui.widgets.alias_overrides_indicator as alias_overrides_indicator
import sase.ace.tui.widgets.current_project_indicator as current_project_indicator
import sase.ace.tui.widgets.llm_override_indicator as llm_override_indicator
import sase.ace.tui.widgets.provider_disables_indicator as provider_disables_indicator
from sase.ace.testing import AcePage
from sase.ace.tui.actions import update_toast
from sase.ace.tui.project_styles import project_accent
from sase.ace.tui.widgets import CurrentProjectIndicator
from sase.ace.tui.widgets.current_project_indicator import _CurrentProjectSnapshot
from sase.current_project import CurrentProject
from sase.llm_provider import TemporaryLLMOverride, TemporaryProviderDisable
from sase.llm_provider.provider_disable import PROVIDER_DISABLE_WIRE_SCHEMA_VERSION
from sase.llm_provider.provider_priority import provider_routing_context_from_parts
from sase.llm_provider.usage.store import provider_usage_project_indicator
from tests._usage_view_helpers import FROZEN_NOW, usage_window


def override(
    provider: str,
    model: str,
    *,
    effort: str | None = None,
) -> TemporaryLLMOverride:
    """Build a temporary launch-model override for the top-bar routing pills."""
    return TemporaryLLMOverride(
        provider=provider,
        model=model,
        raw_model=f"{provider}/{model}",
        created_at=100.0,
        expires_at=None,
        source="test",
        effort=effort,
    )


def disable(provider: str) -> TemporaryProviderDisable:
    """Build a temporary provider disable for the top-bar routing pills."""
    return TemporaryProviderDisable(
        version=PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
        provider=provider,
        created_at=100.0,
        expires_at=None,
        source="test",
    )


def current_project() -> CurrentProject:
    """Return the stable project identity used by every usage indicator scene."""
    return CurrentProject(
        project_key="gh_sase-org__sase",
        display_name="sase",
        origin="project",
        origin_ref="sase",
        workflow_type="gh",
    )


def paint_current_project_chip(page: AcePage) -> CurrentProjectIndicator:
    """Force the project chip to its resolved state so the top bar is stable."""
    project = current_project()
    indicator = page.app.query_one(
        "#current-project-indicator",
        CurrentProjectIndicator,
    )
    indicator._cached_snapshot = _CurrentProjectSnapshot(
        project=project,
        accent=project_accent(project.project_key, among=(project.project_key,)),
    )
    indicator._cached_token = ("visual-usage-indicator",)
    indicator._cached_failed = False
    indicator._apply_content()
    return indicator


def quiet_top_bar(
    monkeypatch: pytest.MonkeyPatch,
    *,
    default_override: TemporaryLLMOverride | None = None,
    alias_overrides: dict[str, TemporaryLLMOverride] | None = None,
    disables: dict[str, TemporaryProviderDisable] | None = None,
    now: float = FROZEN_NOW,
) -> None:
    """Silence every top-bar source except the usage indicator under test."""
    monkeypatch.setattr(
        update_toast, "get_cached_update_status", lambda **_kwargs: None
    )
    monkeypatch.setattr(
        llm_override_indicator,
        "peek_active_temporary_override",
        lambda *a, **k: default_override,
    )
    monkeypatch.setattr(
        alias_overrides_indicator,
        "get_active_alias_overrides",
        lambda: dict(alias_overrides or {}),
    )
    monkeypatch.setattr(
        provider_disables_indicator,
        "peek_provider_routing_context",
        lambda *a, **k: provider_routing_context_from_parts(
            dict(disables or {}),
            None,
            captured_at=now,
        ),
    )
    monkeypatch.setattr(
        provider_disables_indicator,
        "refresh_usage_peek_cache",
        lambda **_kwargs: ((), frozenset()),
    )
    monkeypatch.setattr(
        current_project_indicator,
        "resolve_current_project",
        lambda **_kwargs: current_project(),
    )
    monkeypatch.setattr(
        current_project_indicator,
        "_enabled_project_keys",
        lambda: (current_project().project_key,),
    )


def patch_projection(monkeypatch: pytest.MonkeyPatch, projection: object) -> None:
    """Serve one prebuilt indicator projection to the widget under test."""
    monkeypatch.setattr(
        provider_disables_indicator,
        "cached_usage_indicator_projection",
        lambda **_kwargs: projection,
    )


def weekly_window(
    *,
    key: str,
    label: str,
    used_percent: float,
    remaining_percent: float,
    resets_at: float,
) -> dict[str, Any]:
    """Build a weekly account-scoped window that omits its scope specifier."""
    window = usage_window(
        key=key,
        label=label,
        used_percent=used_percent,
        remaining_percent=remaining_percent,
        resets_at=resets_at,
        applicability={"kind": "account"},
    )
    window["duration_seconds"] = 604_800.0
    return window


def real_projection(*providers: dict[str, Any], now: float) -> object:
    """Project synthetic provider snapshots through the real indicator wire."""
    snapshot = {
        "schema_version": 1,
        "generated_at": now,
        "collection_health": "ok",
        "providers": list(providers),
        "attention": None,
    }
    return provider_usage_project_indicator(
        snapshot,
        eligible_providers=[str(provider["provider"]) for provider in providers],
        now=now,
    )


def scope(
    *,
    kind: str,
    product: str | None = None,
    family: str | None = None,
    model_ids: tuple[str, ...] = (),
    vendor_label: str | None = None,
    vendor_id: str | None = None,
) -> dict[str, Any]:
    """Build an indicator-entry scope record."""
    return {
        "kind": kind,
        "product": product,
        "family": family,
        "model_ids": list(model_ids),
        "vendor_label": vendor_label,
        "vendor_id": vendor_id,
    }


def entry(
    *,
    provider: str = "claude",
    window_key: str = "weekly",
    window_label: str = "Week - all",
    weekly_all: bool = True,
    period_kind: str = "weekly",
    duration_seconds: float | None = 604_800.0,
    entry_scope: dict[str, Any] | None = None,
    remaining_percent: float = 62.0,
    freshness: str = "fresh",
    reset_state: str = "future",
    seconds_until_reset: float | None = 273_840.0,
    resets_at: float | None = FROZEN_NOW + 273_840.0,
    vendor_state: str = "allowed",
    window_attention: str = "none",
    display_attention: str = "none",
    collector_problem: bool = False,
    policy_source: str = "weekly_all",
) -> dict[str, Any]:
    """Build one projected indicator entry directly, for exotic display states."""
    return {
        "provider": provider,
        "context_ref": f"{provider}:default:1",
        "window_key": window_key,
        "window_label": window_label,
        "effective_policy": {"kind": "always"},
        "policy_source": policy_source,
        "weekly_all": weekly_all,
        "period": {"kind": period_kind, "duration_seconds": duration_seconds},
        "scope": entry_scope or scope(kind="all_models"),
        "used_percent": max(0.0, 100.0 - remaining_percent),
        "remaining_percent": remaining_percent,
        "exceeded_by_percent": None,
        "freshness": freshness,
        "reset_state": reset_state,
        "seconds_until_reset": seconds_until_reset,
        "resets_at": resets_at,
        "duration_seconds": duration_seconds,
        "period_start": None,
        "age_seconds": 30.0,
        "observed_at": FROZEN_NOW - 30.0,
        "vendor_state": vendor_state,
        "window_attention": window_attention,
        "display_attention": display_attention,
        "collector_problem": collector_problem,
    }
