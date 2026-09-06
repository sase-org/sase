"""Root parser type and argv normalization helpers."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable, Sequence
from typing import Any, TypeVar, overload

_NamespaceT = TypeVar("_NamespaceT")

_OBSOLETE_DETACHED_PROC_MESSAGE = (
    "all procs are detached; remove --detached (use --session none for no attribution)."
)
_PROC_ALIASES = frozenset({"proc", "task"})
_PROC_SUBCOMMANDS_WITH_LEGACY_DETACHED = frozenset({"list", "run"})

_BEAD_NOTE_VALUE_OPTIONS = frozenset(
    {
        "-a",
        "--author",
        "-e",
        "--edit",
        "-x",
        "--remove",
    }
)
_GLOBAL_VALUE_OPTIONS = frozenset(
    {
        "-f",
        "--enable-feature",
        "-F",
        "--disable-feature",
    }
)

_VALIDATION_FORMATTER: argparse.HelpFormatter | None = None


def shared_validation_formatter() -> argparse.HelpFormatter:
    """Return one colorless formatter for construction-time help checks."""
    global _VALIDATION_FORMATTER
    formatter = _VALIDATION_FORMATTER
    if formatter is None:
        formatter = argparse.HelpFormatter(prog="sase")
        set_color = getattr(formatter, "_set_color", None)
        if callable(set_color):
            set_color(False)
        _VALIDATION_FORMATTER = formatter
    return formatter


class SaseArgumentParser(argparse.ArgumentParser):
    """Root parser with cross-option validation that argparse cannot express."""

    def _get_validation_formatter(self) -> argparse.HelpFormatter:
        """Reuse one colorless formatter while constructing the command tree.

        Python 3.14 validates every help string through a per-parser formatter
        whose ``_set_color`` path dominates ``create_parser``. Validation only
        interpolates help templates, so a shared colorless formatter is enough.
        ``format_help`` still uses ``_get_formatter`` and keeps TTY color.
        """
        return shared_validation_formatter()

    @overload
    def parse_args(
        self,
        args: Iterable[str] | None = ...,
        namespace: None = ...,
    ) -> argparse.Namespace: ...

    @overload
    def parse_args(
        self,
        args: Iterable[str] | None,
        namespace: _NamespaceT,
    ) -> _NamespaceT: ...

    @overload
    def parse_args(self, *, namespace: _NamespaceT) -> _NamespaceT: ...

    def parse_args(
        self,
        args: Iterable[str] | None = None,
        namespace: Any = None,
    ) -> Any:
        raw_args = list(sys.argv[1:] if args is None else args)
        raw_args = normalize_bead_note_args(raw_args)
        if uses_obsolete_detached_proc_option(raw_args):
            self.exit(2, f"{_OBSOLETE_DETACHED_PROC_MESSAGE}\n")
        parsed, unknown = super().parse_known_args(raw_args, namespace)
        if unknown:
            if is_bead_note_args(parsed):
                parsed.text.extend(unknown)
            else:
                self.error(f"unrecognized arguments: {' '.join(unknown)}")
        if (
            getattr(parsed, "command", None) == "agent"
            and getattr(parsed, "agent_subcommand", None) == "sync"
            and getattr(parsed, "refresh", False)
            and not getattr(parsed, "check", False)
        ):
            self.error("sase agent sync --refresh requires --check")
        if (
            getattr(parsed, "command", None) == "agent"
            and getattr(parsed, "agent_subcommand", None) == "sync"
            and getattr(parsed, "check", False)
        ):
            for flag, attribute in (
                ("--drop-retired", "drop_retired"),
                ("--retry-quarantined", "retry_quarantined"),
            ):
                if getattr(parsed, attribute, False):
                    self.error(f"sase agent sync {flag} cannot be used with --check")
        if (
            getattr(parsed, "command", None) == "init"
            and getattr(parsed, "json", False)
            and not getattr(parsed, "check", False)
        ):
            self.error("sase init --json requires --check")
        return parsed


def is_bead_note_args(parsed: argparse.Namespace) -> bool:
    return (
        getattr(parsed, "command", None) == "bead"
        and getattr(parsed, "bead_subcommand", None) == "note"
        and isinstance(getattr(parsed, "text", None), list)
    )


def normalize_bead_note_args(argv: list[str]) -> list[str]:
    """Let ``sase bead note`` text appear after its option flags.

    ``argparse`` does not intermix a ``nargs="*"`` positional with options
    under subparsers, so collect the known note flags and move free-form text
    before them.  The parser still owns validation and help rendering.
    """

    command_index = root_command_index(argv)
    if command_index is None or argv[command_index : command_index + 2] != [
        "bead",
        "note",
    ]:
        return argv

    id_index = command_index + 2
    if len(argv) <= id_index:
        return argv

    prefix = argv[: id_index + 1]
    rest = argv[id_index + 1 :]
    text: list[str] = []
    options: list[str] = []
    force_text = False
    index = 0
    while index < len(rest):
        token = rest[index]
        if force_text:
            text.append(token)
            index += 1
            continue
        if token == "--":
            force_text = True
            index += 1
            continue
        option_name = token.split("=", 1)[0]
        if option_name in _BEAD_NOTE_VALUE_OPTIONS:
            options.append(token)
            if "=" not in token and index + 1 < len(rest):
                options.append(rest[index + 1])
                index += 2
            else:
                index += 1
            continue
        text.append(token)
        index += 1
    return [*prefix, *text, *options]


def root_command_index(argv: Sequence[str]) -> int | None:
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in _GLOBAL_VALUE_OPTIONS:
            index += 2
            continue
        if token.startswith("--enable-feature=") or token.startswith(
            "--disable-feature="
        ):
            index += 1
            continue
        return index
    return None


def uses_obsolete_detached_proc_option(argv: Sequence[str]) -> bool:
    """Return whether proc/task argv uses the retired detached selector."""
    if not argv or argv[0] not in _PROC_ALIASES:
        return False

    subcommand = "list"
    option_start = 1
    if len(argv) > 1 and not argv[1].startswith("-"):
        subcommand = argv[1]
        option_start = 2
    if subcommand not in _PROC_SUBCOMMANDS_WITH_LEGACY_DETACHED:
        return False

    try:
        option_end = argv.index("--", option_start)
    except ValueError:
        option_end = len(argv)
    return any(token in {"-d", "--detached"} for token in argv[option_start:option_end])
