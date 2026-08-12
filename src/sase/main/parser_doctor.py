"""Argument parser definition for the ``sase doctor`` top-level command."""

from __future__ import annotations

import argparse


class _DoctorHelpFormatter(argparse.RawDescriptionHelpFormatter):
    def _format_action_invocation(self, action: argparse.Action) -> str:
        if not action.option_strings:
            return super()._format_action_invocation(action)
        if action.nargs == 0:
            return ", ".join(action.option_strings)

        default = self._get_default_metavar_for_optional(action)
        args_string = self._format_args(action, default)
        return f"{', '.join(action.option_strings)} {args_string}"


def register_doctor_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase doctor`` command parser."""
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Run read-only SASE diagnostics for support",
        description=(
            "Run fast, read-only diagnostics for the active SASE runtime,\n"
            "configuration, and project checkout. Default mode is bounded and\n"
            "safe to run before asking for help."
        ),
        epilog=(
            "Examples:\n"
            "  sase doctor\n"
            "  sase doctor -v\n"
            "  sase doctor -j\n"
            "  sase doctor -D -j\n"
            "  sase doctor -C runtime\n"
            "  sase doctor -C llm.default -s\n"
            "  sase doctor -F\n\n"
            "Exit codes: OK, WARN, and SKIP exit 0; ERROR exits 1.\n"
            "--strict makes WARN exit 1."
        ),
        formatter_class=_DoctorHelpFormatter,
    )
    doctor_parser.add_argument(
        "-C",
        "--check",
        action="append",
        default=[],
        metavar="ID_OR_GROUP",
        help="Run only a check id or group; repeatable",
    )
    doctor_parser.add_argument(
        "-D",
        "--deep",
        action="store_true",
        help="Include slower read-only deep checks",
    )
    doctor_parser.add_argument(
        "-F",
        "--fix-duplicate-blocks",
        action="store_true",
        help=(
            "Preview and, after confirmation, keep one block per Patch name "
            "in every ProjectSpec"
        ),
    )
    doctor_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON support report",
    )
    doctor_parser.add_argument(
        "-L",
        "--list-checks",
        action="store_true",
        help="List registered diagnostic checks without running them",
    )
    doctor_parser.add_argument(
        "-p",
        "--project",
        default=None,
        help="Project name to inspect when it cannot be inferred",
    )
    doctor_parser.add_argument(
        "-s",
        "--strict",
        action="store_true",
        help="Exit non-zero when warnings are present",
    )
    doctor_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show every check and bounded detail",
    )
    doctor_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Apply requested repairs without an interactive confirmation",
    )


__all__ = ["register_doctor_parser"]
