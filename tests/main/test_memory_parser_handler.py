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
        ["memory", "read", "long/foo.md", "--reason", "Need context"]
    )
    assert read_args.command == "memory"
    assert read_args.memory_subcommand == "read"
    assert read_args.memory_path == "long/foo.md"
    assert read_args.reason == "Need context"

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
            "--keyword",
            "skills",
            "--file",
            "draft.md",
            "--allow-large",
            "--json",
        ]
    )
    assert write_args.command == "memory"
    assert write_args.memory_subcommand == "write"
    assert write_args.title == "Generated skills"
    assert write_args.slug == "generated_skills"
    assert write_args.target is None
    assert write_args.evidence == ["sdd/research/skills.md", "note:supplemental"]
    assert write_args.from_chat == ["chat-a"]
    assert write_args.keyword == ["skills"]
    assert write_args.file == "draft.md"
    assert write_args.allow_large is True
    assert write_args.json is True

    log_args = parser.parse_args(
        [
            "memory",
            "log",
            "--path",
            "long/generated_skills.md",
            "--agent",
            "agent-a",
            "--json",
        ]
    )
    assert log_args.command == "memory"
    assert log_args.memory_subcommand == "log"
    assert log_args.path == "long/generated_skills.md"
    assert log_args.agent == "agent-a"
    assert log_args.json is True

    log_id_args = parser.parse_args(["memory", "log", "--id", "read-a"])
    assert log_id_args.command == "memory"
    assert log_id_args.memory_subcommand == "log"
    assert log_id_args.id == "read-a"

    default_args = parser.parse_args(["memory"])
    assert default_args.command == "memory"
    assert default_args.memory_subcommand is None


def test_parser_requires_memory_read_reason() -> None:
    parser = create_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["memory", "read", "long/foo.md"])


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
        ["memory", "read", "long/foo.md", "--reason", "Need context"]
    )

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
