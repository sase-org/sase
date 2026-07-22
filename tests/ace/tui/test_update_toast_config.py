"""Tests for ACE update toast configuration."""

from __future__ import annotations

import pytest

from sase.ace.tui.actions import update_toast


def test_load_update_toast_config_defaults_to_ten_minutes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(update_toast, "load_merged_config", dict)

    config = update_toast._load_update_toast_config()

    assert config.startup_toast is True
    assert config.indicator is True
    assert config.post_update_toast_diffstat is True
    assert config.post_update_toast_commits is True
    assert config.post_update_toast_max_commits == 5
    assert config.check_ttl_seconds == 600.0
    assert config.recompute_interval_seconds == 3600.0
    assert config.incoming_commits_enabled is True
    assert config.startup_toast_max_commits == 20


def test_load_update_toast_config_post_update_diffstat_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        update_toast,
        "load_merged_config",
        lambda: {"ace": {"updates": {"post_update_toast_diffstat": False}}},
    )

    config = update_toast._load_update_toast_config()

    assert config.post_update_toast_diffstat is False


def test_load_update_toast_config_post_update_commit_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        update_toast,
        "load_merged_config",
        lambda: {
            "ace": {
                "updates": {
                    "post_update_toast_commits": False,
                    "post_update_toast_max_commits": 2,
                }
            }
        },
    )

    config = update_toast._load_update_toast_config()

    assert config.post_update_toast_commits is False
    assert config.post_update_toast_max_commits == 2


def test_load_update_toast_config_indicator_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        update_toast,
        "load_merged_config",
        lambda: {"ace": {"updates": {"indicator": False}}},
    )

    config = update_toast._load_update_toast_config()

    assert config.indicator is False


def test_load_update_toast_config_incoming_commits_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        update_toast,
        "load_merged_config",
        lambda: {
            "ace": {
                "updates": {
                    "startup_toast_max_commits": 8,
                    "incoming_commits": {"enabled": False},
                }
            }
        },
    )

    config = update_toast._load_update_toast_config()

    assert config.incoming_commits_enabled is False
    assert config.startup_toast_max_commits == 8


def test_load_update_toast_config_minutes_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        update_toast,
        "load_merged_config",
        lambda: {"ace": {"updates": {"check_ttl_minutes": 5}}},
    )

    config = update_toast._load_update_toast_config()

    assert config.check_ttl_seconds == 300.0


def test_load_update_toast_config_legacy_hours_still_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        update_toast,
        "load_merged_config",
        lambda: {"ace": {"updates": {"check_ttl_hours": 2}}},
    )

    config = update_toast._load_update_toast_config()

    assert config.check_ttl_seconds == 7200.0


def test_load_update_toast_config_minutes_take_precedence_over_hours(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        update_toast,
        "load_merged_config",
        lambda: {"ace": {"updates": {"check_ttl_minutes": 10, "check_ttl_hours": 24}}},
    )

    config = update_toast._load_update_toast_config()

    assert config.check_ttl_seconds == 600.0


def test_load_update_toast_config_recompute_interval_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        update_toast,
        "load_merged_config",
        lambda: {"ace": {"updates": {"recompute_interval_minutes": 30}}},
    )

    config = update_toast._load_update_toast_config()

    assert config.recompute_interval_seconds == 1800.0


@pytest.mark.parametrize(
    ("minutes", "expected_seconds"),
    [(30, 1800.0), (0.25, 15.0)],
)
def test_resolve_check_interval_seconds_converts_positive_minutes(
    minutes: object,
    expected_seconds: float,
) -> None:
    assert (
        update_toast.resolve_check_interval_seconds({"check_interval_minutes": minutes})
        == expected_seconds
    )


@pytest.mark.parametrize(
    "value",
    [
        None,
        "not-a-number",
        "30",
        True,
        False,
        float("nan"),
        float("inf"),
        float("-inf"),
        0,
        -1,
        10**400,
        [],
        {},
    ],
)
def test_resolve_check_interval_seconds_falls_back_for_invalid_values(
    value: object,
) -> None:
    assert (
        update_toast.resolve_check_interval_seconds({"check_interval_minutes": value})
        == 600.0
    )


def test_resolve_check_interval_seconds_falls_back_when_missing() -> None:
    assert update_toast.resolve_check_interval_seconds({}) == 600.0
