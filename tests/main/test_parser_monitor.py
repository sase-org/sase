"""Parser wiring and help tests for the ``sase monitor`` command surface."""

from __future__ import annotations

import pytest

from sase.main.parser import _DEFAULT_LIST_GROUP_DEST, create_parser
from tests.main.parser_help_helpers import flat_help, help_subcommand_rows, parser_for


def test_monitor_group_help_lists_sorted_visible_subcommands() -> None:
    """``sase monitor --help`` advertises its public commands, hiding ``_supervise``."""
    monitor_parser = parser_for(("sase", "monitor"))
    help_text = monitor_parser.format_help()
    expected = {"list", "show", "start", "stop"}

    assert help_subcommand_rows(help_text, expected) == sorted(expected)
    assert "{list,show,start,stop}" in help_text
    usage_line = next(
        line for line in help_text.splitlines() if line.startswith("usage:")
    )
    assert "_supervise" not in usage_line
    assert "defaults to `sase monitor list`" in flat_help(help_text)


def test_bare_monitor_defaults_to_list_and_records_delegation() -> None:
    """A bare ``sase monitor`` parses as ``list`` and marks the delegation."""
    parser = create_parser()

    bare = parser.parse_args(["monitor"])
    explicit = parser.parse_args(["monitor", "list"])

    assert bare.command == "monitor"
    assert bare.monitor_subcommand == "list"
    assert getattr(bare, _DEFAULT_LIST_GROUP_DEST) == "sase monitor"
    assert getattr(explicit, _DEFAULT_LIST_GROUP_DEST) is None


def test_monitor_start_help_documents_required_flags_and_examples() -> None:
    """``sase monitor start --help`` documents every option and an example."""
    start_help = flat_help(parser_for(("sase", "monitor", "start")).format_help())

    assert "usage: sase monitor start" in start_help
    assert "-c, --command CMD" in start_help
    assert "-r, --reason TEXT" in start_help
    assert "-t, --timeout DURATION" in start_help
    assert "-n, --next TEXT" in start_help
    assert "sase monitor start -c 'just check-full'" in start_help


def test_monitor_start_command_flag_does_not_shadow_the_top_level_command_dest() -> (
    None
):
    """``-c/--command``'s dest must not collide with the root ``command`` dest.

    Its default dest would be ``command``, silently overwriting the root
    parser's routing field (which is also ``command``) and breaking
    ``entry.py``'s ``if args.command == "monitor":`` dispatch.
    """
    args = create_parser().parse_args(
        ["monitor", "start", "-c", "true", "-r", "verify", "-t", "30s", "-l", "acme"]
    )

    assert args.command == "monitor"
    assert args.monitor_subcommand == "start"
    assert args.monitor_command == "true"


def test_monitor_start_command_reason_and_timeout_are_required() -> None:
    """``sase monitor start`` refuses to parse without its required flags."""
    parser = create_parser()

    with pytest.raises(SystemExit) as exit_info:
        parser.parse_args(["monitor", "start"])

    assert exit_info.value.code == 2


def test_monitor_stop_id_is_optional() -> None:
    """``sase monitor stop`` accepts an omitted positional id."""
    args = create_parser().parse_args(["monitor", "stop"])

    assert args.monitor_id is None


def test_monitor_show_id_is_required() -> None:
    """``sase monitor show`` refuses to parse without an id."""
    parser = create_parser()

    with pytest.raises(SystemExit) as exit_info:
        parser.parse_args(["monitor", "show"])

    assert exit_info.value.code == 2


def test_monitor_list_status_filter_repeats_and_validates() -> None:
    """``-s`` accumulates and only accepts real monitor states."""
    args = create_parser().parse_args(
        ["monitor", "list", "-s", "failed", "-s", "timeout"]
    )

    assert args.status == ["failed", "timeout"]


def test_monitor_list_format_choices_are_table_markdown_json() -> None:
    """``-f/--format`` only accepts the three documented output shapes."""
    parser = create_parser()

    with pytest.raises(SystemExit) as exit_info:
        parser.parse_args(["monitor", "list", "-f", "yaml"])

    assert exit_info.value.code == 2


def test_monitor_state_choices_match_the_engine_states() -> None:
    """The parser's inlined state list must not drift from the engine's."""
    from sase.main.parser_monitor import MONITOR_STATE_CHOICES
    from sase.monitor.models import MONITOR_STATES

    assert set(MONITOR_STATE_CHOICES) == set(MONITOR_STATES)


def test_monitor_supervise_is_hidden_but_reachable() -> None:
    """``_supervise`` parses even though it is suppressed from help."""
    args = create_parser().parse_args(
        ["monitor", "_supervise", "--artifacts-dir", "/tmp/x"]
    )

    assert args.monitor_subcommand == "_supervise"
    assert args.artifacts_dir == "/tmp/x"


def test_monitor_short_options_have_the_documented_long_aliases() -> None:
    """Every short flag documented for ``start`` binds to its long option."""
    start_parser = parser_for(("sase", "monitor", "start"))
    for short, long in (
        ("-c", "--command"),
        ("-C", "--cwd"),
        ("-L", "--label"),
        ("-l", "--lane"),
        ("-n", "--next"),
        ("-r", "--reason"),
        ("-s", "--start-status"),
        ("-S", "--stop-status"),
        ("-T", "--tail-lines"),
        ("-t", "--timeout"),
    ):
        assert (
            start_parser._option_string_actions[short]
            is start_parser._option_string_actions[long]
        )
