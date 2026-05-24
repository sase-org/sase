"""CLI skeleton for agent markdown document commands."""

from __future__ import annotations

import argparse


def run_amd_init(args: argparse.Namespace) -> int:
    """Run the AMD initializer skeleton."""
    if getattr(args, "check", False):
        print("AMD initialization check is registered; no checks are implemented yet.")
    else:
        print("AMD initialization is registered; no file actions are implemented yet.")
    return 0


def run_amd_list(args: argparse.Namespace) -> int:
    """Run the AMD inventory skeleton."""
    print("AMD inventory is registered; no inventory output is implemented yet.")
    return 0
