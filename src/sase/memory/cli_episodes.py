"""CLI dispatcher for ``sase memory episodes``."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from sase.memory.cli_episodes_build import handle_episode_build
from sase.memory.cli_episodes_inventory import handle_episode_list
from sase.memory.cli_episodes_recall import handle_episode_recall
from sase.memory.cli_episodes_show import handle_episode_show
from sase.memory.cli_episodes_verify import handle_episode_verify


def handle_memory_episodes_command(
    args: argparse.Namespace,
    *,
    projects_root: Path | str | None = None,
    repo_root: Path | str | None = None,
) -> None:
    """Dispatch ``sase memory episodes`` subcommands."""

    subcommand = getattr(args, "episodes_subcommand", None)
    if subcommand == "build":
        handle_episode_build(args, projects_root=projects_root, repo_root=repo_root)
        return
    if subcommand == "list":
        handle_episode_list(args, projects_root=projects_root)
        return
    if subcommand == "show":
        handle_episode_show(args, projects_root=projects_root)
        return
    if subcommand == "verify":
        handle_episode_verify(args, projects_root=projects_root)
        return
    if subcommand == "recall":
        handle_episode_recall(args, projects_root=projects_root)
        return

    print(
        "Usage: sase memory episodes {build,list,show,verify,recall}",
        file=sys.stderr,
    )
    sys.exit(1)


__all__ = [
    "handle_memory_episodes_command",
]
