"""Shared help formatters for SASE CLI parsers."""

from __future__ import annotations

import argparse


class CompactRawDescriptionHelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Render short and long value-taking options with one metavar."""

    def _format_action_invocation(self, action: argparse.Action) -> str:
        if not action.option_strings:
            return super()._format_action_invocation(action)
        if action.nargs == 0:
            return ", ".join(action.option_strings)

        default = self._get_default_metavar_for_optional(action)
        args_string = self._format_args(action, default)
        return f"{', '.join(action.option_strings)} {args_string}"


__all__ = ["CompactRawDescriptionHelpFormatter"]
