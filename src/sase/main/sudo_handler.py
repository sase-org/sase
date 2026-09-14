"""Handler for the ``sase sudo`` command group."""

from __future__ import annotations

import argparse
import sys
from typing import NoReturn

from sase.notification_gates.models import GateError


def handle_sudo_command(args: argparse.Namespace) -> NoReturn:
    """Dispatch ``sase sudo`` subcommands."""
    try:
        from sase.sudo.cli import handle_sudo_command as _handle

        code = _handle(args)
    except GateError as exc:
        print(f"sase sudo: failed [{exc.code}] {exc.target}: {exc}", file=sys.stderr)
        sys.exit(1)
    except OSError as exc:
        print(f"sase sudo: {exc}", file=sys.stderr)
        sys.exit(1)
    sys.exit(code)


__all__ = ["handle_sudo_command"]
