"""Walk the sase argparse tree into a JSON-serializable ``CompletionSpec``."""

from __future__ import annotations

import argparse

from sase import __version__
from sase.completion.kinds import resolve_value_kind
from sase.completion.model import (
    CommandSpec,
    CompletionSpec,
    OptionSpec,
    PositionalSpec,
)
from sase.completion.shorten import get_completion_summary, short_summary
from sase.main.parser import create_parser

_REPEATABLE_ACTION_TYPES = tuple(
    action_cls
    for action_cls in (
        getattr(argparse, "_AppendAction", None),
        getattr(argparse, "_AppendConstAction", None),
        getattr(argparse, "_ExtendAction", None),
    )
    if action_cls is not None
)
_REMAINDER_NARGS = (argparse.REMAINDER, "...")


def build_spec(parser: argparse.ArgumentParser | None = None) -> CompletionSpec:
    """Walk *parser* into a ``CompletionSpec``.

    Defaults to a fresh ``create_parser(only=None)`` -- the full command
    tree. Only reads the parser; never mutates it.
    """
    root_parser = create_parser(only=None) if parser is None else parser
    root = _build_command(
        root_parser, name="sase", path=(), aliases=(), choice_action=None
    )
    return CompletionSpec(prog="sase", version=__version__, root=root)


def _build_command(
    parser: argparse.ArgumentParser,
    *,
    name: str,
    path: tuple[str, ...],
    aliases: tuple[str, ...],
    choice_action: argparse.Action | None,
) -> CommandSpec:
    options: list[OptionSpec] = []
    positionals: list[PositionalSpec] = []
    subcommands: tuple[CommandSpec, ...] = ()
    default_child: str | None = None

    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            subcommands = _build_subcommands(action, parent_path=path)
            if any(child.name == "list" for child in subcommands):
                default_child = "list"
            continue
        if action.option_strings:
            options.append(_build_option(action, command_path=path))
        else:
            positionals.append(_build_positional(action, command_path=path))

    mutex_groups = tuple(
        tuple(member.dest for member in group._group_actions)
        for group in parser._mutually_exclusive_groups
        if group._group_actions
    )

    return CommandSpec(
        name=name,
        path=path,
        aliases=aliases,
        hidden=False,
        summary=_action_summary(choice_action),
        options=tuple(options),
        positionals=tuple(positionals),
        subcommands=subcommands,
        default_child=default_child,
        mutex_groups=mutex_groups,
    )


def _build_subcommands(
    subparsers_action: argparse._SubParsersAction,
    *,
    parent_path: tuple[str, ...],
) -> tuple[CommandSpec, ...]:
    """Collapse aliases and drop hidden subtrees under one subparsers action.

    argparse's ``aliases=`` puts several names in ``choices`` pointing at one
    parser object; they are grouped here by ``id(parser)``. A hidden command
    is one with no visible entry in ``_choices_actions`` at all -- either a
    literal ``help=SUPPRESS``, or (the codebase's stronger convention for
    commands that must not appear even as suppressed) no entry whatsoever.
    Such a subtree is skipped entirely, not merely flagged.
    """
    visible_choice_actions = {
        choice_action.dest: choice_action
        for choice_action in subparsers_action._choices_actions
        if choice_action.help != argparse.SUPPRESS
    }

    names_by_parser_id: dict[int, list[str]] = {}
    parser_by_id: dict[int, argparse.ArgumentParser] = {}
    for child_name, child_parser in subparsers_action.choices.items():
        child_id = id(child_parser)
        if child_id not in names_by_parser_id:
            names_by_parser_id[child_id] = []
            parser_by_id[child_id] = child_parser
        names_by_parser_id[child_id].append(child_name)

    commands: list[CommandSpec] = []
    for child_id, names in names_by_parser_id.items():
        primary = next((name for name in names if name in visible_choice_actions), None)
        if primary is None:
            continue
        aliases = tuple(sorted(name for name in names if name != primary))
        commands.append(
            _build_command(
                parser_by_id[child_id],
                name=primary,
                path=parent_path + (primary,),
                aliases=aliases,
                choice_action=visible_choice_actions[primary],
            )
        )

    commands.sort(key=lambda command: command.name)
    return tuple(commands)


def _build_option(
    action: argparse.Action, *, command_path: tuple[str, ...]
) -> OptionSpec:
    hidden = action.help == argparse.SUPPRESS
    choices = _resolved_choices(action)
    return OptionSpec(
        strings=tuple(action.option_strings),
        dest=action.dest,
        summary=_action_summary(action),
        takes_value=action.nargs != 0,
        repeatable=isinstance(action, _REPEATABLE_ACTION_TYPES),
        choices=choices,
        kind=None if choices is not None else resolve_value_kind(action, command_path),
        hidden=hidden,
    )


def _build_positional(
    action: argparse.Action, *, command_path: tuple[str, ...]
) -> PositionalSpec:
    choices = _resolved_choices(action)
    metavar = action.metavar if action.metavar is not None else action.dest
    return PositionalSpec(
        metavar=str(metavar),
        dest=action.dest,
        summary=_action_summary(action),
        nargs=action.nargs,
        choices=choices,
        kind=None if choices is not None else resolve_value_kind(action, command_path),
        is_remainder=action.nargs in _REMAINDER_NARGS,
    )


def _resolved_choices(action: argparse.Action) -> tuple[str, ...] | None:
    if action.choices is None:
        return None
    return tuple(str(choice) for choice in action.choices)


def _action_summary(action: argparse.Action | None) -> str:
    if action is None:
        return ""
    override = get_completion_summary(action)
    if override is not None:
        return override
    help_text = action.help
    if not help_text or help_text is argparse.SUPPRESS:
        return ""
    return short_summary(help_text)


__all__ = ["build_spec"]
