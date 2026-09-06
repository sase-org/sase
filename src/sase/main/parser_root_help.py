"""Curated root help rendering for the SASE CLI parser."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from typing import Any, TextIO

from rich.console import Console
from rich.text import Text


@dataclass(frozen=True)
class CompactRootCommand:
    name: str
    summary: str


_COMPACT_ROOT_COMMANDS: tuple[CompactRootCommand, ...] = (
    CompactRootCommand(
        "doctor",
        "Run read-only install, config, provider, project, and state diagnostics.",
    ),
    CompactRootCommand(
        "init",
        "Check or initialize config, memory, repositories, and skills.",
    ),
    CompactRootCommand(
        "version",
        "Show the exact SASE host, Rust core, and plugin packages loaded by this process.",
    ),
    CompactRootCommand(
        "ace",
        "Open the interactive control surface for agents, projects, notifications, "
        "automation, and Patches.",
    ),
    CompactRootCommand(
        "run",
        "Launch or resume a coding-agent run from a prompt, xprompt, workflow, or history.",
    ),
    CompactRootCommand(
        "prompt",
        "Inspect, search, replay, and curate previously submitted agent prompts.",
    ),
    CompactRootCommand(
        "agent",
        "List, inspect, tag, or stop active and recent agent runs.",
    ),
    CompactRootCommand(
        "memory",
        "Inspect loaded memory, review proposals, and audit reference memory activity.",
    ),
    CompactRootCommand(
        "patch",
        "Inspect and maintain Patch lifecycle records, refs, and delta metadata.",
    ),
    CompactRootCommand(
        "bead",
        "Manage git-portable issues, dependencies, planning beads, and executable epics.",
    ),
    CompactRootCommand(
        "project",
        "List enabled projects, inspect the current project, and manage disabled work.",
    ),
    CompactRootCommand(
        "stitch",
        "Dispatch a commit, proposal, or PR; show the stitch timeline.",
    ),
    CompactRootCommand(
        "workspace",
        "Inspect, prepare, and repair numbered checkouts used by parallel agents.",
    ),
)

_COMPACT_ROOT_EXAMPLES: tuple[str, ...] = (
    "sase doctor",
    "sase init -c",
    'sase run "#git:home summarize this repository; do not change files"',
    "sase ace",
    "sase agent list",
    "sase --full-help",
)
_COMPACT_ROOT_USAGE = "sase [-h] [-H] [-f <flag>] [-F <flag>] <command> [args...]"
_COMPACT_GLOBAL_OPTIONS: tuple[tuple[str, str], ...] = (
    (
        "-f, --enable-feature <flag>",
        "Enable a registered feature flag for this invocation",
    ),
    (
        "-F, --disable-feature <flag>",
        "Disable a registered feature flag for this invocation",
    ),
)
_COMPACT_GLOBAL_OPTION_EXAMPLE = 'sase -f ref_sync_gesture run "..."'


class CompactRootHelpAction(argparse.Action):
    """Print curated root help and exit."""

    def __init__(self, option_strings: list[str], dest: str, **kwargs: Any) -> None:
        super().__init__(
            option_strings=option_strings,
            dest=dest,
            nargs=0,
            default=argparse.SUPPRESS,
            **kwargs,
        )

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        del namespace, values, option_string
        print_compact_root_help(parser, sys.stdout)
        parser.exit()


class FullRootHelpAction(argparse.Action):
    """Print exhaustive argparse root help and exit."""

    def __init__(self, option_strings: list[str], dest: str, **kwargs: Any) -> None:
        super().__init__(
            option_strings=option_strings,
            dest=dest,
            nargs=0,
            default=argparse.SUPPRESS,
            **kwargs,
        )

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        del namespace, values, option_string
        parser.print_help()
        parser.exit()


def root_subparser_action(
    parser: argparse.ArgumentParser,
) -> argparse._SubParsersAction:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    msg = "root parser has no subparser action"
    raise AssertionError(msg)


def validated_compact_root_commands(
    parser: argparse.ArgumentParser,
) -> tuple[CompactRootCommand, ...]:
    subparser_action = root_subparser_action(parser)
    missing_commands = [
        command.name
        for command in _COMPACT_ROOT_COMMANDS
        if command.name not in subparser_action.choices
    ]
    if missing_commands:
        joined_commands = ", ".join(missing_commands)
        msg = f"compact root help references unknown command(s): {joined_commands}"
        raise AssertionError(msg)

    return tuple(sorted(_COMPACT_ROOT_COMMANDS, key=lambda command: command.name))


def compact_global_option_rows() -> list[str]:
    option_width = max(len(name) for name, _summary in _COMPACT_GLOBAL_OPTIONS)
    return [
        f"  {name:<{option_width}}  {summary}"
        for name, summary in _COMPACT_GLOBAL_OPTIONS
    ]


def format_compact_root_help(parser: argparse.ArgumentParser) -> str:
    commands = validated_compact_root_commands(parser)
    command_width = max(len(command.name) for command in commands)
    command_rows = [
        f"  {command.name:<{command_width}}  {command.summary}" for command in commands
    ]
    example_rows = [f"  {example}" for example in _COMPACT_ROOT_EXAMPLES]
    return "\n".join(
        [
            f"usage: {_COMPACT_ROOT_USAGE}",
            "",
            "SASE - Structured Agentic Software Engineering",
            "",
            "Global options:",
            *compact_global_option_rows(),
            "",
            f"  Example: {_COMPACT_GLOBAL_OPTION_EXAMPLE}",
            "",
            "Common commands:",
            *command_rows,
            "",
            "Examples:",
            *example_rows,
            "",
            "Use `sase <command> --help` for command-specific flags.",
            "Use `sase --full-help` to show every command.",
            "",
        ]
    )


def print_compact_root_help(parser: argparse.ArgumentParser, stream: TextIO) -> None:
    if stream_supports_color(stream):
        console = Console(file=stream, force_terminal=True, highlight=False)
        console.print(format_colored_compact_root_help(parser), end="", soft_wrap=True)
        return

    parser._print_message(format_compact_root_help(parser), stream)


def stream_supports_color(stream: TextIO) -> bool:
    if os.environ.get("NO_COLOR") is not None or os.environ.get("TERM") == "dumb":
        return False

    isatty = getattr(stream, "isatty", None)
    return bool(isatty is not None and isatty())


def format_colored_compact_root_help(parser: argparse.ArgumentParser) -> Text:
    commands = validated_compact_root_commands(parser)
    command_width = max(len(command.name) for command in commands)
    help_text = Text()

    help_text.append("usage:", style="bold dim")
    help_text.append(f" {_COMPACT_ROOT_USAGE}", style="dim")
    help_text.append("\n\n")
    help_text.append("SASE - Structured Agentic Software Engineering", style="bold")
    help_text.append("\n\n")
    help_text.append("Global options:", style="bold cyan")
    help_text.append("\n")
    option_width = max(len(name) for name, _summary in _COMPACT_GLOBAL_OPTIONS)
    for name, summary in _COMPACT_GLOBAL_OPTIONS:
        help_text.append("  ")
        help_text.append(f"{name:<{option_width}}", style="bold green")
        help_text.append("  ")
        help_text.append(summary)
        help_text.append("\n")
    help_text.append("\n")
    help_text.append("  Example: ")
    help_text.append(_COMPACT_GLOBAL_OPTION_EXAMPLE, style="yellow")
    help_text.append("\n\n")
    help_text.append("Common commands:", style="bold cyan")
    help_text.append("\n")
    for command in commands:
        help_text.append("  ")
        help_text.append(f"{command.name:<{command_width}}", style="bold green")
        help_text.append("  ")
        help_text.append(command.summary)
        help_text.append("\n")
    help_text.append("\n")
    help_text.append("Examples:", style="bold cyan")
    help_text.append("\n")
    for example in _COMPACT_ROOT_EXAMPLES:
        help_text.append("  ")
        help_text.append(example, style="yellow")
        help_text.append("\n")
    help_text.append("\n")
    help_text.append("Use ", style="dim")
    help_text.append("`sase <command> --help`", style="bold")
    help_text.append(" for command-specific flags.", style="dim")
    help_text.append("\n")
    help_text.append("Use ", style="dim")
    help_text.append("`sase --full-help`", style="bold")
    help_text.append(" to show every command.", style="dim")
    help_text.append("\n")
    return help_text
