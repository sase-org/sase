"""Tests for ace.hooks.defaults module."""

from unittest.mock import patch

from sase.ace.hooks.defaults import get_required_changespec_hooks


def test_get_required_changespec_hooks_uses_config_override() -> None:
    """Test that config override is used when present."""
    with patch(
        "sase.ace.hooks.defaults.get_vcs_provider_config",
        return_value={"default_hooks": ["!$my_presubmit", "$my_lint"]},
    ):
        result = get_required_changespec_hooks()

    assert result == ("!$my_presubmit", "$my_lint")


def test_get_required_changespec_hooks_empty_default() -> None:
    """Test that built-in default is empty (plugins provide their own)."""
    with patch(
        "sase.ace.hooks.defaults.get_vcs_provider_config",
        return_value={},
    ):
        result = get_required_changespec_hooks()

    assert result == ()
