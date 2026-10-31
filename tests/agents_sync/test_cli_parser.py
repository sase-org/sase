from __future__ import annotations

import argparse

import pytest

from sase.main.parser import create_parser


def test_parser_accepts_repeatable_project_and_check_refresh() -> None:
    args = create_parser().parse_args(
        ["agent", "sync", "-c", "-r", "-p", "one", "-p", "two", "-j"]
    )

    assert args.agent_subcommand == "sync"
    assert args.check and args.refresh and args.json
    assert args.project == ["one", "two"]


def test_parser_rejects_refresh_without_check() -> None:
    with pytest.raises(SystemExit) as exc_info:
        create_parser().parse_args(["agent", "sync", "--refresh"])

    assert exc_info.value.code == 2


def test_parser_accepts_retry_quarantined_only_for_full_sync() -> None:
    args = create_parser().parse_args(
        ["agent", "sync", "--retry-quarantined", "--project", "one"]
    )
    assert args.retry_quarantined

    with pytest.raises(SystemExit) as exc_info:
        create_parser().parse_args(["agent", "sync", "--check", "--retry-quarantined"])
    assert exc_info.value.code == 2


def test_parser_accepts_retry_retired_with_project_and_quarantine_combo() -> None:
    args = create_parser().parse_args(["agent", "sync", "-t", "-q", "-p", "one"])
    assert args.retry_retired
    assert args.retry_quarantined
    assert args.project == ["one"]


def test_parser_accepts_bounded_retry_aliases_and_repeated_error_classes() -> None:
    args = create_parser().parse_args(
        [
            "agent",
            "sync",
            "-t",
            "-q",
            "-l",
            "2",
            "-e",
            "timeout",
            "--retry-error-class",
            "lock_busy",
            "-p",
            "one",
        ]
    )

    assert args.retry_limit == 2
    assert args.retry_error_class == ["timeout", "lock_busy"]
    assert args.retry_key is None


def test_parser_accepts_retry_key_alias_and_full_outbox_identity() -> None:
    identity = ("alice.athena.worker", "a" * 40)
    args = create_parser().parse_args(
        [
            "agent",
            "sync",
            "-q",
            "-l",
            "1",
            "-k",
            f"{identity[0]}@{identity[1]}",
            "-p",
            "one",
        ]
    )

    assert args.retry_key == identity
    assert args.retry_limit == 1
    assert args.retry_quarantined


@pytest.mark.parametrize(
    "argv",
    (
        ["--retry-quarantined", "--retry-limit", "0", "--project", "one"],
        ["--retry-limit", "2", "--project", "one"],
        ["--retry-quarantined", "--retry-error-class", "timeout", "--project", "one"],
        ["--retry-quarantined", "--retry-limit", "2"],
        [
            "--retry-quarantined",
            "--retry-limit",
            "2",
            "--project",
            "one",
            "--project",
            "two",
        ],
        ["--retry-quarantined", "--retry-limit", "2", "--project", "one", "--check"],
        [
            "--retry-quarantined",
            "--retry-limit",
            "2",
            "--project",
            "one",
            "--check",
            "--refresh",
        ],
        [
            "--retry-quarantined",
            "--retry-limit",
            "2",
            "--project",
            "one",
            "--drop-retired",
        ],
        [
            "--retry-quarantined",
            "--retry-limit",
            "2",
            "--project",
            "one",
            "--repair-digests",
        ],
        [
            "--retry-quarantined",
            "--retry-limit",
            "2",
            "--project",
            "one",
            "--repair-manifest",
        ],
        [
            "--retry-quarantined",
            "--retry-limit",
            "2",
            "--retry-error-class",
            "bogus",
            "--project",
            "one",
        ],
        [
            "--retry-quarantined",
            "--retry-limit",
            "1",
            "--retry-key",
            "not-an-identity",
            "--project",
            "one",
        ],
        [
            "--retry-quarantined",
            "--retry-limit",
            "1",
            "--retry-key",
            "alice.athena.worker@short",
            "--project",
            "one",
        ],
        [
            "--retry-quarantined",
            "--retry-limit",
            "1",
            "--retry-key",
            f"alice.athena.worker@{'A' * 40}",
            "--project",
            "one",
        ],
        [
            "--retry-quarantined",
            "--retry-limit",
            "1",
            "--retry-key",
            f"@{('a' * 40)}",
            "--project",
            "one",
        ],
        [
            "--retry-quarantined",
            "--retry-limit",
            "1",
            "--retry-key",
            f"alice.athena.worker@{('a' * 40)}@extra",
            "--project",
            "one",
        ],
        [
            "--retry-quarantined",
            "--retry-key",
            f"alice.athena.worker@{('a' * 40)}",
            "--project",
            "one",
        ],
        [
            "--retry-quarantined",
            "--retry-limit",
            "2",
            "--retry-key",
            f"alice.athena.worker@{('a' * 40)}",
            "--project",
            "one",
        ],
        [
            "--retry-limit",
            "1",
            "--retry-key",
            f"alice.athena.worker@{('a' * 40)}",
            "--project",
            "one",
        ],
        [
            "--retry-quarantined",
            "--retry-limit",
            "1",
            "--retry-key",
            f"alice.athena.worker@{('a' * 40)}",
        ],
        [
            "--retry-quarantined",
            "--retry-limit",
            "1",
            "--retry-key",
            f"alice.athena.worker@{('a' * 40)}",
            "--project",
            "one",
            "--project",
            "two",
        ],
        [
            "--retry-quarantined",
            "--retry-limit",
            "1",
            "--retry-key",
            f"alice.athena.worker@{('a' * 40)}",
            "--project",
            "one",
            "--check",
        ],
    ),
)
def test_parser_rejects_invalid_bounded_retry_options(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        create_parser().parse_args(["agent", "sync", *argv])

    assert exc_info.value.code == 2


def test_parser_rejects_retry_retired_without_project() -> None:
    with pytest.raises(SystemExit) as exc_info:
        create_parser().parse_args(["agent", "sync", "--retry-retired"])
    assert exc_info.value.code == 2


@pytest.mark.parametrize(
    "extra",
    (
        ["--check"],
        ["--drop-retired"],
        ["--repair-digests"],
        ["--repair-manifest"],
    ),
)
def test_parser_rejects_retry_retired_with_incompatible_modes(extra: list[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        create_parser().parse_args(
            ["agent", "sync", "--retry-retired", "--project", "one", *extra]
        )
    assert exc_info.value.code == 2


def test_parser_accepts_repair_digests_flag() -> None:
    args = create_parser().parse_args(
        ["agent", "sync", "--repair-digests", "--project", "one"]
    )
    assert args.repair_digests
    assert args.project == ["one"]


def test_parser_accepts_repair_manifest_flag() -> None:
    args = create_parser().parse_args(
        ["agent", "sync", "--repair-manifest", "--project", "one"]
    )
    assert args.repair_manifest
    assert args.project == ["one"]


def test_parser_accepts_drop_retired_only_for_full_sync() -> None:
    args = create_parser().parse_args(["agent", "sync", "-d", "--project", "one"])
    assert args.drop_retired

    with pytest.raises(SystemExit) as exc_info:
        create_parser().parse_args(["agent", "sync", "--check", "--drop-retired"])
    assert exc_info.value.code == 2


def test_sync_help_distinguishes_full_cached_and_refresh_modes() -> None:
    parser = create_parser()
    root_action = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    agent_parser = root_action.choices["agent"]
    agent_action = next(
        action
        for action in agent_parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )

    help_text = " ".join(agent_action.choices["sync"].format_help().split())

    assert "drain publication retries" in help_text
    assert "--check is local and network-free" in help_text
    assert "computing ahead/behind" in help_text
    assert "-t, --retry-retired" in help_text
    # argparse includes the metavar beside each alias on Python 3.12, but
    # omits it on 3.13+. Assert the stable long option across supported Pythons.
    assert "--retry-key" in help_text
    assert "GLOBAL_AGENT@REVISION" in help_text
    assert "requires --project" in help_text


def test_agent_help_keeps_bare_list_delegation_and_sorted_commands() -> None:
    parser = create_parser()
    agent_action = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    agent_parser = agent_action.choices["agent"]
    help_text = agent_parser.format_help()

    normalized_help = " ".join(help_text.split())
    assert "delegates to `sase agent list`" in normalized_help
    command_line = next(line for line in help_text.splitlines() if "archive" in line)
    assert command_line.index("archive") < command_line.index("artifacts")
    assert command_line.index("show") < command_line.index("sync")
    assert command_line.index("sync") < command_line.index("tribe")
