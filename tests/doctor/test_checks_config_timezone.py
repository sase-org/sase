"""Tests for the ``config.timezone`` doctor check."""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest

from sase.config.core import ConfigLayer
from sase.doctor.checks_config_timezone import check_config_timezone


def _layer(name: str, path: str, *, timezone: bool) -> ConfigLayer:
    return ConfigLayer(
        name=name,
        path=path,
        exists=True,
        list_strategy="replace",
        keys=["timezone"] if timezone else [],
    )


def test_ok_when_configured_matches_system(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_config_timezone.get_timezone",
        lambda: ZoneInfo("America/New_York"),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_config_timezone.system_timezone",
        lambda: ZoneInfo("America/New_York"),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_config_timezone.load_config_layers",
        lambda: [_layer("user", "/home/user/.config/sase/sase.yml", timezone=True)],
    )

    check = check_config_timezone()

    assert check.status == "OK"
    assert check.data["configured_timezone"] == "America/New_York"
    assert check.data["system_timezone"] == "America/New_York"
    assert not check.next_steps


def test_warns_and_names_the_overlay_when_diverging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_config_timezone.get_timezone",
        lambda: ZoneInfo("UTC"),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_config_timezone.system_timezone",
        lambda: ZoneInfo("America/New_York"),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_config_timezone.load_config_layers",
        lambda: [
            _layer("user", "/home/user/.config/sase/sase.yml", timezone=False),
            _layer(
                "overlay:sase_extra.yml",
                "/home/user/.config/sase/sase_extra.yml",
                timezone=True,
            ),
        ],
    )

    check = check_config_timezone()

    assert check.status == "WARN"
    assert "/home/user/.config/sase/sase_extra.yml" in check.details[0]
    assert "/home/user/.config/sase/sase_extra.yml" in check.next_steps[0]


def test_ok_when_no_layer_sets_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_config_timezone.get_timezone",
        lambda: ZoneInfo("America/New_York"),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_config_timezone.system_timezone",
        lambda: ZoneInfo("America/New_York"),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_config_timezone.load_config_layers",
        lambda: [_layer("user", "/home/user/.config/sase/sase.yml", timezone=False)],
    )

    check = check_config_timezone()

    assert check.status == "OK"
    assert check.data["source_layer_path"] is None
