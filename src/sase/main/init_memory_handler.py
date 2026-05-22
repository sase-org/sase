"""Handler for the ``sase init memory`` command."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from sase.config.core import CHEZMOI_HOME, CONFIG_DIR, get_use_chezmoi

_COMMAND_LABEL = "init memory"


def _home_memory_path(use_chezmoi: bool) -> Path:
    """Return the home-level short memory target for the active config mode."""
    if use_chezmoi:
        return CHEZMOI_HOME / "memory" / "short" / "sase.md"
    return Path.home() / "memory" / "short" / "sase.md"


def _global_config_path(use_chezmoi: bool) -> Path:
    """Return the global config source path for the active config mode."""
    if use_chezmoi:
        return CHEZMOI_HOME / "dot_config" / "sase" / "sase.yml"
    return CONFIG_DIR / "sase.yml"


def handle_init_memory_command(args: argparse.Namespace) -> None:
    """Handle the ``sase init memory`` command.

    Phase 1 registers the command and resolves the target contract without
    writing files. Generation and reference validation land in the follow-up
    phase.
    """
    del args

    use_chezmoi = get_use_chezmoi()
    project_memory = Path.cwd() / "memory" / "short" / "sase.md"
    home_memory = _home_memory_path(use_chezmoi)
    global_config = _global_config_path(use_chezmoi)

    print(f"{_COMMAND_LABEL}: command registered")
    print(f"  project memory target: {project_memory}")
    print(f"  home memory target: {home_memory}")
    print(f"  global config source: {global_config}")
    print("  generation will be implemented by the next phase")
    sys.exit(0)
