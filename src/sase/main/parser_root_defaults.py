"""Parser tree post-processing helpers."""

from __future__ import annotations

import argparse


def sort_subcommand_help(parser: argparse.ArgumentParser) -> None:
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
            sort_subcommand_help(child_parser)


def copy_parser_defaults(
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


def default_list_subcommands(parser: argparse.ArgumentParser) -> None:
    """Default command groups with an exact ``list`` child to that child."""
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue

        list_parser = action.choices.get("list")
        if list_parser is not None and action.dest != argparse.SUPPRESS:
            action.required = False
            parser.set_defaults(**{action.dest: "list"})
            copy_parser_defaults(list_parser, parser)

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
            default_list_subcommands(child_parser)


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
