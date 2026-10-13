"""Shared fixtures for macro plugin-discovery tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from sase.main.plugin_discovery import _clear_macro_plugin_discovery_memo


@pytest.fixture(autouse=True)
def _clear_macro_plugin_discovery_memo_fixture() -> Iterator[None]:
    """Drop the process-local discovery memo around each test.

    Several tests patch ``importlib.metadata.entry_points``, the discovery
    functions, or ``sys.path`` without changing the install signature, so a
    memo that survived across tests would serve stale entry points.
    """
    _clear_macro_plugin_discovery_memo()
    yield
    _clear_macro_plugin_discovery_memo()
