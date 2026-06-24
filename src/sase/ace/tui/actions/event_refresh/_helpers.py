"""Small helpers shared by event refresh modules."""

from __future__ import annotations

from collections.abc import Callable
from inspect import Parameter, signature


def callable_accepts_kwarg(callback: Callable[..., object], name: str) -> bool:
    try:
        params = signature(callback).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(p.kind == Parameter.VAR_KEYWORD or p.name == name for p in params)
