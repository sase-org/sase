"""Shared helpers for axe routine-origin (declaring-source) tests."""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def reset_axe_config_cache() -> Any:
    """Isolate the token-keyed axe composition cache per test."""
    import sase.axe.config as axe_config

    axe_config._keyed_config_cache_token = None
    axe_config._keyed_config_cache_value = None
    yield
    axe_config._keyed_config_cache_token = None
    axe_config._keyed_config_cache_value = None
