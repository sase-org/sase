"""Multi-project batch helpers for ``sase init --all`` / ``--project``."""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from contextlib import contextmanager
import copy
import os
from pathlib import Path

from rich.console import Console

from ._init_onboarding_types import InitRunStatus
from .init_project_scope import InitProjectTarget


@contextmanager
def working_directory(path: Path) -> Iterator[None]:
    """Temporarily enter *path* and always restore the caller's directory."""
    original = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(original)


def project_args(args: argparse.Namespace) -> argparse.Namespace:
    """Return a fresh namespace for one project in a batch run."""
    fresh_args = copy.copy(args)
    fresh_args.all = False
    fresh_args.enable_project_memory = False
    if hasattr(fresh_args, "project"):
        fresh_args.project = None
    if hasattr(fresh_args, "json"):
        fresh_args.json = False
    for marker in (
        "_project_memory_opt_in_prepared",
        "_project_config_changed",
        "_project_config_git_state",
        "_project_config_operation",
    ):
        if hasattr(fresh_args, marker):
            delattr(fresh_args, marker)
    return fresh_args


def render_project_heading(console: Console, target: InitProjectTarget) -> None:
    console.print()
    console.print(f"Project: {target.reference}", style="bold cyan")
    if target.warnings:
        console.print("Project inventory warnings:", style="yellow")
        for warning in target.warnings:
            console.print(f"  {warning}")


def summary_parts(
    *,
    checked: int,
    current: int,
    initialized: int,
    needs_attention: int,
    unavailable: int,
    failed: int,
    cancelled: bool,
    deploy_failed: bool,
) -> list[str]:
    parts = [f"{checked} checked"]
    for count, singular in (
        (current, "current"),
        (initialized, "initialized"),
        (needs_attention, "needs attention"),
        (unavailable, "unavailable"),
        (failed, "failed"),
    ):
        if count:
            parts.append(f"{count} {singular}")
    if cancelled:
        parts.append("cancelled")
    if deploy_failed:
        parts.append("deployment failed")
    return parts


def tally_batch_status(
    status: InitRunStatus,
    *,
    current: int,
    initialized: int,
    needs_attention: int,
    failed: int,
) -> tuple[int, int, int, int, bool]:
    if status == "current":
        return current + 1, initialized, needs_attention, failed, False
    if status == "initialized":
        return current, initialized + 1, needs_attention, failed, False
    if status == "needs_attention":
        return current, initialized, needs_attention + 1, failed, False
    if status == "cancelled":
        return current, initialized, needs_attention, failed, True
    return current, initialized, needs_attention, failed + 1, False
