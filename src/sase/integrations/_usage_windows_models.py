"""Frozen models for presentation-neutral usage-window projections."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UsageWindowRow:
    key: str
    label: str
    period: str
    duration_seconds: float | None
    scope: str
    scope_family: str | None
    scope_models: tuple[str, ...]
    scope_vendor_label: str | None
    used_percent: float
    remaining_percent: float
    remaining_text: str
    exceeded_by_percent: float | None
    resets_at: float | None
    reset_state: str
    seconds_until_reset: float | None
    freshness: str
    age_seconds: float
    vendor_state: str
    attention: str


@dataclass(frozen=True)
class UsageProviderRow:
    provider: str
    display_name: str
    emoji: str | None
    plan: str | None
    collection_status: str
    status_label: str
    collector_state: str | None
    retry_label: str | None
    last_observed_at: float | None
    windows: tuple[UsageWindowRow, ...]


@dataclass(frozen=True)
class UsageWindowsReport:
    generated_at: float
    collection_enabled: bool
    providers: tuple[UsageProviderRow, ...]
    configured_providers: tuple[str, ...]
    diagnostics: tuple[str, ...]


@dataclass(frozen=True)
class UsageWindowsRefresh:
    started: bool
    operation_ids: tuple[str, ...]
    providers: tuple[str, ...]
    summary: str
