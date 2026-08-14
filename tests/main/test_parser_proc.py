"""Parser wiring and help tests for the ``sase proc`` command surface."""

from __future__ import annotations

import pytest

from sase.main.parser import _DEFAULT_LIST_GROUP_DEST, create_parser
from tests.main.parser_help_helpers import flat_help, help_subcommand_rows, parser_for


def test_proc_group_help_lists_sorted_subcommands() -> None:
    """``sase proc --help`` advertises its four commands in order."""
    proc_parser = parser_for(("sase", "proc"))
    help_text = proc_parser.format_help()
    expected = {"kill", "list", "run", "show"}

    assert help_subcommand_rows(help_text, expected) == sorted(expected)
    assert "{kill,list,run,show}" in help_text
    assert "defaults to `sase proc list`" in flat_help(help_text)


def test_bare_proc_defaults_to_list_and_records_delegation() -> None:
    """A bare ``sase proc`` parses as ``list`` and marks the delegation."""
    parser = create_parser()

    bare = parser.parse_args(["proc"])
    explicit = parser.parse_args(["proc", "list"])

    assert bare.command == "proc"
    assert bare.proc_subcommand == "list"
    assert getattr(bare, _DEFAULT_LIST_GROUP_DEST) == "sase proc"
    assert getattr(explicit, _DEFAULT_LIST_GROUP_DEST) is None


def test_legacy_task_command_alias_parses_like_proc() -> None:
    """The old ``sase task`` spelling still routes to the proc parser."""
    parser = create_parser()

    bare = parser.parse_args(["task"])
    explicit = parser.parse_args(["task", "list"])

    assert bare.command == "task"
    assert bare.proc_subcommand == "list"
    assert explicit.command == "task"
    assert explicit.proc_subcommand == "list"
    assert getattr(explicit, _DEFAULT_LIST_GROUP_DEST) is None


def test_legacy_task_facade_modules_export_old_symbols() -> None:
    """Old import paths remain available as proc facades."""
    from sase.main.parser_proc import PROC_STATUS_CHOICES, register_proc_parser
    from sase.main.parser_task import TASK_STATUS_CHOICES, register_task_parser
    from sase.main.proc_handler import handle_proc_command
    from sase.main.proc_render import proc_detail, proc_kill_json, proc_show_json
    from sase.main.task_handler import handle_task_command
    from sase.main.task_render import task_detail, task_kill_json, task_show_json

    assert register_task_parser is register_proc_parser
    assert TASK_STATUS_CHOICES is PROC_STATUS_CHOICES
    assert handle_task_command is handle_proc_command
    assert task_detail is proc_detail
    assert task_kill_json is proc_kill_json
    assert task_show_json is proc_show_json


def test_proc_list_help_documents_every_filter_and_examples() -> None:
    """Each documented ``list`` filter keeps a short alias and a metavar."""
    list_parser = parser_for(("sase", "proc", "list"))
    list_help = flat_help(list_parser.format_help())

    assert "usage: sase proc list" in list_help
    assert "-a, --all" in list_help
    assert "-d, --detached" in list_help
    assert "-j, --json" in list_help
    assert "-r, --running" in list_help
    for short, long, metavar in (
        ("-k", "--kind", "KIND"),
        ("-n", "--limit", "N"),
        ("-p", "--project", "NAME"),
        ("-q", "--query", "TEXT"),
        ("-s", "--session", "REF"),
        ("-S", "--status", "STATUS"),
        ("-t", "--tag", "TAG"),
    ):
        action = list_parser._option_string_actions[long]
        assert list_parser._option_string_actions[short] is action
        assert action.metavar == metavar
    assert "procs.history_limit" in list_help
    assert "sase proc list --tag epic --json" in list_help


def test_proc_run_help_documents_command_and_examples() -> None:
    """``sase proc run --help`` explains the ``--`` command and attribution."""
    run_help = flat_help(parser_for(("sase", "proc", "run")).format_help())

    assert "usage: sase proc run" in run_help
    assert "-- COMMAND ..." in run_help
    assert "-w, --wait" in run_help
    assert "-q, --quiet" in run_help
    assert "-d, --detached" in run_help
    assert "attribution, not delegation" in run_help
    assert "sase proc run -- just check" in run_help


def test_proc_kill_help_documents_prefix_and_json() -> None:
    """``sase proc kill --help`` describes prefix resolution and JSON."""
    kill_help = flat_help(parser_for(("sase", "proc", "kill")).format_help())

    assert "usage: sase proc kill" in kill_help
    assert "unique id prefix" in kill_help
    assert "-j, --json" in kill_help
    assert "sase proc kill k7m2" in kill_help


def test_proc_show_help_documents_log_and_follow_options() -> None:
    """``sase proc show --help`` covers the log tail, format, and follow."""
    show_parser = parser_for(("sase", "proc", "show"))
    show_help = flat_help(show_parser.format_help())

    assert "usage: sase proc show" in show_help
    assert "-A, --all-lines" in show_help
    assert "-F, --follow" in show_help
    assert "-o, --output-only" in show_help
    assert (
        show_parser._option_string_actions["-l"]
        is show_parser._option_string_actions["--log-lines"]
    )
    assert (
        show_parser._option_string_actions["-f"]
        is show_parser._option_string_actions["--format"]
    )
    assert "sase proc show k7m2 --follow" in show_help


def test_proc_run_command_positional_does_not_shadow_the_command_dest() -> None:
    """The run positional must not overwrite the top-level ``command`` dest."""
    args = create_parser().parse_args(["proc", "run", "--", "just", "check"])

    assert args.command == "proc"
    assert args.proc_subcommand == "run"
    assert args.proc_command == ["--", "just", "check"]


def test_proc_run_options_precede_the_command_separator() -> None:
    """Options before ``--`` bind to ``run``, not to the launched command."""
    args = create_parser().parse_args(
        ["proc", "run", "-w", "-t", "epic", "-t", "launch", "--", "ls", "-la"]
    )

    assert args.wait is True
    assert args.tag == ["epic", "launch"]
    assert args.proc_command == ["--", "ls", "-la"]


def test_proc_list_status_filter_repeats_and_validates() -> None:
    """``-S`` accumulates and only accepts real proc statuses."""
    args = create_parser().parse_args(["proc", "list", "-S", "error", "-S", "killed"])

    assert args.status == ["error", "killed"]


def test_proc_list_kind_filter_repeats_and_detached_is_a_shorthand() -> None:
    """Kinds compose, and ``--detached`` is represented independently."""
    args = create_parser().parse_args(
        ["proc", "list", "-k", "command", "-k", "tui", "--detached"]
    )

    assert args.kind == ["command", "tui"]
    assert args.detached is True


def test_proc_run_detached_and_session_are_mutually_exclusive() -> None:
    """A global detached proc cannot also carry session attribution."""
    parser = create_parser()

    with pytest.raises(SystemExit) as exit_info:
        parser.parse_args(
            ["proc", "run", "--detached", "--session", "latest", "--", "true"]
        )

    assert exit_info.value.code == 2


def test_proc_status_choices_match_the_store_lifecycle() -> None:
    """The parser's inlined status list must not drift from the store's."""
    from sase.main.parser_proc import PROC_STATUS_CHOICES
    from sase.procs import ACTIVE_PROC_STATUSES, TERMINAL_PROC_STATUSES

    assert set(PROC_STATUS_CHOICES) == ACTIVE_PROC_STATUSES | TERMINAL_PROC_STATUSES


def test_proc_kind_choices_match_the_store_kinds() -> None:
    """The parser's inlined kind list must not drift from the store's."""
    from sase.main.parser_proc import PROC_KIND_CHOICES
    from sase.procs import PROC_KINDS

    assert set(PROC_KIND_CHOICES) == PROC_KINDS
