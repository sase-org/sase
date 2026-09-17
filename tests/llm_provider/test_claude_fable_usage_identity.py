"""Claude Fable provider-usage identity regressions."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.widgets._provider_usage_indicator import (
    build_usage_indicator_segment,
    usage_indicator_groups,
)
from sase.llm_provider.usage.store import (
    load_provider_usage,
    provider_usage_project_indicator,
    provider_usage_state_path,
)
from tests._usage_view_helpers import FROZEN_NOW

WEEK_SECONDS = 7.0 * 24.0 * 60.0 * 60.0
FABLE_ALIAS_KEY = "window:seven-day-overage-included"
FABLE_CANONICAL_KEY = "weekly:claude-fable-5"


def _window(
    *,
    key: str,
    label: str,
    used_percent: float,
    observed_at: float,
) -> dict[str, Any]:
    is_fable = key in {FABLE_ALIAS_KEY, FABLE_CANONICAL_KEY}
    return {
        "key": key,
        "label": label,
        "used_percent": used_percent,
        "resets_at": FROZEN_NOW + WEEK_SECONDS,
        "duration_seconds": WEEK_SECONDS,
        "period_start": FROZEN_NOW,
        "applicability": (
            {"kind": "models", "model_ids": ["claude-fable-5"]}
            if key == FABLE_CANONICAL_KEY
            else {
                "kind": "unknown",
                "vendor_label": "seven_day_overage_included",
                "vendor_id": "seven-day-overage-included",
            }
            if is_fable
            else {"kind": "product", "product": "claude", "model_ids": []}
        ),
        "observed_at": observed_at,
        "source": "stream_event" if key == FABLE_ALIAS_KEY else "probe",
        "vendor_state": "unknown" if key == FABLE_ALIAS_KEY else "allowed",
    }


def _observation(
    *,
    ordering_token: float,
    windows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "provider": "claude",
        "context_id": "ctx-claude",
        "account_generation": 1,
        "ordering_token": ordering_token,
        "received_at": ordering_token + 1.0,
        "source": "stream_event",
        "outcome": "ok",
        "reason_code": None,
        "diagnostic": None,
        "completeness": "complete",
        "authoritative_empty": False,
        "account_mode": "subscription",
        "plan": "Max",
        "windows": list(windows),
    }


def _write_legacy_store(path: Path, *, fable_remaining_percent: float) -> None:
    weekly = _window(
        key="weekly",
        label="Claude weekly all models",
        used_percent=88.0,
        observed_at=FROZEN_NOW - 60.0,
    )
    canonical = _window(
        key=FABLE_CANONICAL_KEY,
        label="Claude weekly Fable",
        used_percent=80.0,
        observed_at=FROZEN_NOW - 50.0,
    )
    alias = _window(
        key=FABLE_ALIAS_KEY,
        label="Claude seven_day_overage_included",
        used_percent=100.0 - fable_remaining_percent,
        observed_at=FROZEN_NOW - 20.0,
    )
    raw = {
        "version": 1,
        "providers": {
            "claude": {
                "version": 1,
                "provider": "claude",
                "context_id": "ctx-claude",
                "account_generation": 1,
                "last_attempt": _observation(
                    ordering_token=FROZEN_NOW - 20.0,
                    windows=[weekly, canonical, alias],
                ),
                "last_attempt_ordering_token": FROZEN_NOW - 20.0,
                "last_attempt_received_at": FROZEN_NOW - 19.0,
                "last_full_observation_at": FROZEN_NOW - 20.0,
                "last_full_ordering_token": FROZEN_NOW - 20.0,
                "windows": {
                    "weekly": {
                        "window": weekly,
                        "ordering_token": FROZEN_NOW - 60.0,
                        "received_at": FROZEN_NOW - 59.0,
                    },
                    FABLE_CANONICAL_KEY: {
                        "window": canonical,
                        "ordering_token": FROZEN_NOW - 50.0,
                        "received_at": FROZEN_NOW - 49.0,
                    },
                    FABLE_ALIAS_KEY: {
                        "window": alias,
                        "ordering_token": FROZEN_NOW - 20.0,
                        "received_at": FROZEN_NOW - 19.0,
                    },
                },
                "tombstones": {},
            }
        },
        "reservations": {},
        "schedules": {},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, indent=2), encoding="utf-8")


@pytest.mark.parametrize("remaining_percent", [19.0, 20.0, 21.0])
def test_legacy_claude_fable_cache_renders_one_canonical_entry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    remaining_percent: float,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    state_path = provider_usage_state_path()
    _write_legacy_store(state_path, fable_remaining_percent=remaining_percent)
    before = state_path.read_bytes()

    read = load_provider_usage(now=FROZEN_NOW)

    assert state_path.read_bytes() == before
    provider = read.snapshot["providers"][0]
    window_keys = [window["key"] for window in provider["windows"]]
    assert window_keys == ["weekly", FABLE_CANONICAL_KEY]
    fable_window = provider["windows"][1]
    assert fable_window["remaining_percent"] == remaining_percent
    assert fable_window["applicability"] == {
        "kind": "models",
        "model_ids": ["claude-fable-5"],
    }

    projection = provider_usage_project_indicator(
        read.snapshot,
        indicator={
            "default": {"below_remaining_percent": 20},
            "weekly_all": "always",
            "providers": {"claude": {"windows": {FABLE_CANONICAL_KEY: "always"}}},
        },
        eligible_providers=["claude"],
        now=FROZEN_NOW,
    )
    keys = [entry["window_key"] for entry in projection.entries]
    assert keys == ["weekly", FABLE_CANONICAL_KEY]
    segment = build_usage_indicator_segment(
        usage_indicator_groups(projection.entries, dark=True, now=FROZEN_NOW)
    )
    assert f"fable {remaining_percent:.0f}%" in segment.plain
    assert "seven_day_overage_included" not in segment.plain
    assert "scope?" not in segment.plain

    hidden = provider_usage_project_indicator(
        read.snapshot,
        indicator={
            "default": "always",
            "weekly_all": "always",
            "providers": {"claude": {"windows": {FABLE_CANONICAL_KEY: "never"}}},
        },
        eligible_providers=["claude"],
        now=FROZEN_NOW,
    )
    assert [entry["window_key"] for entry in hidden.entries] == ["weekly"]
