"""`tool_runs.soft_ceiling` resolution (`SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS`)."""

from __future__ import annotations

import pytest

from sase.config.tools import get_tool_runs_soft_ceiling_seconds


def _config(default: object = "", providers: object | None = None) -> dict:
    section: dict = {"default": default}
    if providers is not None:
        section["providers"] = providers
    return {"tool_runs": {"soft_ceiling": section}}


def test_provider_entry_wins_over_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.config.core.load_merged_config",
        lambda: _config(default="20m", providers={"muse": "90s"}),
    )
    assert get_tool_runs_soft_ceiling_seconds("muse") == 90
    assert get_tool_runs_soft_ceiling_seconds("claude") == 1200


def test_default_used_when_no_provider_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.config.core.load_merged_config",
        lambda: _config(default="1h", providers={}),
    )
    assert get_tool_runs_soft_ceiling_seconds("muse") == 3600
    assert get_tool_runs_soft_ceiling_seconds(None) == 3600


def test_none_when_nothing_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.config.core.load_merged_config",
        lambda: _config(default="", providers={}),
    )
    assert get_tool_runs_soft_ceiling_seconds("muse") is None
    assert get_tool_runs_soft_ceiling_seconds(None) is None


def test_empty_provider_entry_falls_through_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.config.core.load_merged_config",
        lambda: _config(default="20m", providers={"muse": ""}),
    )
    assert get_tool_runs_soft_ceiling_seconds("muse") == 1200


def test_bare_seconds_and_hour_suffixes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.config.core.load_merged_config",
        lambda: _config(default="90", providers={"muse": "1h"}),
    )
    assert get_tool_runs_soft_ceiling_seconds("claude") == 90
    assert get_tool_runs_soft_ceiling_seconds("muse") == 3600


@pytest.mark.parametrize("raw", ["bogus", "0", "-5s", "0s"])
def test_malformed_default_is_ignored(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setattr(
        "sase.config.core.load_merged_config",
        lambda: _config(default=raw, providers={}),
    )
    assert get_tool_runs_soft_ceiling_seconds("muse") is None


def test_malformed_provider_entry_falls_through_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.config.core.load_merged_config",
        lambda: _config(default="20m", providers={"muse": "bogus"}),
    )
    assert get_tool_runs_soft_ceiling_seconds("muse") == 1200


def test_non_string_values_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.config.core.load_merged_config",
        lambda: _config(default=1200, providers={"muse": 90}),
    )
    assert get_tool_runs_soft_ceiling_seconds("muse") is None
    assert get_tool_runs_soft_ceiling_seconds("claude") is None


def test_missing_section_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.config.core.load_merged_config", lambda: {"tool_runs": {}}
    )
    assert get_tool_runs_soft_ceiling_seconds("muse") is None
