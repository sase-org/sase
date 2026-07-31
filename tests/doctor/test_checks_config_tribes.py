"""Tests for doctor ``ace.tribes`` description checks."""

from __future__ import annotations

import pytest

from sase.doctor.checks_config_common import MAX_DETAIL_ROWS
from sase.doctor.checks_config_tribes import check_config_tribes


def test_tribes_ok_when_every_configured_tribe_has_a_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_config_tribes.load_merged_config",
        lambda: {
            "ace": {
                "tribes": {
                    "default": {"icon": "⌂", "description": "Home tribe."},
                    "epic": {"description": "Epic phase workers."},
                }
            }
        },
    )

    check = check_config_tribes()

    assert check.status == "OK"
    assert check.data == {
        "tribe_count": 2,
        "problem_count": 0,
        "problems": (),
    }
    assert check.details == ()


def test_tribes_warns_on_missing_blank_non_string_and_non_dict_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_config_tribes.load_merged_config",
        lambda: {
            "ace": {
                "tribes": {
                    "missing": {"icon": "X"},
                    "blank": {"description": "   "},
                    "wrong_type": {"description": 7},
                    "not_a_dict": "nope",
                    "documented": {"description": "Fully documented."},
                }
            }
        },
    )

    check = check_config_tribes()

    assert check.status == "WARN"
    assert check.data["tribe_count"] == 5
    assert check.data["problem_count"] == 4
    assert check.summary == "4 configured tribe(s) missing a description"
    assert "ace.tribes.missing.description is missing or blank" in check.details
    assert "ace.tribes.blank.description is missing or blank" in check.details
    assert "ace.tribes.wrong_type.description is missing or blank" in check.details
    assert "ace.tribes.not_a_dict must be an object with a description" in check.details
    assert check.next_steps


def test_tribes_returns_ok_when_no_tribes_are_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_config_tribes.load_merged_config",
        lambda: {"ace": {}},
    )

    check = check_config_tribes()

    assert check.status == "OK"
    assert check.data == {"tribe_count": 0, "problem_count": 0, "problems": ()}


def test_tribes_detail_rows_are_capped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tribes = {f"tribe-{index}": {"icon": "X"} for index in range(MAX_DETAIL_ROWS + 5)}
    monkeypatch.setattr(
        "sase.doctor.checks_config_tribes.load_merged_config",
        lambda: {"ace": {"tribes": tribes}},
    )

    check = check_config_tribes()

    assert check.status == "WARN"
    assert check.data["problem_count"] == MAX_DETAIL_ROWS + 5
    assert len(check.details) == MAX_DETAIL_ROWS
