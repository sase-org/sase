"""Handler for ``sase artifact`` subcommands."""

from __future__ import annotations

import argparse
from typing import NoReturn

from sase.core import artifact_facade

from .artifact_cli.commands import handle_artifact_command as _dispatch_artifact_command


def handle_artifact_command(args: argparse.Namespace) -> NoReturn:
    """Dispatch to the appropriate artifact sub-handler."""
    _dispatch_artifact_command(args, artifact_facade)
