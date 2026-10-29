"""Suite-wide terminal pin so rendering tests ignore ambient TERM=dumb."""

from __future__ import annotations

import os

import pytest

from tests._conftest_environment import _DEFAULT_TEST_TERM


def test_suite_pins_capable_term_and_clears_color_overrides() -> None:
    assert os.environ.get("TERM") == _DEFAULT_TEST_TERM
    assert "NO_COLOR" not in os.environ
    assert "FORCE_COLOR" not in os.environ
    assert "CLICOLOR" not in os.environ
    assert "CLICOLOR_FORCE" not in os.environ


def test_tests_may_override_term_and_color_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert os.environ["TERM"] == "dumb"
    assert os.environ["NO_COLOR"] == "1"
    assert os.environ["FORCE_COLOR"] == "1"
