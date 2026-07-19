"""Tests for persisted Admin Center tab loading and saving."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sase.ace.admin_center_tab import (
    load_admin_center_tab,
    save_admin_center_tab,
)

_VALID_TABS = (
    "config",
    "logs",
    "projects",
    "statistics",
    "tasks",
    "updates",
    "xprompts",
)


def test_load_missing_file_returns_none(tmp_path: Path) -> None:
    tab_file = tmp_path / "admin_center_tab.json"
    with patch("sase.ace.admin_center_tab._ADMIN_CENTER_TAB_FILE", tab_file):
        assert load_admin_center_tab(_VALID_TABS) is None


def test_load_malformed_json_returns_none(tmp_path: Path) -> None:
    tab_file = tmp_path / "admin_center_tab.json"
    tab_file.write_text("{not valid json", encoding="utf-8")
    with patch("sase.ace.admin_center_tab._ADMIN_CENTER_TAB_FILE", tab_file):
        assert load_admin_center_tab(_VALID_TABS) is None


def test_load_non_object_returns_none(tmp_path: Path) -> None:
    tab_file = tmp_path / "admin_center_tab.json"
    tab_file.write_text('"logs"', encoding="utf-8")
    with patch("sase.ace.admin_center_tab._ADMIN_CENTER_TAB_FILE", tab_file):
        assert load_admin_center_tab(_VALID_TABS) is None


def test_load_unknown_tab_returns_none(tmp_path: Path) -> None:
    tab_file = tmp_path / "admin_center_tab.json"
    tab_file.write_text('{"active_tab": "bogus"}', encoding="utf-8")
    with patch("sase.ace.admin_center_tab._ADMIN_CENTER_TAB_FILE", tab_file):
        assert load_admin_center_tab(_VALID_TABS) is None


def test_load_legacy_telemetry_tab_migrates_to_statistics(tmp_path: Path) -> None:
    tab_file = tmp_path / "admin_center_tab.json"
    tab_file.write_text('{"active_tab": "telemetry"}', encoding="utf-8")
    with patch("sase.ace.admin_center_tab._ADMIN_CENTER_TAB_FILE", tab_file):
        assert load_admin_center_tab(_VALID_TABS) == "statistics"


def test_load_non_string_tab_returns_none(tmp_path: Path) -> None:
    tab_file = tmp_path / "admin_center_tab.json"
    tab_file.write_text('{"active_tab": 5}', encoding="utf-8")
    with patch("sase.ace.admin_center_tab._ADMIN_CENTER_TAB_FILE", tab_file):
        assert load_admin_center_tab(_VALID_TABS) is None


def test_valid_tab_round_trips(tmp_path: Path) -> None:
    tab_file = tmp_path / "admin_center_tab.json"
    with patch("sase.ace.admin_center_tab._ADMIN_CENTER_TAB_FILE", tab_file):
        assert save_admin_center_tab("updates", _VALID_TABS) is True
        assert load_admin_center_tab(_VALID_TABS) == "updates"


def test_save_rejects_unknown_tab_without_corrupting_state(tmp_path: Path) -> None:
    tab_file = tmp_path / "admin_center_tab.json"
    with patch("sase.ace.admin_center_tab._ADMIN_CENTER_TAB_FILE", tab_file):
        assert save_admin_center_tab("logs", _VALID_TABS) is True
        # An unknown tab must be rejected and must not overwrite the file.
        assert save_admin_center_tab("bogus", _VALID_TABS) is False
        assert load_admin_center_tab(_VALID_TABS) == "logs"


def test_save_creates_parent_directory(tmp_path: Path) -> None:
    tab_file = tmp_path / "nested" / "admin_center_tab.json"
    with patch("sase.ace.admin_center_tab._ADMIN_CENTER_TAB_FILE", tab_file):
        assert save_admin_center_tab("tasks", _VALID_TABS) is True
        assert load_admin_center_tab(_VALID_TABS) == "tasks"


def test_stale_tab_after_removal_falls_back_to_none(tmp_path: Path) -> None:
    """A tab that was valid when saved but later removed reads back as None."""
    tab_file = tmp_path / "admin_center_tab.json"
    with patch("sase.ace.admin_center_tab._ADMIN_CENTER_TAB_FILE", tab_file):
        assert save_admin_center_tab("xprompts", _VALID_TABS) is True
        shrunk = ("config", "logs")
        assert load_admin_center_tab(shrunk) is None
