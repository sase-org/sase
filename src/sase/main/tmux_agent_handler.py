"""Dispatch for the ``sase tmux-agent`` command."""

from __future__ import annotations

import argparse
import sys


def handle_tmux_agent_command(args: argparse.Namespace) -> None:
    """Dispatch a parsed tmux-agent command and exit with its handler's code."""
    from sase.tmux_agent.cli import handle_tmux_agent_cli

    sys.exit(handle_tmux_agent_cli(args))


__all__ = ["handle_tmux_agent_command"]
