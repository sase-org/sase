"""Tests for update-handler installed-version lookups."""

from __future__ import annotations

from sase.main.update_handler import _installed_version


def test_installed_version_returns_none_for_unknown() -> None:
    assert _installed_version("this-distribution-does-not-exist-xyz") is None


def test_installed_version_returns_value_for_known() -> None:
    # ``rich`` is a hard dependency, so it is always importable here.
    assert _installed_version("rich") is not None
