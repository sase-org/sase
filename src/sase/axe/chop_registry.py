"""Chop registry for the axe lumberjack architecture.

A chop is a named check function that a lumberjack invokes by name each tick.
This module provides a registry of chops, a decorator for registering them,
and a ChopContext dataclass that carries per-tick state to each chop.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sase.ace.changespec import ChangeSpec
from sase.ace.query import QueryExpr

from .runner_pool import RunnerPool
from .state import AxeMetrics

# Type alias for log callback (same as hook_jobs.py / check_cycles.py)
LogCallback = Callable[[str, str | None], None]


@dataclass
class ChopContext:
    """Per-tick context passed to every chop function.

    Constructed by the lumberjack once per tick, then shared across all
    chops that the lumberjack is configured to run.
    """

    log_callback: LogCallback
    runner_pool: RunnerPool
    metrics: AxeMetrics
    parsed_query: QueryExpr | None
    max_runners: int
    zombie_timeout_seconds: int
    all_changespecs: list[ChangeSpec]
    filtered_changespecs: list[ChangeSpec]
    lumberjack_name: str
    state_dir: Path


# Chop function signature: takes a ChopContext, returns nothing.
ChopFunc = Callable[[ChopContext], None]

# Module-level registry: chop-name → chop-function
_CHOPS: dict[str, ChopFunc] = {}


def register_chop(name: str) -> Callable[[ChopFunc], ChopFunc]:
    """Decorator that registers a function as a named chop.

    Usage::

        @register_chop("hook_checks")
        def run_hook_checks(ctx: ChopContext) -> None:
            ...
    """

    def decorator(func: ChopFunc) -> ChopFunc:
        _CHOPS[name] = func
        return func

    return decorator


def get_chop(name: str) -> ChopFunc:
    """Look up a chop by name.

    Raises:
        KeyError: If no chop is registered under *name*.
    """
    _ensure_chops_loaded()
    if name not in _CHOPS:
        raise KeyError(f"No chop registered with name {name!r}")
    return _CHOPS[name]


def list_chops() -> list[str]:
    """Return a sorted list of all registered chop names."""
    _ensure_chops_loaded()
    return sorted(_CHOPS)


def get_all_chops() -> dict[str, ChopFunc]:
    """Return a copy of the full chop registry."""
    _ensure_chops_loaded()
    return dict(_CHOPS)


def _ensure_chops_loaded() -> None:
    """Import chop modules so they self-register (lazy, idempotent)."""
    if _CHOPS:
        return
    from sase.axe import chops as _chops  # noqa: F841
