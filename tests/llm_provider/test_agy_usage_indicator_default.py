"""Shipped header-indicator defaults for agy's subscription usage windows."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from sase.ace.tui.widgets._provider_usage_indicator import (
    build_usage_indicator_segment,
    usage_indicator_groups,
)
from sase.llm_provider.usage import peek as peek_mod
from sase.llm_provider.usage.peek import (
    _clear_usage_peek_cache,
    cached_usage_indicator_projection,
    refresh_usage_peek_cache,
)
from sase.llm_provider.usage.store import provider_usage_project_indicator
from tests._usage_view_helpers import usage_provider, usage_window
from tests.llm_provider._provider_config_helpers import mock_provider_config

_FROZEN_NOW = 1_800_000_000.0
_DEFAULT_CONFIG = Path(__file__).parents[2] / "src/sase/default_config.yml"

_GEMINI_IDS = [
    "gemini-3.8-flash-high",
    "gemini-3.7-flash-medium",
    "gemini-3.1-pro-low",
]
_3P_IDS = [
    "claude-sonnet-4-6",
    "claude-opus-4-6-thinking",
    "gpt-oss-120b-medium",
]


def _shipped_usage_metrics() -> dict[str, Any]:
    default_config = yaml.safe_load(_DEFAULT_CONFIG.read_text())
    return dict(default_config["llm_provider"]["usage_metrics"])


def _agy_window(
    *,
    key: str,
    label: str,
    remaining: float,
    reset_in_seconds: float,
    family: str,
    model_ids: list[str],
    duration_seconds: float,
) -> dict[str, Any]:
    window = usage_window(
        key=key,
        label=label,
        used_percent=100.0 - remaining,
        remaining_percent=remaining,
        resets_at=_FROZEN_NOW + reset_in_seconds,
        applicability={
            "kind": "model_family",
            "family": family,
            "model_ids": model_ids,
        },
        vendor_state="allowed",
    )
    window["duration_seconds"] = duration_seconds
    window["period_start"] = _FROZEN_NOW + reset_in_seconds - duration_seconds
    return window


def _agy_snapshot(
    *,
    gemini_weekly_remaining: float = 96.0,
    gemini_5h_remaining: float = 87.0,
    p3_weekly_remaining: float = 100.0,
    p3_5h_remaining: float = 100.0,
) -> dict[str, Any]:
    windows = [
        _agy_window(
            key="gemini-weekly",
            label="Gemini Models Weekly Limit Remaining",
            remaining=gemini_weekly_remaining,
            reset_in_seconds=522_000.0,
            family="gemini",
            model_ids=_GEMINI_IDS,
            duration_seconds=604_800.0,
        ),
        _agy_window(
            key="gemini-5h",
            label="Gemini Models Five Hour Limit Remaining",
            remaining=gemini_5h_remaining,
            reset_in_seconds=17_400.0,
            family="gemini",
            model_ids=_GEMINI_IDS,
            duration_seconds=18_000.0,
        ),
        _agy_window(
            key="3p-weekly",
            label="Claude and GPT models Weekly Limit Remaining",
            remaining=p3_weekly_remaining,
            reset_in_seconds=560_000.0,
            family="3p",
            model_ids=_3P_IDS,
            duration_seconds=604_800.0,
        ),
        _agy_window(
            key="3p-5h",
            label="Claude and GPT models Five Hour Limit Remaining",
            remaining=p3_5h_remaining,
            reset_in_seconds=18_000.0,
            family="3p",
            model_ids=_3P_IDS,
            duration_seconds=18_000.0,
        ),
    ]
    return {
        "schema_version": 1,
        "generated_at": _FROZEN_NOW,
        "collection_health": "ok",
        "providers": [
            usage_provider(
                "agy",
                plan=None,
                account_mode="subscription",
                used_percent=100.0 - gemini_weekly_remaining,
                remaining_percent=gemini_weekly_remaining,
                attention={"kind": "none", "provider": "agy", "window_key": None},
                windows=windows,
                known_constraints=[],
            )
        ],
        "attention": None,
    }


def _project(snapshot: dict[str, Any]) -> Any:
    return provider_usage_project_indicator(
        snapshot,
        indicator=_shipped_usage_metrics()["indicator"],
        eligible_providers=frozenset({"agy"}),
        now=_FROZEN_NOW,
    )


def _render(entries: Any) -> str:
    return build_usage_indicator_segment(
        usage_indicator_groups(entries, dark=True, now=_FROZEN_NOW)
    ).plain


def test_shipped_config_carries_no_active_agy_entry() -> None:
    """agy rides `weekly_all: always` plus the generic default; nothing is pinned."""
    indicator = _shipped_usage_metrics()["indicator"]
    assert "agy" not in indicator["providers"]


def test_live_shaped_snapshot_renders_only_the_unlabeled_weekly_anchor() -> None:
    projection = _project(_agy_snapshot())

    assert [(e["provider"], e["window_key"]) for e in projection.entries] == [
        ("agy", "gemini-weekly")
    ]
    anchor = projection.entries[0]
    assert anchor["policy_source"] == "weekly_all"
    assert anchor["remaining_percent"] == pytest.approx(96.0)

    plain = _render(projection.entries)
    assert "🪐" in plain
    assert "96%" in plain
    assert "87%" not in plain
    assert "family:" not in plain


def test_pressured_gemini_5h_rides_the_generic_default() -> None:
    """At 12% remaining the Gemini 5-hour window appears as `5h/gemini`."""
    projection = _project(_agy_snapshot(gemini_5h_remaining=12.0))

    assert [e["window_key"] for e in projection.entries] == [
        "gemini-weekly",
        "gemini-5h",
    ]
    five_hour = next(e for e in projection.entries if e["window_key"] == "gemini-5h")
    assert five_hour["policy_source"] == "default"

    plain = _render(projection.entries)
    assert "5h/gemini 12%" in plain
    assert "family:" not in plain


def test_low_3p_5h_appears_with_bare_family_name() -> None:
    projection = _project(_agy_snapshot(p3_5h_remaining=12.0))

    assert [e["window_key"] for e in projection.entries] == [
        "gemini-weekly",
        "3p-5h",
    ]

    plain = _render(projection.entries)
    assert "5h/3p 12%" in plain
    assert "family:" not in plain


@pytest.fixture
def _peek_cache() -> Iterator[None]:
    try:
        yield
    finally:
        _clear_usage_peek_cache()


def _install_agy_pipeline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, installed: bool
) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.registry.registered_provider_names", lambda: ["agy"]
    )
    monkeypatch.setattr(
        "sase.llm_provider.registry.model_picker_hidden_provider_names",
        lambda: frozenset(),
    )
    monkeypatch.setattr(
        "sase.llm_provider.registry.get_llm_metadata_payload",
        lambda: {
            "providers": {
                "agy": {
                    "autodetect_cli_name": "agy",
                    "usage_capabilities": {"probe": True},
                }
            }
        },
    )
    usage_metrics = _shipped_usage_metrics()
    usage_metrics["providers"] = {"agy": {"enabled": True}}
    mock_provider_config(monkeypatch, {"usage_metrics": usage_metrics})

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if installed:
        agy = bin_dir / "agy"
        agy.write_text("#!/bin/sh\n")
        agy.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.delenv("SASE_AGY_PATH", raising=False)

    snapshot = _agy_snapshot()
    monkeypatch.setattr(
        peek_mod,
        "load_provider_usage",
        lambda **_kwargs: type("Read", (), {"snapshot": snapshot})(),
    )


@pytest.mark.usefixtures("_peek_cache")
def test_installed_agy_reaches_header_with_only_the_weekly_anchor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_agy_pipeline(monkeypatch, tmp_path, installed=True)

    _providers, eligible = refresh_usage_peek_cache(now=_FROZEN_NOW)
    projection = cached_usage_indicator_projection(now=_FROZEN_NOW)

    assert eligible == frozenset({"agy"})
    assert [e["window_key"] for e in projection.entries] == ["gemini-weekly"]
    segment = build_usage_indicator_segment(
        usage_indicator_groups(projection.entries, dark=True, now=_FROZEN_NOW)
    )
    assert "🪐" in segment.plain
    assert "96%" in segment.plain
    assert "87%" not in segment.plain
    assert "family:" not in segment.plain


@pytest.mark.usefixtures("_peek_cache")
def test_agy_is_not_shown_when_it_is_not_installed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No agy binary means no eligibility, so a cached observation is inert."""
    _install_agy_pipeline(monkeypatch, tmp_path, installed=False)

    _providers, eligible = refresh_usage_peek_cache(now=_FROZEN_NOW)
    projection = cached_usage_indicator_projection(now=_FROZEN_NOW)

    assert eligible == frozenset()
    assert projection.entries == ()
