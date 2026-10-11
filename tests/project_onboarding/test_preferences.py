"""Tests for onboarding preference load/save round-trips."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.project_onboarding.preferences import (
    Preferences,
    load_preferences,
    preferences_path,
    record_owner_selection,
    record_provider_selection,
    record_visibility_selection,
    save_preferences,
)


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``$SASE_HOME`` at a fresh directory."""

    home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(home))
    return home


class TestPreferences:
    def test_missing_file_loads_defaults(self, isolated_home: Path) -> None:
        del isolated_home

        assert load_preferences() == Preferences()

    def test_corrupt_file_loads_defaults(self, isolated_home: Path) -> None:
        del isolated_home
        path = preferences_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")

        assert load_preferences() == Preferences()

    def test_wrong_shape_loads_defaults(self, isolated_home: Path) -> None:
        del isolated_home
        path = preferences_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('["last_provider"]', encoding="utf-8")

        assert load_preferences() == Preferences()

    def test_round_trip(self, isolated_home: Path) -> None:
        del isolated_home
        prefs = Preferences(
            last_provider="gh",
            last_owner={"gh": "sase-org"},
            last_visibility={"sase-org": "private"},
        )

        save_preferences(prefs)

        assert load_preferences() == prefs

    def test_record_helpers_persist(self, isolated_home: Path) -> None:
        del isolated_home

        record_provider_selection("gh")
        record_owner_selection("gh", "sase-org")
        record_visibility_selection("sase-org", "private")

        assert load_preferences() == Preferences(
            last_provider="gh",
            last_owner={"gh": "sase-org"},
            last_visibility={"sase-org": "private"},
        )

    def test_save_is_atomic(self, isolated_home: Path) -> None:
        del isolated_home

        save_preferences(Preferences(last_provider="git"))

        leftovers = list(preferences_path().parent.glob("*.tmp"))
        assert leftovers == []
        assert load_preferences().last_provider == "git"
