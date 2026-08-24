"""Tests for the ``sase memory`` parser and command dispatch."""

from __future__ import annotations

import argparse
import sys

import pytest

from sase.main import memory_handler
from sase.main.parser import create_parser


def test_parser_registers_memory_namespace() -> None:
    parser = create_parser()

    init_args = parser.parse_args(["memory", "init", "-C"])
    assert init_args.command == "memory"
    assert init_args.memory_subcommand == "init"
    assert init_args.no_commit is True
    assert init_args.check is False

    check_args = parser.parse_args(["memory", "init", "--check"])
    assert check_args.command == "memory"
    assert check_args.memory_subcommand == "init"
    assert check_args.check is True
    assert check_args.no_commit is False

    list_args = parser.parse_args(["memory", "list"])
    assert list_args.command == "memory"
    assert list_args.memory_subcommand == "list"

    read_args = parser.parse_args(
        ["memory", "read", "foo.md", "--reason", "Need context"]
    )
    assert read_args.command == "memory"
    assert read_args.memory_subcommand == "read"
    assert read_args.selectors == ["foo.md"]
    assert read_args.reason == "Need context"
    assert read_args.format == "markdown"
    assert read_args.depth is None
    assert read_args.project is None

    show_args = parser.parse_args(["memory", "show", "foo.md"])
    assert show_args.command == "memory"
    assert show_args.memory_subcommand == "show"
    assert show_args.selectors == ["foo.md"]
    assert show_args.format == "markdown"

    show_rich_args = parser.parse_args(["memory", "show", "foo.md", "-f", "rich"])
    assert show_rich_args.format == "rich"

    with pytest.raises(SystemExit):
        parser.parse_args(["memory", "show", "foo.md", "-f", "bogus"])

    write_args = parser.parse_args(
        [
            "memory",
            "write",
            "--title",
            "Generated skills",
            "--slug",
            "generated_skills",
            "--evidence",
            "sdd/research/skills.md",
            "--evidence",
            "note:supplemental",
            "--from-chat",
            "chat-a",
            "--file",
            "draft.md",
            "--allow-large",
            "--json",
            "--notify",
        ]
    )
    assert write_args.command == "memory"
    assert write_args.memory_subcommand == "write"
    assert write_args.title == "Generated skills"
    assert write_args.slug == "generated_skills"
    assert write_args.target is None
    assert write_args.evidence == ["sdd/research/skills.md", "note:supplemental"]
    assert write_args.from_chat == ["chat-a"]
    assert write_args.file == "draft.md"
    assert write_args.allow_large is True
    assert write_args.json is True
    assert write_args.notify is True

    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "memory",
                "write",
                "--title",
                "Generated skills",
                "--slug",
                "generated_skills",
                "--evidence",
                "chat:abc",
                "--keyword",
                "skills",
                "--body",
                "Body",
            ]
        )

    review_list_args = parser.parse_args(["memory", "review", "--list", "--json"])
    assert review_list_args.command == "memory"
    assert review_list_args.memory_subcommand == "review"
    assert review_list_args.list is True
    assert review_list_args.json is True

    review_approve_args = parser.parse_args(
        [
            "memory",
            "review",
            "mem-20260523-120000-1234abcd",
            "--approve",
            "--target",
            "reviewed.md",
            "--edited-file",
            "reviewed.md",
        ]
    )
    assert review_approve_args.command == "memory"
    assert review_approve_args.memory_subcommand == "review"
    assert review_approve_args.proposal_id == "mem-20260523-120000-1234abcd"
    assert review_approve_args.approve is True
    assert review_approve_args.target == "reviewed.md"
    assert review_approve_args.edited_file == "reviewed.md"

    log_args = parser.parse_args(
        [
            "memory",
            "log",
            "--path",
            "generated_skills.md",
            "--agent",
            "agent-a",
            "--json",
            "--include",
            "proposals",
        ]
    )
    assert log_args.command == "memory"
    assert log_args.memory_subcommand == "log"
    assert log_args.path == "generated_skills.md"
    assert log_args.agent == "agent-a"
    assert log_args.json is True
    assert log_args.include == ["proposals"]

    log_id_args = parser.parse_args(["memory", "log", "--id", "read-a"])
    assert log_id_args.command == "memory"
    assert log_id_args.memory_subcommand == "log"
    assert log_id_args.id == "read-a"

    default_args = parser.parse_args(["memory"])
    assert default_args.command == "memory"
    assert default_args.memory_subcommand == "list"


def test_parser_requires_memory_read_reason() -> None:
    parser = create_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["memory", "read", "foo.md"])


def test_parser_accepts_memory_read_reason_short_option() -> None:
    parser = create_parser()

    args = parser.parse_args(["memory", "read", "foo.md", "-r", "Need context"])

    assert args.command == "memory"
    assert args.memory_subcommand == "read"
    assert args.selectors == ["foo.md"]
    assert args.reason == "Need context"


def test_parser_requires_memory_write_target_or_slug() -> None:
    parser = create_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "memory",
                "write",
                "--title",
                "Memory",
                "--evidence",
                "chat:abc",
                "--body",
                "Body",
            ]
        )


def test_memory_init_dispatches_to_primary_init(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[argparse.Namespace] = []

    def fake_init(args: argparse.Namespace) -> None:
        calls.append(args)

    monkeypatch.setattr(
        "sase.main.init_memory_handler.handle_memory_init_command",
        fake_init,
    )
    args = create_parser().parse_args(["memory", "init", "-C"])

    with pytest.raises(SystemExit) as exc:
        memory_handler.handle_memory_command(args)

    assert exc.value.code == 0
    assert calls == [args]
    assert calls[0].no_commit is True


def test_memory_read_dispatches_to_read_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[argparse.Namespace] = []

    def fake_read(args: argparse.Namespace) -> None:
        calls.append(args)

    monkeypatch.setattr(
        "sase.memory.cli_read.handle_memory_read_command",
        fake_read,
    )
    args = create_parser().parse_args(
        ["memory", "read", "foo.md", "--reason", "Need context"]
    )

    with pytest.raises(SystemExit) as exc:
        memory_handler.handle_memory_command(args)

    assert exc.value.code == 0
    assert calls == [args]


def test_memory_show_dispatches_to_show_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[argparse.Namespace] = []

    def fake_show(args: argparse.Namespace) -> None:
        calls.append(args)

    monkeypatch.setattr(
        "sase.memory.cli_show.handle_memory_show_command",
        fake_show,
    )
    args = create_parser().parse_args(["memory", "show", "foo.md"])

    with pytest.raises(SystemExit) as exc:
        memory_handler.handle_memory_command(args)

    assert exc.value.code == 0
    assert calls == [args]


def test_memory_write_dispatches_to_write_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[argparse.Namespace] = []

    def fake_write(args: argparse.Namespace) -> None:
        calls.append(args)

    monkeypatch.setattr(
        "sase.memory.cli_write.handle_memory_write_command",
        fake_write,
    )
    args = create_parser().parse_args(
        [
            "memory",
            "write",
            "--title",
            "Memory",
            "--slug",
            "memory",
            "--evidence",
            "chat:abc",
            "--body",
            "Body",
        ]
    )

    with pytest.raises(SystemExit) as exc:
        memory_handler.handle_memory_command(args)

    assert exc.value.code == 0
    assert calls == [args]


def test_memory_review_dispatches_to_review_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[argparse.Namespace] = []

    def fake_review(args: argparse.Namespace) -> None:
        calls.append(args)

    monkeypatch.setattr(
        "sase.memory.cli_review.handle_memory_review_command",
        fake_review,
    )
    args = create_parser().parse_args(["memory", "review", "--list"])

    with pytest.raises(SystemExit) as exc:
        memory_handler.handle_memory_command(args)

    assert exc.value.code == 0
    assert calls == [args]


def test_init_memory_alias_dispatches_to_memory_init(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.main.entry import main

    calls: list[argparse.Namespace] = []

    def fake_init(args: argparse.Namespace) -> None:
        calls.append(args)
        sys.exit(0)

    monkeypatch.setattr(sys, "argv", ["sase", "init", "memory", "-C"])
    monkeypatch.setattr(
        "sase.main.init_memory_handler.handle_memory_init_command",
        fake_init,
    )

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 0
    assert len(calls) == 1
    assert calls[0].command == "init"
    assert calls[0].init_subcommand == "memory"
    assert calls[0].no_commit is True


def test_bare_memory_defaults_to_list(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[argparse.Namespace] = []

    def fake_list(args: argparse.Namespace) -> None:
        calls.append(args)

    monkeypatch.setattr(memory_handler, "_handle_memory_list_command", fake_list)
    args = create_parser().parse_args(["memory"])

    with pytest.raises(SystemExit) as exc:
        memory_handler.handle_memory_command(args)

    assert exc.value.code == 0
    assert calls == [args]


def test_memory_log_dispatches_to_summary_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[argparse.Namespace] = []

    def fake_log(args: argparse.Namespace) -> None:
        calls.append(args)

    monkeypatch.setattr(memory_handler, "_handle_memory_log_command", fake_log)
    args = create_parser().parse_args(["memory", "log", "--agent", "agent-a"])

    with pytest.raises(SystemExit) as exc:
        memory_handler.handle_memory_command(args)

    assert exc.value.code == 0
    assert calls == [args]
