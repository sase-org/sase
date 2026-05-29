"""Tests for the ``sase amd`` parser and command dispatch."""

from __future__ import annotations

import argparse
import sys

import pytest

from sase.main import amd_handler
from sase.main.parser import create_parser


def test_parser_registers_amd_namespace() -> None:
    parser = create_parser()

    default_args = parser.parse_args(["amd"])
    assert default_args.command == "amd"
    assert default_args.amd_subcommand == "list"

    list_args = parser.parse_args(["amd", "list"])
    assert list_args.command == "amd"
    assert list_args.amd_subcommand == "list"

    init_args = parser.parse_args(["amd", "init", "-c"])
    assert init_args.command == "amd"
    assert init_args.amd_subcommand == "init"
    assert init_args.check is True

    init_alias_args = parser.parse_args(["init", "amd", "--check"])
    assert init_alias_args.command == "init"
    assert init_alias_args.init_subcommand == "amd"
    assert init_alias_args.check is True

    parent_check_alias_args = parser.parse_args(["init", "--check", "amd"])
    assert parent_check_alias_args.command == "init"
    assert parent_check_alias_args.init_subcommand == "amd"
    assert parent_check_alias_args.check is True


def test_bare_amd_defaults_to_list(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[argparse.Namespace] = []

    def fake_list(args: argparse.Namespace) -> int:
        calls.append(args)
        return 0

    monkeypatch.setattr(amd_handler, "_handle_amd_list_command", fake_list)
    args = create_parser().parse_args(["amd"])

    with pytest.raises(SystemExit) as exc:
        amd_handler.handle_amd_command(args)

    assert exc.value.code == 0
    assert calls == [args]


def test_amd_init_dispatches_to_initializer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[argparse.Namespace] = []

    def fake_init(args: argparse.Namespace) -> int:
        calls.append(args)
        return 0

    monkeypatch.setattr(amd_handler, "_handle_amd_init_command", fake_init)
    args = create_parser().parse_args(["amd", "init", "--check"])

    with pytest.raises(SystemExit) as exc:
        amd_handler.handle_amd_command(args)

    assert exc.value.code == 0
    assert calls == [args]
    assert calls[0].check is True


def test_init_amd_alias_dispatches_to_amd_init(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.main.entry import main

    calls: list[argparse.Namespace] = []

    def fake_init(args: argparse.Namespace) -> int:
        calls.append(args)
        return 7

    monkeypatch.setattr(sys, "argv", ["sase", "init", "amd", "-c"])
    monkeypatch.setattr(amd_handler, "_handle_amd_init_command", fake_init)

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 7
    assert len(calls) == 1
    assert calls[0].command == "init"
    assert calls[0].init_subcommand == "amd"
    assert calls[0].check is True
