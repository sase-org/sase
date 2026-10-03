"""Scoped runtime template variables for prompt rendering."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any


_RUNTIME_TEMPLATE_VARS: ContextVar[Mapping[str, Any] | None] = ContextVar(
    "sase_xprompt_runtime_template_vars",
    default=None,
)


@contextmanager
def bind_runtime_template_vars(values: Mapping[str, Any]) -> Iterator[None]:
    """Bind runtime-only Jinja variables for one execution scope."""
    token = _RUNTIME_TEMPLATE_VARS.set(dict(values))
    try:
        yield
    finally:
        _RUNTIME_TEMPLATE_VARS.reset(token)


def get_runtime_template_vars() -> dict[str, Any]:
    """Return the current runtime-only Jinja variables."""
    values = _RUNTIME_TEMPLATE_VARS.get()
    return dict(values) if values else {}


__all__ = ["bind_runtime_template_vars", "get_runtime_template_vars"]
