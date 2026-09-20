"""Shipped header-indicator defaults for Muse's subscription usage windows."""

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


def _shipped_usage_metrics() -> dict[str, Any]:
    default_config = yaml.safe_load(_DEFAULT_CONFIG.read_text())
    return dict(default_config["llm_provider"]["usage_metrics"])


def _muse_snapshot(
    *, session_remaining: float = 12.0, weekly_remaining: float = 97.0
) -> dict[str, Any]:
    session = usage_window(
        key="session",
        label="Muse 5-hour session",
        used_percent=100.0 - session_remaining,
        remaining_percent=session_remaining,
        resets_at=_FROZEN_NOW + 3_600.0,
        applicability={"kind": "account"},
        vendor_state="allowed",
    )
    weekly = usage_window(
        key="weekly",
        label="Muse weekly all models",
        used_percent=100.0 - weekly_remaining,
        remaining_percent=weekly_remaining,
        resets_at=_FROZEN_NOW + 400_000.0,
        applicability={"kind": "account"},
        vendor_state="allowed",
    )
    # The vendor omits the weekly duration on purpose; classification is the
    # Rust indicator's per-provider allowlist, not a fabricated 604800.
    weekly["duration_seconds"] = None
    weekly["period_start"] = None
    return {
        "schema_version": 1,
        "generated_at": _FROZEN_NOW,
        "collection_health": "ok",
        "providers": [
            usage_provider(
                "muse",
                plan=None,
                account_mode="subscription",
                used_percent=100.0 - session_remaining,
                remaining_percent=session_remaining,
                attention={"kind": "none", "provider": "muse", "window_key": None},
                windows=[session, weekly],
                known_constraints=[],
            )
        ],
        "attention": None,
    }


def project_shipped_muse_weekly_only() -> tuple[dict[str, Any], ...]:
    """Project a low 5-hour and healthy weekly Muse snapshot with shipped defaults."""
    projection = provider_usage_project_indicator(
        _muse_snapshot(session_remaining=12.0, weekly_remaining=97.0),
        indicator=_shipped_usage_metrics()["indicator"],
        eligible_providers=frozenset({"muse"}),
        now=_FROZEN_NOW,
    )
    return tuple(projection.entries)


def test_shipped_defaults_select_muse_weekly_and_reject_session() -> None:
    indicator = _shipped_usage_metrics()["indicator"]
    assert indicator["providers"]["muse"] == {"windows": {"session": "never"}}

    # The 5-hour block is nearly exhausted (12% left), which the generic
    # fallback would surface; the shipped default must still hide it.
    projection = provider_usage_project_indicator(
        _muse_snapshot(session_remaining=12.0, weekly_remaining=97.0),
        indicator=indicator,
        eligible_providers=frozenset({"muse"}),
        now=_FROZEN_NOW,
    )
    assert [(e["provider"], e["window_key"]) for e in projection.entries] == [
        ("muse", "weekly")
    ]
    weekly = projection.entries[0]
    assert weekly["period"]["kind"] == "weekly"
    assert weekly["scope"]["kind"] == "all_models"
    assert weekly["policy_source"] == "weekly_all"
    assert weekly["remaining_percent"] == pytest.approx(97.0)


def test_removing_muse_session_override_restores_generic_fallback() -> None:
    indicator = dict(_shipped_usage_metrics()["indicator"])
    indicator["providers"] = {}
    projection = provider_usage_project_indicator(
        _muse_snapshot(session_remaining=12.0),
        indicator=indicator,
        eligible_providers=frozenset({"muse"}),
        now=_FROZEN_NOW,
    )
    assert {e["window_key"] for e in projection.entries} == {"session", "weekly"}


@pytest.fixture
def _peek_cache() -> Iterator[None]:
    try:
        yield
    finally:
        _clear_usage_peek_cache()


def _install_muse_pipeline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, installed: bool
) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.registry.registered_provider_names", lambda: ["muse"]
    )
    monkeypatch.setattr(
        "sase.llm_provider.registry.model_picker_hidden_provider_names",
        lambda: frozenset(),
    )
    monkeypatch.setattr(
        "sase.llm_provider.registry.get_llm_metadata_payload",
        lambda: {
            "providers": {
                "muse": {
                    "autodetect_cli_name": "muse",
                    "usage_capabilities": {"probe": True},
                }
            }
        },
    )
    usage_metrics = _shipped_usage_metrics()
    usage_metrics["providers"] = {"muse": {"enabled": True}}
    mock_provider_config(monkeypatch, {"usage_metrics": usage_metrics})

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if installed:
        muse = bin_dir / "muse"
        muse.write_text("#!/bin/sh\n")
        muse.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.delenv("SASE_MUSE_PATH", raising=False)

    snapshot = _muse_snapshot()
    monkeypatch.setattr(
        peek_mod,
        "load_provider_usage",
        lambda **_kwargs: type("Read", (), {"snapshot": snapshot})(),
    )


@pytest.mark.usefixtures("_peek_cache")
def test_installed_muse_reaches_header_with_only_the_weekly_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_muse_pipeline(monkeypatch, tmp_path, installed=True)

    _providers, eligible = refresh_usage_peek_cache(now=_FROZEN_NOW)
    projection = cached_usage_indicator_projection(now=_FROZEN_NOW)

    assert eligible == frozenset({"muse"})
    assert [e["window_key"] for e in projection.entries] == ["weekly"]
    segment = build_usage_indicator_segment(
        usage_indicator_groups(projection.entries, dark=True, now=_FROZEN_NOW)
    )
    assert "97%" in segment.plain
    assert "12%" not in segment.plain


@pytest.mark.usefixtures("_peek_cache")
def test_muse_is_not_shown_when_it_is_not_installed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No Muse binary means no eligibility, so a cached observation is inert."""
    _install_muse_pipeline(monkeypatch, tmp_path, installed=False)

    _providers, eligible = refresh_usage_peek_cache(now=_FROZEN_NOW)
    projection = cached_usage_indicator_projection(now=_FROZEN_NOW)

    assert eligible == frozenset()
    assert projection.entries == ()
