"""Public facade for ``sase memory init`` and its ``sase init memory`` alias.

Behavior lives in :mod:`sase.main._init_memory_support` (inputs and root
plans), ``_init_memory_plan`` (read-only planning), and ``_init_memory_apply``
(opt-in, apply, and deploy). Shared helpers are public names in the
already-private support module so no split module imports a ``_``-prefixed
name across modules. This module re-exports the public names only so every
existing import path keeps working.
"""

from __future__ import annotations

import argparse

from ._init_memory_apply import (
    HOME_MEMORY_DEPLOY_BYPASS_ENV,
    handle_memory_init_command as handle_memory_init_command_impl,
    prepare_project_memory_opt_in as prepare_project_memory_opt_in_impl,
    run_init_memory as run_init_memory_impl,
)
from ._init_memory_plan import plan_init_memory as plan_init_memory_impl
from .init_plan import InitPlan

__all__ = [
    "HOME_MEMORY_DEPLOY_BYPASS_ENV",
    "handle_init_memory_command",
    "handle_memory_init_command",
    "plan_init_memory",
    "prepare_project_memory_opt_in",
    "run_init_memory",
]


def plan_init_memory(args: argparse.Namespace) -> InitPlan:
    """Return a read-only plan for generated memory files."""
    return plan_init_memory_impl(args)


def prepare_project_memory_opt_in(args: argparse.Namespace) -> bool:
    """Apply the compatibility opt-in flag before init planning or writes."""
    return prepare_project_memory_opt_in_impl(args)


def run_init_memory(args: argparse.Namespace) -> int:
    """Apply ``sase memory init`` and return a process exit code."""
    return run_init_memory_impl(args)


def handle_memory_init_command(args: argparse.Namespace) -> None:
    """Handle the ``sase memory init`` command."""
    handle_memory_init_command_impl(args)


def handle_init_memory_command(args: argparse.Namespace) -> None:
    """Compatibility wrapper for ``sase init memory``."""
    handle_memory_init_command(args)
