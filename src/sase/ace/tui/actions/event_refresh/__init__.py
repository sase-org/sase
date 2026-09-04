"""Refresh, watcher, and daemon event handler mixins."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from ._constants import (
    AGENT_ARTIFACT_DELTA_QUEUE_LIMIT,
    AGENTS_LOAD_MIN_INTERVAL_SECONDS,
    EXPECTED_AGENT_ARTIFACT_DELETION_TTL_SECONDS,
    FULL_SANITY_REFRESH_SECONDS,
    PROMPT_INPUT_DEFER_SECONDS,
)

_LAZY_EXPORTS = {
    "EventRefreshMixin": ("._mixin", "EventRefreshMixin"),
}

__all__ = [
    "AGENT_ARTIFACT_DELTA_QUEUE_LIMIT",
    "AGENTS_LOAD_MIN_INTERVAL_SECONDS",
    "EXPECTED_AGENT_ARTIFACT_DELETION_TTL_SECONDS",
    "FULL_SANITY_REFRESH_SECONDS",
    "PROMPT_INPUT_DEFER_SECONDS",
    "EventRefreshMixin",
]


def __getattr__(name: str) -> Any:
    try:
        module_name, attr = _LAZY_EXPORTS[name]
    except KeyError as error:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from error
    module = import_module(module_name, __name__)
    value = getattr(module, attr)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})


# PEP 562 entry points are called by Python, not by normal in-file code.
_PEP562_HOOKS = (__getattr__, __dir__)
