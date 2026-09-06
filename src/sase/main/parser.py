"""Argument parser creation for the SASE CLI tool."""

from __future__ import annotations

import argparse

from .parser_gettext import (
    _GETTEXT_ENV_KEYS,
    _ORIGINAL_GETTEXT_FIND,
    cached_gettext_find,
    gettext_languages_key,
    install_memoized_gettext_find,
    memoized_gettext_find,
)
from .parser_registry import (
    _COMMAND_REGISTRARS,
    _RegistrarSpec,
    parser_only_hint,
    register_command_parsers,
)
from .parser_root_args import (
    _BEAD_NOTE_VALUE_OPTIONS,
    _GLOBAL_VALUE_OPTIONS,
    _NamespaceT,
    _OBSOLETE_DETACHED_PROC_MESSAGE,
    _PROC_ALIASES,
    _PROC_SUBCOMMANDS_WITH_LEGACY_DETACHED,
    _VALIDATION_FORMATTER,
    SaseArgumentParser,
    is_bead_note_args,
    normalize_bead_note_args,
    root_command_index,
    shared_validation_formatter,
    uses_obsolete_detached_proc_option,
)
from .parser_root_defaults import (
    _DEFAULT_LIST_GROUP_DEST,
    copy_parser_defaults,
    default_list_subcommands,
    default_list_delegation_notice,
    sort_subcommand_help,
)
from .parser_root_help import (
    _COMPACT_GLOBAL_OPTIONS,
    _COMPACT_GLOBAL_OPTION_EXAMPLE,
    _COMPACT_ROOT_COMMANDS,
    _COMPACT_ROOT_EXAMPLES,
    _COMPACT_ROOT_USAGE,
    CompactRootCommand,
    CompactRootHelpAction,
    FullRootHelpAction,
    compact_global_option_rows,
    format_colored_compact_root_help,
    format_compact_root_help,
    print_compact_root_help,
    root_subparser_action,
    stream_supports_color,
    validated_compact_root_commands,
)

install_memoized_gettext_find()

_SaseArgumentParser = SaseArgumentParser
_cached_gettext_find = cached_gettext_find
_compact_global_option_rows = compact_global_option_rows
_copy_parser_defaults = copy_parser_defaults
_default_list_subcommands = default_list_subcommands
_format_colored_compact_root_help = format_colored_compact_root_help
_format_compact_root_help = format_compact_root_help
_gettext_languages_key = gettext_languages_key
_is_bead_note_args = is_bead_note_args
_memoized_gettext_find = memoized_gettext_find
_normalize_bead_note_args = normalize_bead_note_args
_print_compact_root_help = print_compact_root_help
_register_command_parsers = register_command_parsers
_root_command_index = root_command_index
_root_subparser_action = root_subparser_action
_shared_validation_formatter = shared_validation_formatter
_sort_subcommand_help = sort_subcommand_help
_stream_supports_color = stream_supports_color
_uses_obsolete_detached_proc_option = uses_obsolete_detached_proc_option
_validated_compact_root_commands = validated_compact_root_commands
_CompactRootCommand = CompactRootCommand
_CompactRootHelpAction = CompactRootHelpAction
_FullRootHelpAction = FullRootHelpAction

__all__ = (
    "_BEAD_NOTE_VALUE_OPTIONS",
    "_COMMAND_REGISTRARS",
    "_COMPACT_GLOBAL_OPTIONS",
    "_COMPACT_GLOBAL_OPTION_EXAMPLE",
    "_COMPACT_ROOT_COMMANDS",
    "_COMPACT_ROOT_EXAMPLES",
    "_COMPACT_ROOT_USAGE",
    "_DEFAULT_LIST_GROUP_DEST",
    "_GETTEXT_ENV_KEYS",
    "_GLOBAL_VALUE_OPTIONS",
    "_NamespaceT",
    "_OBSOLETE_DETACHED_PROC_MESSAGE",
    "_ORIGINAL_GETTEXT_FIND",
    "_PROC_ALIASES",
    "_PROC_SUBCOMMANDS_WITH_LEGACY_DETACHED",
    "_RegistrarSpec",
    "_SaseArgumentParser",
    "_VALIDATION_FORMATTER",
    "_cached_gettext_find",
    "_compact_global_option_rows",
    "_copy_parser_defaults",
    "_default_list_subcommands",
    "_format_colored_compact_root_help",
    "_format_compact_root_help",
    "_gettext_languages_key",
    "_is_bead_note_args",
    "_memoized_gettext_find",
    "_normalize_bead_note_args",
    "_print_compact_root_help",
    "_register_command_parsers",
    "_root_command_index",
    "_root_subparser_action",
    "_shared_validation_formatter",
    "_sort_subcommand_help",
    "_stream_supports_color",
    "_uses_obsolete_detached_proc_option",
    "_validated_compact_root_commands",
    "create_parser",
    "default_list_delegation_notice",
    "parser_only_hint",
)


def create_parser(*, only: str | None = None) -> argparse.ArgumentParser:
    """Create the full argument parser, or only one top-level command tree."""
    parser = SaseArgumentParser(
        add_help=False,
        description="SASE - Structured Agentic Software Engineering",
        prog="sase",
    )
    parser.add_argument(
        "-h",
        "--help",
        action=CompactRootHelpAction,
        help="show compact help and exit",
    )
    parser.add_argument(
        "-H",
        "--full-help",
        action=FullRootHelpAction,
        help="show full command inventory and exit",
    )
    from .global_options import register_global_feature_flag_options

    register_global_feature_flag_options(parser)

    top_level_subparsers = parser.add_subparsers(
        dest="command", help="Available commands", required=True
    )

    register_command_parsers(top_level_subparsers, only=only)

    sort_subcommand_help(parser)
    default_list_subcommands(parser)
    return parser
