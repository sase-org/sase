"""Exact-pin specifier tests for ratchet_core_pin."""

from __future__ import annotations

from types import ModuleType

import pytest

from tests._ratchet_core_window_tool_helpers import load_tool as _load_tool


pytestmark = pytest.mark.contract


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    return _load_tool()


def test_dependency_specifier_is_exact_pin(tool: ModuleType) -> None:
    assert (
        tool.dependency_specifier_for_floor(tool.parse_version("0.21.3")) == "==0.21.3"
    )
    assert tool.dependency_specifier_for_floor(tool.parse_version("1.4.5")) == "==1.4.5"
