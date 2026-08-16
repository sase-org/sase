"""Argument parser creation for the SASE CLI tool."""

import argparse
import functools
import gettext
from collections.abc import Iterable, Sequence
from importlib import import_module
import os
import sys
from dataclasses import dataclass
from typing import Any, overload, TextIO, TypeVar

from rich.console import Console
from rich.text import Text

_NamespaceT = TypeVar("_NamespaceT")

_RegistrarSpec = tuple[str, str]

_GETTEXT_ENV_KEYS = ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")
_ORIGINAL_GETTEXT_FIND = gettext.find


def _gettext_languages_key(languages: object) -> tuple[str, ...] | None:
    if languages is None:
        return None
    if isinstance(languages, str):
        return (languages,)
    if isinstance(languages, Iterable):
        return tuple(str(language) for language in languages)
    return (str(languages),)


@functools.lru_cache(maxsize=512)
def _cached_gettext_find(
    domain: str,
    localedir: str | None,
    languages: tuple[str, ...] | None,
    locale_env: tuple[str | None, ...] | None,
    all_matches: bool,
) -> str | list[str] | None:
    del locale_env
    result = _ORIGINAL_GETTEXT_FIND(
        domain,
        localedir,
        None if languages is None else list(languages),
        all=all_matches,
    )
    if isinstance(result, list):
        return list(result)
    return result


def _memoized_gettext_find(
    domain: str,
    localedir: str | None = None,
    languages: object = None,
    all: bool = False,  # noqa: A002 - mirrors gettext.find's public signature.
) -> str | list[str] | None:
    """Memoize locale catalog discovery while preserving gettext's inputs."""

    language_key = _gettext_languages_key(languages)
    locale_env = (
        tuple(os.environ.get(key) for key in _GETTEXT_ENV_KEYS)
        if language_key is None
        else None
    )
    result = _cached_gettext_find(
        domain,
        localedir,
        language_key,
        locale_env,
        bool(all),
    )
    if isinstance(result, list):
        return list(result)
    return result


gettext.find = _memoized_gettext_find  # type: ignore[assignment]

# Keep the command inventory and registrar routing in one lazy registry. Values are
# module/function names instead of imported callables so ``create_parser(only=...)``
# does not import unrelated command trees. Aliases share one registrar and are
# deduplicated when the full parser is built.
_COMMAND_REGISTRARS: dict[str, _RegistrarSpec] = {
    "ace": ("sase.main.parser_ace", "register_ace_parser"),
    "agent": ("sase.main.parser_agent", "register_agent_parser"),
    "agent-cli": ("sase.main.parser_agent_cli", "register_agent_cli_parser"),
    "artifact": ("sase.main.parser_artifact", "register_artifact_parser"),
    "artifact-file": ("sase.main.parser_artifact", "register_artifact_parser"),
    "axe": ("sase.main.parser_ace", "register_axe_parser"),
    "bead": ("sase.main.parser_bead", "register_bead_parser"),
    # Legacy command alias for the patch parser.
    "changespec": (
        "sase.main.parser_patch",
        "register_patch_parser",
    ),
    "chat": ("sase.main.parser_chat", "register_chat_parser"),
    "comments": ("sase.main.parser_commands", "register_comments_parser"),
    "commit": ("sase.main.parser_commit", "register_commit_parser"),
    "config": ("sase.main.parser_commands", "register_config_parser"),
    "core": ("sase.main.parser_core", "register_core_parser"),
    "doctor": ("sase.main.parser_doctor", "register_doctor_parser"),
    "editor": ("sase.main.parser_editor", "register_editor_parser"),
    "file": ("sase.main.parser_commands", "register_file_parser"),
    "file-history": ("sase.main.parser_commands", "register_file_history_parser"),
    "file-hook": ("sase.main.parser_file_hook", "register_file_hook_parser"),
    "gate": ("sase.main.parser_gate", "register_gate_parser"),
    "init": ("sase.main.parser_init", "register_init_parser"),
    "launch": ("sase.main.parser_launch", "register_launch_parser"),
    "logs": ("sase.main.parser_commands", "register_logs_parser"),
    "lsp": ("sase.main.parser_commands", "register_lsp_parser"),
    "memory": ("sase.main.parser_memory", "register_memory_parser"),
    "mobile": ("sase.main.parser_mobile", "register_mobile_parser"),
    "monitor": ("sase.main.parser_monitor", "register_monitor_parser"),
    "notify": ("sase.main.parser_commands", "register_notify_parser"),
    "path": ("sase.main.parser_commands", "register_path_parser"),
    "patch": ("sase.main.parser_patch", "register_patch_parser"),
    "plan": ("sase.main.parser_plan", "register_plan_parser"),
    "plugin": ("sase.main.parser_plugin", "register_plugin_parser"),
    "proc": ("sase.main.parser_proc", "register_proc_parser"),
    "project": ("sase.main.parser_project", "register_project_parser"),
    "prompt": ("sase.main.parser_prompt", "register_prompt_parser"),
    "questions": ("sase.main.parser_commands", "register_questions_parser"),
    "repo": ("sase.main.parser_repo", "register_repo_parser"),
    "repro": ("sase.main.parser_repro", "register_repro_parser"),
    "restore": ("sase.main.parser_commit", "register_restore_parser"),
    "revert": ("sase.main.parser_commit", "register_revert_parser"),
    "revive-log": ("sase.main.parser_commands", "register_revive_log_parser"),
    "run": ("sase.main.parser_commands", "register_run_parser"),
    "skill": ("sase.main.parser_skills", "register_skills_parser"),
    "stitch": ("sase.main.parser_stitch", "register_stitch_parser"),
    # Legacy command alias for the proc parser.
    "task": ("sase.main.parser_proc", "register_proc_parser"),
    "telemetry": ("sase.main.parser_telemetry", "register_telemetry_parser"),
    "update": ("sase.main.parser_update", "register_update_parser"),
    "validate": ("sase.main.parser_validate", "register_validate_parser"),
    "var": ("sase.main.parser_var", "register_var_parser"),
    # Legacy command alias for the stitch parser.
    "vcs": ("sase.main.parser_stitch", "register_stitch_parser"),
    "version": ("sase.main.parser_version", "register_version_parser"),
    "workspace": ("sase.main.parser_workspace", "register_workspace_parser"),
    "xprompt": ("sase.main.parser_xprompt", "register_xprompt_parser"),
}

_OBSOLETE_DETACHED_PROC_MESSAGE = (
    "all procs are detached; remove --detached (use --session none for no attribution)."
)
_PROC_ALIASES = frozenset({"proc", "task"})
_PROC_SUBCOMMANDS_WITH_LEGACY_DETACHED = frozenset({"list", "run"})


class _SaseArgumentParser(argparse.ArgumentParser):
    """Root parser with cross-option validation that argparse cannot express."""

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
        if _uses_obsolete_detached_proc_option(raw_args):
            self.exit(2, f"{_OBSOLETE_DETACHED_PROC_MESSAGE}\n")
        parsed = super().parse_args(raw_args, namespace)
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
        return parsed


def _uses_obsolete_detached_proc_option(argv: Sequence[str]) -> bool:
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
        "Check or initialize config, memory, repositories, and skills.",
    ),
    _CompactRootCommand(
        "version",
        "Show the exact SASE host, Rust core, and plugin packages loaded by this process.",
    ),
    _CompactRootCommand(
        "ace",
        "Open the interactive control surface for agents, projects, notifications, "
        "automation, and Patches.",
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
        "patch",
        "Inspect and maintain Patch lifecycle records, refs, and delta metadata.",
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
        "stitch",
        "Dispatch a commit, proposal, or PR; show the stitch timeline.",
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
        if not action.option_strings and action.nargs not in {"?", "*"}:
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


def parser_only_hint(argv: Sequence[str]) -> str | None:
    """Return a safe narrow-parser hint for a complete command-line argv."""
    if len(argv) < 2:
        return None

    candidate = argv[1]
    if candidate.startswith("-") or candidate not in _COMMAND_REGISTRARS:
        return None
    return candidate


def _register_command_parsers(
    subparsers: argparse._SubParsersAction,
    *,
    only: str | None,
) -> None:
    specs: Iterable[_RegistrarSpec]
    full_registrars: dict[str, Any] | None = None
    if only is None:
        from sase.main.parser_full_registrars import COMMAND_REGISTRARS_BY_NAME

        specs = _COMMAND_REGISTRARS.values()
        full_registrars = COMMAND_REGISTRARS_BY_NAME
    else:
        try:
            specs = (_COMMAND_REGISTRARS[only],)
        except KeyError:
            raise ValueError(f"unknown top-level command: {only}") from None

    registered: set[_RegistrarSpec] = set()
    for spec in specs:
        if spec in registered:
            continue
        registered.add(spec)
        module_name, registrar_name = spec
        if full_registrars is None:
            registrar = getattr(import_module(module_name), registrar_name)
        else:
            registrar = full_registrars[registrar_name]
        registrar(subparsers)


def create_parser(*, only: str | None = None) -> argparse.ArgumentParser:
    """Create the full argument parser, or only one top-level command tree."""
    parser = _SaseArgumentParser(
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

    _register_command_parsers(top_level_subparsers, only=only)

    _sort_subcommand_help(parser)
    _default_list_subcommands(parser)
    return parser
