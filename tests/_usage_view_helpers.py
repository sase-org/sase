"""Shared fixtures for ACE Providers · Usage view tests."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.ace.tui.modals.models_panel_usage_state import ProviderUsageViewSnapshot
from sase.llm_provider.usage.store import ProviderUsageStoreDiagnostic

FROZEN_NOW = 1_800_000_000.0


def usage_window(
    *,
    key: str = "shared",
    label: str = "Shared 5h",
    used_percent: float | None = 87.5,
    remaining_percent: float | None = 12.5,
    resets_at: float | None = FROZEN_NOW + 7_200.0,
    reset_passed: bool = False,
    age_seconds: float = 30.0,
    freshness: str = "fresh",
    vendor_state: str = "warning",
    source: str = "probe",
    applicability: Mapping[str, Any] | None = None,
    exceeded_by_percent: float | None = None,
    observed_at: float = FROZEN_NOW - 30.0,
) -> dict[str, Any]:
    return {
        "age_seconds": age_seconds,
        "applicability": applicability or {"kind": "models", "model_ids": ["gpt-5"]},
        "duration_seconds": 18_000.0,
        "exceeded_by_percent": exceeded_by_percent,
        "freshness": freshness,
        "key": key,
        "label": label,
        "observed_at": observed_at,
        "period_start": FROZEN_NOW - 18_000.0,
        "remaining_percent": remaining_percent,
        "reset_passed": reset_passed,
        "resets_at": resets_at,
        "source": source,
        "used_percent": used_percent,
        "vendor_state": vendor_state,
    }


def usage_provider(
    name: str = "codex",
    *,
    collection_status: str = "ok",
    collection_reason: str | None = None,
    plan: str | None = "Plus",
    account_mode: str | None = "chatgpt",
    diagnostic: str | None = None,
    attention: Mapping[str, Any] | None = None,
    used_percent: float | None = 87.5,
    remaining_percent: float | None = 12.5,
    freshness: str = "fresh",
    scope: Mapping[str, Any] | None = None,
    windows: list[dict[str, Any]] | None = None,
    last_attempt_at: float | None = FROZEN_NOW,
    last_full_observation_at: float | None = FROZEN_NOW,
) -> dict[str, Any]:
    summary = (
        None
        if used_percent is None and remaining_percent is None
        else {
            "completeness": "complete",
            "freshness": freshness,
            "limiting_window_keys": ["shared"],
            "remaining_percent": remaining_percent,
            "scope": scope or {"kind": "models", "model_ids": ["gpt-5"]},
            "used_percent": used_percent,
        }
    )
    return {
        "account_generation": 1,
        "account_mode": account_mode,
        "attention": attention,
        "collection_reason": collection_reason,
        "collection_status": collection_status,
        "completeness": "complete",
        "context_ref": f"{name}:default:1",
        "diagnostic": diagnostic,
        "known_constraints": [],
        "last_attempt_at": last_attempt_at,
        "last_full_observation_at": last_full_observation_at,
        "plan": plan,
        "provider": name,
        "summary": summary,
        "windows": windows if windows is not None else [usage_window()],
    }


def usage_view_snapshot(
    *providers: Mapping[str, Any],
    diagnostics: tuple[ProviderUsageStoreDiagnostic, ...] = (),
    captured_at: float = FROZEN_NOW,
    load_error: str | None = None,
) -> ProviderUsageViewSnapshot:
    return ProviderUsageViewSnapshot(
        providers=tuple(providers),
        diagnostics=diagnostics,
        captured_at=captured_at,
        load_error=load_error,
    )
