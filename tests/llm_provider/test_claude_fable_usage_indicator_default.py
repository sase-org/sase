"""Shipped header-indicator defaults for Claude's Fable usage window."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

from sase.ace.tui.widgets._provider_usage_indicator import (
    build_usage_indicator_segment,
    usage_indicator_groups,
)
from sase.llm_provider.usage.store import provider_usage_project_indicator
from tests._usage_view_helpers import usage_provider, usage_window

_FROZEN_NOW = 1_800_000_000.0
_DEFAULT_CONFIG = Path(__file__).parents[2] / "src/sase/default_config.yml"
FABLE_KEY = "weekly:claude-fable-5"


def _shipped_usage_metrics() -> dict[str, Any]:
    default_config = yaml.safe_load(_DEFAULT_CONFIG.read_text())
    return dict(default_config["llm_provider"]["usage_metrics"])


def _claude_snapshot(
    *, fable_remaining: float, weekly_remaining: float = 62.0
) -> dict[str, Any]:
    weekly = usage_window(
        key="weekly",
        label="Claude weekly all models",
        used_percent=100.0 - weekly_remaining,
        remaining_percent=weekly_remaining,
        resets_at=_FROZEN_NOW + 400_000.0,
        applicability={"kind": "product", "product": "claude"},
        vendor_state="allowed",
    )
    fable = usage_window(
        key=FABLE_KEY,
        label="Claude weekly Fable",
        used_percent=100.0 - fable_remaining,
        remaining_percent=fable_remaining,
        resets_at=_FROZEN_NOW + 400_000.0,
        applicability={"kind": "models", "model_ids": ["claude-fable-5"]},
        vendor_state="allowed",
    )
    # The real collector emits no weekly duration (see parse_usage_windows in
    # _claude_support_windows.py); a present short duration would fail the
    # Rust indicator's weekly classification short-circuit.
    weekly["duration_seconds"] = None
    weekly["period_start"] = None
    fable["duration_seconds"] = None
    fable["period_start"] = None
    return {
        "schema_version": 1,
        "generated_at": _FROZEN_NOW,
        "collection_health": "ok",
        "providers": [
            usage_provider(
                "claude",
                plan="Max",
                account_mode="subscription",
                used_percent=100.0 - weekly_remaining,
                remaining_percent=weekly_remaining,
                attention={"kind": "none", "provider": "claude", "window_key": None},
                windows=[weekly, fable],
                known_constraints=[],
            )
        ],
        "attention": None,
    }


def _project(fable_remaining: float, indicator: dict[str, Any]):  # type: ignore[no-untyped-def]
    return provider_usage_project_indicator(
        _claude_snapshot(fable_remaining=fable_remaining),
        indicator=indicator,
        eligible_providers=frozenset({"claude"}),
        now=_FROZEN_NOW,
    )


def test_shipped_config_does_not_pin_fable() -> None:
    """The shipped indicator config carries no exact Fable override."""
    indicator = _shipped_usage_metrics()["indicator"]
    assert "claude" not in indicator["providers"]


def test_fable_hidden_at_healthy_and_boundary_remaining() -> None:
    """Fable stays out of the header at healthy capacity and at exactly 20%."""
    indicator = _shipped_usage_metrics()["indicator"]
    for remaining in (100.0, 21.0, 20.0):
        projection = _project(remaining, indicator)
        assert [e["window_key"] for e in projection.entries] == ["weekly"]


def test_fable_shown_via_generic_default_when_low() -> None:
    """Below the threshold Fable rides the generic default, not an override."""
    indicator = _shipped_usage_metrics()["indicator"]
    projection = _project(19.0, indicator)
    assert [e["window_key"] for e in projection.entries] == ["weekly", FABLE_KEY]
    fable = next(e for e in projection.entries if e["window_key"] == FABLE_KEY)
    assert fable["policy_source"] == "default"


def test_user_can_restore_always_visible_fable() -> None:
    """An explicit exact-key override pins Fable back to always-visible."""
    indicator = copy.deepcopy(_shipped_usage_metrics()["indicator"])
    indicator["providers"] = {
        **indicator.get("providers", {}),
        "claude": {"windows": {FABLE_KEY: "always"}},
    }
    projection = _project(100.0, indicator)
    assert [e["window_key"] for e in projection.entries] == ["weekly", FABLE_KEY]
    fable = next(e for e in projection.entries if e["window_key"] == FABLE_KEY)
    assert fable["policy_source"] == "window"


def test_header_text_follows_fable_selection() -> None:
    """The rendered header names Fable only when it is selected."""
    shipped = _shipped_usage_metrics()["indicator"]
    hidden = _project(100.0, shipped)
    segment = build_usage_indicator_segment(
        usage_indicator_groups(hidden.entries, dark=True, now=_FROZEN_NOW)
    )
    assert "fable" not in segment.plain

    restored = copy.deepcopy(shipped)
    restored["providers"] = {
        **restored.get("providers", {}),
        "claude": {"windows": {FABLE_KEY: "always"}},
    }
    shown = _project(100.0, restored)
    segment = build_usage_indicator_segment(
        usage_indicator_groups(shown.entries, dark=True, now=_FROZEN_NOW)
    )
    assert "fable" in segment.plain
