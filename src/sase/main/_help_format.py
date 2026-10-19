"""Shared stable help formatter for CLI parsers."""

from __future__ import annotations

import argparse


class StableInvocationHelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Render every option as ``-s, --long METAVAR`` on all interpreters.

    Python 3.12 renders ``-f {a,b}, --format {a,b}`` while 3.13+ renders
    ``-f, --format {a,b}``. This formatter always uses the 3.13+ layout so
    help goldens stay byte-identical across supported Pythons.
    """

    def _format_action_invocation(self, action: argparse.Action) -> str:
        if not action.option_strings:
            return super()._format_action_invocation(action)
        if action.nargs == 0:
            return ", ".join(action.option_strings)

        default = self._get_default_metavar_for_optional(action)
        args_string = self._format_args(action, default)
        return f"{', '.join(action.option_strings)} {args_string}"


__all__ = ["StableInvocationHelpFormatter"]
