"""Argument parsing and pytest-selector validation for screenshot maintenance."""

from __future__ import annotations

import argparse
import os
import shlex
from collections.abc import Mapping, Sequence

from tests.ace.tui.visual._visual_capture_paths import PLUGIN_NAME
from tests.ace.tui.visual._visual_maintenance_types import (
    EXIT_FAILURE,
    EXIT_SUCCESS,
    EXIT_USAGE,
    MaintenanceRequest,
    UsageError,
)


_RESTRICTING_FLAGS = frozenset(
    {
        "-k",
        "--lf",
        "--ff",
        "--last-failed",
        "--failed-first",
        "--nf",
        "--new-first",
        "--collect-only",
        "--co",
        "--deselect",
        "--ignore",
        "--ignore-glob",
        "--file-or-dir",
    }
)
_RESTRICTING_PREFIXES = (
    "-k=",
    "--deselect=",
    "--ignore=",
    "--ignore-glob=",
    "--lf=",
)
_CAPTURE_OWNED_PREFIXES = (
    "--sase-visual-capture-dir",
    "--sase-visual-capture-run-id",
    "--sase-visual-capture-scope",
    "--sase-visual-capture-ace-root",
    "--sase-visual-capture-pager-root",
)
_LEGACY_UPDATE = "--sase-update-visual-snapshots"
_CAPTURE_PLUGIN_ALIASES = frozenset(
    {PLUGIN_NAME, "tests._visual_capture_plugin", "_visual_capture_plugin"}
)
_MARKER_FLAGS = frozenset({"-m", "--markers"})
_HELP_EPILOG = f"""
Exit codes:
  {EXIT_SUCCESS}  check is clean, or an update applied successfully (including no-ops)
  1  check mode found required golden changes
  {EXIT_USAGE}  usage error or environment refusal (CI update, renderer, lock)
  {EXIT_FAILURE}  pytest/capture/inventory/application failure

`just` may normalize a non-zero child code to 1. Automation that needs the
distinction should read the run manifest or invoke this tool directly.

Arguments after `--` are pytest selectors and options (paths, node IDs, `-k`).
The runner owns the visual lane, capture plugin, and candidate directory.
""".strip()


def parse_command(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> MaintenanceRequest:
    """Parse *argv* into a maintenance request.

    Raises ``SystemExit`` for ``-h`` (0) and argparse errors (2). Raises
    ``UsageError`` for rejected pytest options.
    """
    raw = list(sys_argv(argv))
    ours, pytest_args = split_owned_args(raw)
    parser = build_parser()
    namespace = parser.parse_args(ours)
    env = os.environ if environ is None else environ
    env_args = _pytest_addopts(env)
    validate_pytest_args(pytest_args)
    validate_pytest_args(env_args, origin="PYTEST_ADDOPTS")
    scope, reasons = resolve_scope(pytest_args, env_args)
    return MaintenanceRequest(
        check=bool(namespace.check),
        pytest_args=tuple(pytest_args),
        scope=scope,
        scope_reasons=reasons,
        argv=tuple(raw),
    )


def build_parser() -> argparse.ArgumentParser:
    """Return the public argument parser with sorted option help."""
    parser = argparse.ArgumentParser(
        prog="fix_tui_screenshots",
        description=(
            "Capture ACE and pager TUI screenshots, compare them to goldens, "
            "and apply created, updated, and proven-stale changes."
        ),
        epilog=_HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
        usage="%(prog)s [-c/--check] [--] [pytest-selector ...]",
    )
    parser.add_argument(
        "-c",
        "--check",
        action="store_true",
        help=(
            "Compare the complete inventory without writing goldens. "
            "Exit 1 when any required change exists."
        ),
    )
    return parser


def split_owned_args(argv: Sequence[str]) -> tuple[list[str], list[str]]:
    """Split *argv* on `--` into tool flags and pytest arguments."""
    values = list(argv)
    if "--" in values:
        index = values.index("--")
        return values[:index], values[index + 1 :]
    owned, rest = [], []
    for arg in values:
        if arg in {"-c", "--check", "-h", "--help"}:
            owned.append(arg)
            continue
        rest.append(arg)
    return owned, rest


def sys_argv(argv: Sequence[str] | None) -> Sequence[str]:
    if argv is None:
        import sys

        return sys.argv[1:]
    return argv


def resolve_scope(
    pytest_args: Sequence[str],
    env_args: Sequence[str] = (),
) -> tuple[str, tuple[str, ...]]:
    """Return ``full`` or ``targeted`` plus reasons that suppressed a full run."""
    reasons: list[str] = []
    if _has_restricting_args(pytest_args):
        reasons.append("cli_selectors")
    if _has_restricting_args(env_args):
        reasons.append("PYTEST_ADDOPTS")
    if reasons:
        return "targeted", tuple(reasons)
    return "full", ()


def validate_pytest_args(
    args: Sequence[str],
    *,
    origin: str = "pytest arguments",
) -> None:
    """Reject options that replace the visual lane or bypass capture."""
    if _LEGACY_UPDATE in args or any(
        arg.startswith(f"{_LEGACY_UPDATE}=") for arg in args
    ):
        raise UsageError(
            f"{origin} request legacy golden writes via {_LEGACY_UPDATE}; "
            "use `just fix-tui-screenshots` without that pytest flag"
        )
    for arg in args:
        for prefix in _CAPTURE_OWNED_PREFIXES:
            if arg == prefix or arg.startswith(f"{prefix}="):
                raise UsageError(
                    f"{origin} include {prefix}, which the maintenance runner owns"
                )
    if "--noconftest" in args:
        raise UsageError(
            f"{origin} include --noconftest, which would skip visual fixtures"
        )
    if _has_marker_override(args):
        raise UsageError(
            f"{origin} replace the visual marker with -m/--markers; "
            "pass paths, node IDs, or -k after -- instead"
        )
    disabled = _disabled_plugin_names(args)
    blocked = sorted(_CAPTURE_PLUGIN_ALIASES.intersection(disabled))
    if blocked:
        raise UsageError(
            f"{origin} disable the visual capture plugin ({', '.join(blocked)})"
        )


def _pytest_addopts(environ: Mapping[str, str]) -> list[str]:
    raw = environ.get("PYTEST_ADDOPTS", "")
    if not raw.strip():
        return []
    try:
        return shlex.split(raw)
    except ValueError:
        return raw.split()


def _has_restricting_args(args: Sequence[str]) -> bool:
    for arg in args:
        if arg in _RESTRICTING_FLAGS:
            return True
        if any(arg.startswith(prefix) for prefix in _RESTRICTING_PREFIXES):
            return True
        if arg == "--":
            continue
        if not arg.startswith("-"):
            return True
    return False


def _has_marker_override(args: Sequence[str]) -> bool:
    for arg in args:
        if (
            arg in _MARKER_FLAGS
            or arg.startswith("-m=")
            or arg.startswith("--markers=")
        ):
            return True
        if arg.startswith("-m") and not arg.startswith("-max"):
            return True
    return False


def _disabled_plugin_names(args: Sequence[str]) -> set[str]:
    names: set[str] = set()
    skip_value = False
    for arg in args:
        if skip_value:
            _add_plugin_tokens(arg, names)
            skip_value = False
            continue
        if arg in {"-p", "--plugins"}:
            skip_value = True
            continue
        if arg.startswith("-p") and arg != "-p":
            _add_plugin_tokens(arg[2:].lstrip("="), names)
        elif arg.startswith("--plugins="):
            _add_plugin_tokens(arg.split("=", 1)[1], names)
    return names


def _add_plugin_tokens(value: str, names: set[str]) -> None:
    for part in value.split(","):
        token = part.strip()
        if token.startswith("no:"):
            names.add(token[3:].strip())
