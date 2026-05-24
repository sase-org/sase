"""CLI entry points for agent markdown document commands."""

from __future__ import annotations

import argparse


def run_amd_init(args: argparse.Namespace) -> int:
    """Run the AMD initializer."""
    from .init import run_amd_init as _run_amd_init

    return _run_amd_init(args)


def run_amd_list(args: argparse.Namespace) -> int:
    """Run the AMD inventory skeleton."""
    print("AMD inventory is registered; no inventory output is implemented yet.")
    return 0
