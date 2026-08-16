"""Tests for defaulted parser command groups."""

from __future__ import annotations

from sase.main.parser import (
    _DEFAULT_LIST_GROUP_DEST,
    create_parser,
    default_list_delegation_notice,
)
from tests.main.parser_help_helpers import walk_subparser_actions


def test_all_subparser_choices_are_sorted() -> None:
    """Every subcommand group keeps usage metavars sorted alphabetically."""
    parser = create_parser()

    for path, action in walk_subparser_actions(parser):
        commands = list(action.choices)

        assert commands == sorted(commands), " ".join(path)


def test_all_visible_subparser_help_entries_are_sorted() -> None:
    """Every subcommand group renders its help rows sorted alphabetically."""
    parser = create_parser()

    for path, action in walk_subparser_actions(parser):
        visible_commands = [
            choice_action.dest for choice_action in action._choices_actions
        ]

        assert visible_commands == sorted(visible_commands), " ".join(path)


def test_telemetry_only_exposes_debugging_and_health_commands() -> None:
    """Product charts are absent while the debugging surface remains."""
    parser = create_parser()
    telemetry_action = next(
        action
        for path, action in walk_subparser_actions(parser)
        if path == ("sase", "telemetry")
    )

    assert set(telemetry_action.choices) == {
        "cleanup-test-data",
        "health",
        "list",
        "snapshot",
        "status",
    }


def test_exact_list_subcommands_default_when_group_is_omitted() -> None:
    """Every command group with an exact ``list`` child parses bare as list."""
    parser = create_parser()
    expected_groups = {
        "sase agent",
        "sase agent tribe",
        "sase axe chop",
        "sase axe lumberjack",
        "sase bead",
        "sase chat",
        "sase file",
        "sase file-history",
        "sase flag",
        "sase memory",
        "sase memory agent-docs",
        "sase notify",
        "sase plan links",
        "sase prompt",
        "sase skill",
        "sase proc",
        "sase telemetry",
        "sase var",
        "sase stitch",
        "sase workspace",
        "sase xprompt",
    }
    list_groups: set[str] = set()

    for path, action in walk_subparser_actions(parser):
        if "list" not in action.choices:
            continue

        label = " ".join(path)
        list_groups.add(label)
        omitted_args = parser.parse_args([*path[1:]])
        explicit_args = parser.parse_args([*path[1:], "list"])

        assert getattr(omitted_args, action.dest) == "list", label
        for key, value in vars(explicit_args).items():
            # The private delegation marker intentionally differs between a bare
            # group and an explicit ``list``; all public defaults must match.
            if key == _DEFAULT_LIST_GROUP_DEST:
                continue
            assert hasattr(omitted_args, key), f"{label} missing {key}"
            assert getattr(omitted_args, key) == value, f"{label} default {key}"

    assert expected_groups <= list_groups


def test_bare_list_group_records_delegation_metadata() -> None:
    """Omitting a list-defaulted group records the omitted group path."""
    parser = create_parser()

    for path, action in walk_subparser_actions(parser):
        if "list" not in action.choices:
            continue

        label = " ".join(path)
        omitted_args = parser.parse_args([*path[1:]])
        expected_label = "sase patch ref" if label == "sase changespec ref" else label

        assert getattr(omitted_args, _DEFAULT_LIST_GROUP_DEST) == expected_label, label
        assert default_list_delegation_notice(omitted_args) == (
            f"No subcommand provided for '{expected_label}'; "
            f"delegating to '{expected_label} list'."
        ), label


def test_nested_default_reports_only_the_omitted_group() -> None:
    """Bare nested groups report themselves, not their parent group."""
    parser = create_parser()

    tribe_args = parser.parse_args(["agent", "tribe"])
    alias_args = parser.parse_args(["project", "alias"])

    assert getattr(tribe_args, _DEFAULT_LIST_GROUP_DEST) == "sase agent tribe"
    assert getattr(alias_args, _DEFAULT_LIST_GROUP_DEST) == "sase project alias"
    assert default_list_delegation_notice(tribe_args) == (
        "No subcommand provided for 'sase agent tribe';"
        " delegating to 'sase agent tribe list'."
    )


def test_explicit_subcommands_record_no_delegation_metadata() -> None:
    """Explicit list and non-list subcommands never look defaulted."""
    parser = create_parser()

    explicit_list = parser.parse_args(["agent", "list"])
    explicit_other = parser.parse_args(["agent", "names"])
    nested_explicit_list = parser.parse_args(["agent", "tribe", "list"])
    nested_explicit_group = parser.parse_args(["project", "alias", "list"])

    for omitted_free in (
        explicit_list,
        explicit_other,
        nested_explicit_list,
        nested_explicit_group,
    ):
        assert getattr(omitted_free, _DEFAULT_LIST_GROUP_DEST) is None
        assert default_list_delegation_notice(omitted_free) is None


def test_non_list_group_has_no_delegation_metadata() -> None:
    """Commands without a defaulted list child carry no delegation marker."""
    parser = create_parser()

    doctor_args = parser.parse_args(["doctor"])

    assert getattr(doctor_args, _DEFAULT_LIST_GROUP_DEST, None) is None
    assert default_list_delegation_notice(doctor_args) is None
