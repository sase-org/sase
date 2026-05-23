"""Tests for the ``sase memory`` parser and handler."""

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

    list_args = parser.parse_args(["memory", "list"])
    assert list_args.command == "memory"
    assert list_args.memory_subcommand == "list"

    default_args = parser.parse_args(["memory"])
    assert default_args.command == "memory"
    assert default_args.memory_subcommand is None


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
