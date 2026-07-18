"""Argument parser creation for the SASE CLI tool."""

import argparse
import os
import sys
from dataclasses import dataclass
from typing import Any, TextIO

from rich.console import Console
from rich.text import Text

from sase.main.parser_ace import register_ace_parser, register_axe_parser
from sase.main.parser_agent import register_agent_parser
from sase.main.parser_artifact_file import register_artifact_file_parser
from sase.main.parser_bead import register_bead_parser
from sase.main.parser_chat import register_chat_parser
from sase.main.parser_commands import (
    register_changespec_parser,
    register_comments_parser,
    register_config_parser,
    register_file_history_parser,
    register_file_parser,
    register_logs_parser,
    register_lsp_parser,
    register_notify_parser,
    register_path_parser,
    register_plan_parser,
    register_questions_parser,
    register_revive_log_parser,
    register_run_parser,
)
from sase.main.parser_commit import (
    register_commit_parser,
    register_restore_parser,
    register_revert_parser,
)
from sase.main.parser_core import register_core_parser
from sase.main.parser_doctor import register_doctor_parser
from sase.main.parser_editor import register_editor_parser
from sase.main.parser_gate import register_gate_parser
from sase.main.parser_init import register_init_parser
from sase.main.parser_launch import register_launch_parser
from sase.main.parser_memory import register_memory_parser
from sase.main.parser_mobile import register_mobile_parser
from sase.main.parser_plugin import register_plugin_parser
from sase.main.parser_project import register_project_parser
from sase.main.parser_prompt import register_prompt_parser
from sase.main.parser_repo import register_repo_parser
from sase.main.parser_repro import register_repro_parser
from sase.main.parser_skills import register_skills_parser
from sase.main.parser_telemetry import register_telemetry_parser
from sase.main.parser_update import register_update_parser
from sase.main.parser_validate import register_validate_parser
from sase.main.parser_var import register_var_parser
from sase.main.parser_vcs import register_vcs_parser
from sase.main.parser_version import register_version_parser
from sase.main.parser_workspace import register_workspace_parser
from sase.main.parser_xprompt import register_xprompt_parser


@dataclass(frozen=True)
class _CompactRootCommand:
    name: str
    summary: str


_COMPACT_ROOT_COMMANDS: tuple[_CompactRootCommand, ...] = (
    _CompactRootCommand(
        "doctor",
        "Run read-only install, config, provider, project, and state diagnostics.",
    ),
    _CompactRootCommand(
        "init",
        "Check or initialize memory, repositories, and skills.",
    ),
    _CompactRootCommand(
        "version",
        "Show the exact SASE host, Rust core, and plugin packages loaded by this process.",
    ),
    _CompactRootCommand(
        "ace",
        "Open the interactive control surface for agents, projects, notifications, "
        "automation, and ChangeSpecs.",
    ),
    _CompactRootCommand(
        "run",
        "Launch or resume a coding-agent run from a prompt, xprompt, workflow, or history.",
    ),
    _CompactRootCommand(
        "prompt",
        "Inspect, search, replay, and curate previously submitted agent prompts.",
    ),
    _CompactRootCommand(
        "agent",
        "List, inspect, tag, or stop active and recent agent runs.",
    ),
    _CompactRootCommand(
        "memory",
        "Inspect loaded memory, review proposals, and audit long-term memory activity.",
    ),
    _CompactRootCommand(
        "bead",
        "Manage git-portable issues, dependencies, planning beads, and executable epics.",
    ),
    _CompactRootCommand(
        "project",
        "List enabled projects and manage disabled work.",
    ),
    _CompactRootCommand(
        "vcs",
        "Inspect primary, linked, and SDD repos, or show their commit timeline.",
    ),
    _CompactRootCommand(
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


class _CompactRootHelpAction(argparse.Action):
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
        _print_compact_root_help(parser, sys.stdout)
        parser.exit()


class _FullRootHelpAction(argparse.Action):
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


def _root_subparser_action(
    parser: argparse.ArgumentParser,
) -> argparse._SubParsersAction:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    msg = "root parser has no subparser action"
    raise AssertionError(msg)


def _validated_compact_root_commands(
    parser: argparse.ArgumentParser,
) -> tuple[_CompactRootCommand, ...]:
    subparser_action = _root_subparser_action(parser)
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


def _format_compact_root_help(parser: argparse.ArgumentParser) -> str:
    commands = _validated_compact_root_commands(parser)
    command_width = max(len(command.name) for command in commands)
    command_rows = [
        f"  {command.name:<{command_width}}  {command.summary}" for command in commands
    ]
    example_rows = [f"  {example}" for example in _COMPACT_ROOT_EXAMPLES]
    return "\n".join(
        [
            "usage: sase [-h] [-H] <command> [args...]",
            "",
            "SASE - Structured Agentic Software Engineering",
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


def _print_compact_root_help(parser: argparse.ArgumentParser, stream: TextIO) -> None:
    if _stream_supports_color(stream):
        console = Console(file=stream, force_terminal=True, highlight=False)
        console.print(_format_colored_compact_root_help(parser), end="", soft_wrap=True)
        return

    parser._print_message(_format_compact_root_help(parser), stream)


def _stream_supports_color(stream: TextIO) -> bool:
    if os.environ.get("NO_COLOR") is not None or os.environ.get("TERM") == "dumb":
        return False

    isatty = getattr(stream, "isatty", None)
    return bool(isatty is not None and isatty())


def _format_colored_compact_root_help(parser: argparse.ArgumentParser) -> Text:
    commands = _validated_compact_root_commands(parser)
    command_width = max(len(command.name) for command in commands)
    help_text = Text()

    help_text.append("usage:", style="bold dim")
    help_text.append(" sase [-h] [-H] <command> [args...]", style="dim")
    help_text.append("\n\n")
    help_text.append("SASE - Structured Agentic Software Engineering", style="bold")
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


def _sort_subcommand_help(parser: argparse.ArgumentParser) -> None:
    """Sort every subparser action by command name for stable help output."""
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue

        sorted_choices = dict(sorted(action.choices.items()))
        action.choices.clear()
        action.choices.update(sorted_choices)
        action._choices_actions.sort(key=lambda choice_action: choice_action.dest)

        seen_child_parsers: set[int] = set()
        for child_parser in action.choices.values():
            child_id = id(child_parser)
            if child_id in seen_child_parsers:
                continue
            seen_child_parsers.add(child_id)
            _sort_subcommand_help(child_parser)


def _copy_parser_defaults(
    source_parser: argparse.ArgumentParser,
    target_parser: argparse.ArgumentParser,
) -> None:
    """Copy defaults that parsing *source_parser* would add to a namespace."""
    defaults = dict(source_parser._defaults)
    for action in source_parser._actions:
        if action.dest in (argparse.SUPPRESS, "help"):
            continue
        if isinstance(action, argparse._HelpAction):
            continue
        if isinstance(action, argparse._SubParsersAction):
            continue
        if not action.option_strings:
            continue
        if action.default is argparse.SUPPRESS:
            continue
        defaults.setdefault(action.dest, action.default)

    if defaults:
        target_parser.set_defaults(**defaults)


# Private namespace attribute recording the command group (e.g. ``sase agent``)
# that was implicitly defaulted to its ``list`` child because the user invoked
# the group without choosing a subcommand. Absent or ``None`` means no implicit
# delegation happened, so no runtime notice should be printed.
_DEFAULT_LIST_GROUP_DEST = "_default_list_group"


def _default_list_subcommands(parser: argparse.ArgumentParser) -> None:
    """Default command groups with an exact ``list`` child to that child."""
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue

        list_parser = action.choices.get("list")
        if list_parser is not None and action.dest != argparse.SUPPRESS:
            action.required = False
            parser.set_defaults(**{action.dest: "list"})
            _copy_parser_defaults(list_parser, parser)

            # Choosing any explicit child clears the defaulted marker, so an
            # explicit ``list`` (or non-``list``) command never looks defaulted.
            seen_choice_parsers: set[int] = set()
            for child_parser in action.choices.values():
                if id(child_parser) in seen_choice_parsers:
                    continue
                seen_choice_parsers.add(id(child_parser))
                child_parser.set_defaults(**{_DEFAULT_LIST_GROUP_DEST: None})

            # Set last so it wins on the parent: a bare invocation of this group
            # leaves this marker untouched and identifies the omitted group.
            parser.set_defaults(**{_DEFAULT_LIST_GROUP_DEST: parser.prog})

        seen_child_parsers: set[int] = set()
        for child_parser in action.choices.values():
            child_id = id(child_parser)
            if child_id in seen_child_parsers:
                continue
            seen_child_parsers.add(child_id)
            _default_list_subcommands(child_parser)


def default_list_delegation_notice(args: argparse.Namespace) -> str | None:
    """Return the delegation notice for a bare list-defaulted group, if any.

    When a command group with an exact ``list`` child is invoked without a
    subcommand, the parser records the group path in a private namespace
    attribute. This returns a short notice explaining the implicit delegation,
    or ``None`` when an explicit subcommand was chosen.
    """
    group = getattr(args, _DEFAULT_LIST_GROUP_DEST, None)
    if not group:
        return None
    return f"No subcommand provided for '{group}'; delegating to '{group} list'."


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        add_help=False,
        description="SASE - Structured Agentic Software Engineering",
        prog="sase",
    )
    parser.add_argument(
        "-h",
        "--help",
        action=_CompactRootHelpAction,
        help="show compact help and exit",
    )
    parser.add_argument(
        "-H",
        "--full-help",
        action=_FullRootHelpAction,
        help="show full command inventory and exit",
    )

    # Top-level subparsers
    top_level_subparsers = parser.add_subparsers(
        dest="command", help="Available commands", required=True
    )

    # =========================================================================
    # TOP-LEVEL SUBCOMMANDS (keep sorted alphabetically)
    # =========================================================================
    register_ace_parser(top_level_subparsers)
    register_agent_parser(top_level_subparsers)
    register_artifact_file_parser(top_level_subparsers)
    register_axe_parser(top_level_subparsers)
    register_bead_parser(top_level_subparsers)
    register_changespec_parser(top_level_subparsers)
    register_chat_parser(top_level_subparsers)
    register_comments_parser(top_level_subparsers)
    register_commit_parser(top_level_subparsers)
    register_config_parser(top_level_subparsers)
    register_core_parser(top_level_subparsers)
    register_doctor_parser(top_level_subparsers)
    register_editor_parser(top_level_subparsers)
    register_file_parser(top_level_subparsers)
    register_file_history_parser(top_level_subparsers)
    register_gate_parser(top_level_subparsers)
    register_init_parser(top_level_subparsers)
    register_launch_parser(top_level_subparsers)
    register_logs_parser(top_level_subparsers)
    register_lsp_parser(top_level_subparsers)
    register_memory_parser(top_level_subparsers)
    register_mobile_parser(top_level_subparsers)
    register_notify_parser(top_level_subparsers)
    register_path_parser(top_level_subparsers)
    register_plan_parser(top_level_subparsers)
    register_plugin_parser(top_level_subparsers)
    register_project_parser(top_level_subparsers)
    register_prompt_parser(top_level_subparsers)
    register_questions_parser(top_level_subparsers)
    register_repo_parser(top_level_subparsers)
    register_repro_parser(top_level_subparsers)
    register_restore_parser(top_level_subparsers)
    register_revert_parser(top_level_subparsers)
    register_revive_log_parser(top_level_subparsers)
    register_run_parser(top_level_subparsers)
    register_skills_parser(top_level_subparsers)
    register_telemetry_parser(top_level_subparsers)
    register_update_parser(top_level_subparsers)
    register_validate_parser(top_level_subparsers)
    register_var_parser(top_level_subparsers)
    register_vcs_parser(top_level_subparsers)
    register_version_parser(top_level_subparsers)
    register_workspace_parser(top_level_subparsers)
    register_xprompt_parser(top_level_subparsers)

    _sort_subcommand_help(parser)
    _default_list_subcommands(parser)
    return parser
