"""Parser wiring and help tests for the ``sase task`` command surface."""

from __future__ import annotations

import pytest

from sase.main.parser import _DEFAULT_LIST_GROUP_DEST, create_parser
from tests.main.parser_help_helpers import flat_help, help_subcommand_rows, parser_for


def test_task_group_help_lists_sorted_subcommands() -> None:
    """``sase task --help`` advertises its four commands in order."""
    task_parser = parser_for(("sase", "task"))
    help_text = task_parser.format_help()
    expected = {"kill", "list", "run", "show"}

    assert help_subcommand_rows(help_text, expected) == sorted(expected)
    assert "{kill,list,run,show}" in help_text
    assert "defaults to `sase task list`" in flat_help(help_text)


def test_bare_task_defaults_to_list_and_records_delegation() -> None:
    """A bare ``sase task`` parses as ``list`` and marks the delegation."""
    parser = create_parser()

    bare = parser.parse_args(["task"])
    explicit = parser.parse_args(["task", "list"])

    assert bare.command == "task"
    assert bare.task_subcommand == "list"
    assert getattr(bare, _DEFAULT_LIST_GROUP_DEST) == "sase task"
    assert getattr(explicit, _DEFAULT_LIST_GROUP_DEST) is None


def test_task_list_help_documents_every_filter_and_examples() -> None:
    """Each documented ``list`` filter keeps a short alias and a metavar."""
    list_parser = parser_for(("sase", "task", "list"))
    list_help = flat_help(list_parser.format_help())

    assert "usage: sase task list" in list_help
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
    assert "tasks.history_limit" in list_help
    assert "sase task list --tag epic --json" in list_help


def test_task_run_help_documents_command_and_examples() -> None:
    """``sase task run --help`` explains the ``--`` command and attribution."""
    run_help = flat_help(parser_for(("sase", "task", "run")).format_help())

    assert "usage: sase task run" in run_help
    assert "-- COMMAND ..." in run_help
    assert "-w, --wait" in run_help
    assert "-q, --quiet" in run_help
    assert "-d, --detached" in run_help
    assert "attribution, not delegation" in run_help
    assert "sase task run -- just check" in run_help


def test_task_kill_help_documents_prefix_and_json() -> None:
    """``sase task kill --help`` describes prefix resolution and JSON."""
    kill_help = flat_help(parser_for(("sase", "task", "kill")).format_help())

    assert "usage: sase task kill" in kill_help
    assert "unique id prefix" in kill_help
    assert "-j, --json" in kill_help
    assert "sase task kill k7m2" in kill_help


def test_task_show_help_documents_log_and_follow_options() -> None:
    """``sase task show --help`` covers the log tail, format, and follow."""
    show_parser = parser_for(("sase", "task", "show"))
    show_help = flat_help(show_parser.format_help())

    assert "usage: sase task show" in show_help
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
    assert "sase task show k7m2 --follow" in show_help


def test_task_run_command_positional_does_not_shadow_the_command_dest() -> None:
    """The run positional must not overwrite the top-level ``command`` dest."""
    args = create_parser().parse_args(["task", "run", "--", "just", "check"])

    assert args.command == "task"
    assert args.task_subcommand == "run"
    assert args.task_command == ["--", "just", "check"]


def test_task_run_options_precede_the_command_separator() -> None:
    """Options before ``--`` bind to ``run``, not to the launched command."""
    args = create_parser().parse_args(
        ["task", "run", "-w", "-t", "epic", "-t", "launch", "--", "ls", "-la"]
    )

    assert args.wait is True
    assert args.tag == ["epic", "launch"]
    assert args.task_command == ["--", "ls", "-la"]


def test_task_list_status_filter_repeats_and_validates() -> None:
    """``-S`` accumulates and only accepts real task statuses."""
    args = create_parser().parse_args(["task", "list", "-S", "error", "-S", "killed"])

    assert args.status == ["error", "killed"]


def test_task_list_kind_filter_repeats_and_detached_is_a_shorthand() -> None:
    """Kinds compose, and ``--detached`` is represented independently."""
    args = create_parser().parse_args(
        ["task", "list", "-k", "command", "-k", "tui", "--detached"]
    )

    assert args.kind == ["command", "tui"]
    assert args.detached is True


def test_task_run_detached_and_session_are_mutually_exclusive() -> None:
    """A global detached task cannot also carry session attribution."""
    parser = create_parser()

    with pytest.raises(SystemExit) as exit_info:
        parser.parse_args(
            ["task", "run", "--detached", "--session", "latest", "--", "true"]
        )

    assert exit_info.value.code == 2


def test_task_status_choices_match_the_store_lifecycle() -> None:
    """The parser's inlined status list must not drift from the store's."""
    from sase.main.parser_task import TASK_STATUS_CHOICES
    from sase.procs import ACTIVE_PROC_STATUSES, TERMINAL_PROC_STATUSES

    assert set(TASK_STATUS_CHOICES) == ACTIVE_PROC_STATUSES | TERMINAL_PROC_STATUSES


def test_task_kind_choices_match_the_store_kinds() -> None:
    """The parser's inlined kind list must not drift from the store's."""
    from sase.main.parser_task import TASK_KIND_CHOICES
    from sase.procs import PROC_KINDS

    assert set(TASK_KIND_CHOICES) == PROC_KINDS
