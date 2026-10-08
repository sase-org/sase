"""Curated root help rendering for the SASE CLI parser."""

from __future__ import annotations

import argparse
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
        "Check or initialize config, machines, memory, repositories, and skills.",
    ),
    CompactRootCommand(
        "version",
        "Show the exact SASE host, Rust core, and plugin packages loaded by this process.",
    ),
    CompactRootCommand(
        "tui",
        "Open the interactive control surface for agents, projects, notifications, "
        "automation, and Patches.",
    ),
    CompactRootCommand(
        "run",
        "Launch or resume a coding-agent run from a prompt, macro, workflow, or history.",
    ),
    CompactRootCommand(
        "screenshot",
        "Capture canonical PNG evidence from a real live SASE TUI in tmux.",
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
        "machine",
        "List, enroll, repair, and check configured remote machine aliases.",
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
        "disk",
        "List SASE disk usage by owner and delegate safe cleanup to those owners.",
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
        "tool",
        "Run and inspect project named tools with a recorded ToolRun history.",
    ),
    CompactRootCommand(
        "usage",
        "Inspect and refresh cached LLM subscription-usage observations.",
    ),
    CompactRootCommand(
        "workspace",
        "Inspect, prepare, and repair numbered checkouts used by parallel agents.",
    ),
)

_COMPACT_ROOT_EXAMPLES: tuple[str, ...] = (
    "sase doctor",
    "sase init -c",
    'sase run "+home summarize this repository; do not change files"',
    "sase screenshot -o /tmp/sase.png",
    "sase tui",
    "sase agent list",
    "sase --full-help",
)
_COMPACT_ROOT_USAGE = "sase [-h] [-H] [-F <flag>] [-f <flag>] [-p] <command> [args...]"
_COMPACT_GLOBAL_OPTIONS: tuple[tuple[str, str], ...] = (
    (
        "-F, --disable-feature <flag>",
        "Disable a registered feature flag for this invocation",
    ),
    (
        "-f, --enable-feature <flag>",
        "Enable a registered feature flag for this invocation",
    ),
    (
        "-p, --print-command",
        "Print the shell-quoted command to stderr before running it",
    ),
)
_COMPACT_GLOBAL_OPTION_EXAMPLE = "alias sbd='sase -p bead'"


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
        print_plugin_commands_footer(sys.stdout)
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
            *compact_plugin_command_group_lines(),
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
    from sase.core.term_color import should_colorize

    return should_colorize(stream)


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
    append_colored_plugin_command_group(help_text)
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


_PLUGIN_COMMANDS_FOOTER_CLOSING = (
    "Manage plugins with sase plugin list or the Updates tab in sase's Admin Center."
)


@dataclass(frozen=True)
class PluginCommandHelpRow:
    """One mounted plugin command with its display summary and provenance."""

    name: str
    summary: str
    distribution: str
    version: str


def mounted_plugin_command_rows() -> tuple[PluginCommandHelpRow, ...]:
    """Return mounted plugin commands with summaries for root help.

    Summaries prefer the adapter ``SUMMARY`` and fall back to the
    distribution metadata without raising, so a broken plugin never breaks
    ``sase -h``; its problem state is reported by ``sase -H`` and doctor.
    """
    from sase.plugin_commands.adapter import resolve_command_summary
    from sase.plugin_commands.registry import discover_plugin_commands

    return tuple(
        PluginCommandHelpRow(
            name=record.name,
            summary=resolve_command_summary(record),
            distribution=record.distribution,
            version=record.version,
        )
        for record in discover_plugin_commands().mounted
    )


def compact_plugin_command_group_lines() -> list[str]:
    """Return the plain-text ``Plugin commands`` group for ``sase -h``.

    The group lists mounted commands only and is empty when none is
    mounted; problem states stay in ``sase -H`` and doctor.
    """
    rows = mounted_plugin_command_rows()
    if not rows:
        return []
    width = max(len(row.name) for row in rows)
    lines = ["Plugin commands:"]
    for row in rows:
        text = (
            f"{row.summary} · {row.distribution}"
            if row.summary
            else f"· {row.distribution}"
        )
        lines.append(f"  {row.name:<{width}}  {text}")
    lines.append("")
    return lines


def append_colored_plugin_command_group(help_text: Text) -> None:
    """Append the ``Plugin commands`` group to colored ``sase -h`` output.

    The stripped text matches :func:`compact_plugin_command_group_lines`.
    """
    rows = mounted_plugin_command_rows()
    if not rows:
        return
    width = max(len(row.name) for row in rows)
    help_text.append("Plugin commands:", style="bold cyan")
    help_text.append("\n")
    for row in rows:
        help_text.append("  ")
        help_text.append(f"{row.name:<{width}}", style="bold green")
        help_text.append("  ")
        if row.summary:
            help_text.append(row.summary)
            help_text.append(" ")
        help_text.append(f"· {row.distribution}", style="dim")
        help_text.append("\n")
    help_text.append("\n")


def format_plugin_commands_footer() -> str:
    """Return the plain-text ``Plugin commands`` footer for ``sase -H``.

    Each mounted command shows the command chip, the summary, and the
    distribution and version; problem rows (shadowed, conflict, invalid
    name, load failure) show ``⚠`` with a one-line reason. The footer is
    empty when no plugin commands exist.
    """
    from sase.plugin_commands.adapter import PluginCommandLoadError, load_plugin_command
    from sase.plugin_commands.chip import format_command_chip
    from sase.plugin_commands.registry import discover_plugin_commands

    command_set = discover_plugin_commands()
    if not command_set.mounted and not command_set.problems:
        return ""
    lines = ["", "Plugin commands:"]
    for record in command_set.mounted:
        try:
            summary = load_plugin_command(record).summary
        except PluginCommandLoadError as exc:
            cause = " ".join(exc.cause.split())
            lines.append(
                f"  ⚠ sase {record.name}  failed to load from "
                f"{exc.distribution} {exc.version}: {cause}; see sase doctor"
            )
            continue
        provenance = f"({record.distribution} {record.version})"
        text = f"{summary} {provenance}" if summary else provenance
        lines.append(f"  {format_command_chip(record.name)}  {text}")
    for problem in command_set.problems:
        owners = ", ".join(problem.distributions)
        lines.append(f"  ⚠ sase {problem.name}  {owners}: {problem.reason}")
    lines.append(_PLUGIN_COMMANDS_FOOTER_CLOSING)
    lines.append("")
    return "\n".join(lines)


def format_colored_plugin_commands_footer() -> Text | None:
    """Return the footer as Rich text, or ``None`` when there is no footer.

    The stripped text matches :func:`format_plugin_commands_footer`.
    """
    from rich.text import Text as RichText

    from sase.plugin_commands.adapter import PluginCommandLoadError, load_plugin_command
    from sase.plugin_commands.chip import format_command_chip
    from sase.plugin_commands.registry import discover_plugin_commands

    command_set = discover_plugin_commands()
    if not command_set.mounted and not command_set.problems:
        return None
    footer = RichText()
    footer.append("\n")
    footer.append("Plugin commands:", style="bold cyan")
    footer.append("\n")
    for record in command_set.mounted:
        try:
            summary = load_plugin_command(record).summary
        except PluginCommandLoadError as exc:
            cause = " ".join(exc.cause.split())
            footer.append("  ")
            footer.append("⚠ ", style="yellow")
            footer.append(f"sase {record.name}", style="bold red")
            footer.append(
                f"  failed to load from "
                f"{exc.distribution} {exc.version}: {cause}; see sase doctor"
            )
            footer.append("\n")
            continue
        provenance = f"({record.distribution} {record.version})"
        text = f"{summary} {provenance}" if summary else provenance
        footer.append("  ")
        footer.append(format_command_chip(record.name), style="bold magenta")
        footer.append(f"  {text}")
        footer.append("\n")
    for problem in command_set.problems:
        owners = ", ".join(problem.distributions)
        footer.append("  ")
        footer.append("⚠ ", style="yellow")
        footer.append(f"sase {problem.name}", style="bold red")
        footer.append(f"  {owners}: {problem.reason}")
        footer.append("\n")
    footer.append(_PLUGIN_COMMANDS_FOOTER_CLOSING, style="dim")
    footer.append("\n")
    return footer


def print_plugin_commands_footer(stream: TextIO) -> None:
    """Print the ``sase -H`` plugin footer, or nothing when there is none."""
    if stream_supports_color(stream):
        footer = format_colored_plugin_commands_footer()
        if footer is None:
            return
        console = Console(file=stream, force_terminal=True, highlight=False)
        console.print(footer, end="", soft_wrap=True)
        return
    footer_text = format_plugin_commands_footer()
    if footer_text:
        stream.write(footer_text)
