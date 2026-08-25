"""Ceiling policy, target-version selection, and PyPI fetch tests for ratchet_core_window."""

from __future__ import annotations

import json
import urllib.error
from types import ModuleType

import pytest

from tests._ratchet_core_window_tool_helpers import complete_files as _complete_files
from tests._ratchet_core_window_tool_helpers import load_tool as _load_tool
from tests._ratchet_core_window_tool_helpers import metadata as _metadata


pytestmark = pytest.mark.contract


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    return _load_tool()


def test_ceiling_policy_is_single_function(tool: ModuleType) -> None:
    assert tool.ceiling_specifier_for_floor(tool.parse_version("0.21.3")) == "<0.22.0"
    assert tool.ceiling_specifier_for_floor(tool.parse_version("1.4.5")) == "<2.0.0"


def test_select_target_uses_version_order_and_skips_incomplete_releases(
    tool: ModuleType,
) -> None:
    metadata = {
        "releases": {
            "0.9.2": _complete_files("0.9.2"),
            "0.10.0": _complete_files("0.10.0"),
            "0.11.0rc1": _complete_files("0.11.0rc1"),
            "0.11.0": _complete_files("0.11.0")[:-1],
            "0.12.0": _complete_files("0.12.0", yanked=True),
        }
    }

    target = tool.select_target_version(metadata, tool.parse_version("0.9.2"))

    assert target.raw == "0.10.0"


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_pypi_fetch_retries_transient_failures(tool: ModuleType) -> None:
    seen: list[tuple[str, float]] = []
    sleeps: list[float] = []
    payload = _metadata("0.21.3")

    def _urlopen(url: str, *, timeout: float) -> _Response:
        seen.append((url, timeout))
        if len(seen) < 3:
            raise urllib.error.URLError("temporary failure")
        return _Response(payload)

    assert (
        tool.fetch_pypi_metadata(
            urlopen_fn=_urlopen,
            sleep_fn=sleeps.append,
            attempts=3,
        )
        == payload
    )
    assert seen == [
        (tool.PYPI_URL, tool.PYPI_TIMEOUT_SECONDS),
        (tool.PYPI_URL, tool.PYPI_TIMEOUT_SECONDS),
        (tool.PYPI_URL, tool.PYPI_TIMEOUT_SECONDS),
    ]
    assert sleeps == [0.5, 1.0]
