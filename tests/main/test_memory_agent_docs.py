"""Tests for the ``sase memory agent-docs`` parser and command dispatch."""

from __future__ import annotations

import argparse

import pytest

import sase.amd.inventory as inventory
from sase.main import memory_handler
from sase.main.parser import create_parser, default_list_delegation_notice


def test_parser_registers_memory_agent_docs_namespace() -> None:
    parser = create_parser()

    default_args = parser.parse_args(["memory", "agent-docs"])
    assert default_args.command == "memory"
    assert default_args.memory_subcommand == "agent-docs"
    assert default_args.agent_docs_subcommand == "list"

    list_args = parser.parse_args(["memory", "agent-docs", "list"])
    assert list_args.command == "memory"
    assert list_args.memory_subcommand == "agent-docs"
    assert list_args.agent_docs_subcommand == "list"


def test_amd_command_and_init_alias_are_removed() -> None:
    parser = create_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["amd"])
    with pytest.raises(SystemExit):
        parser.parse_args(["init", "amd"])


def test_bare_memory_agent_docs_delegates_to_list() -> None:
    parser = create_parser()

    args = parser.parse_args(["memory", "agent-docs"])

    assert default_list_delegation_notice(args) == (
        "No subcommand provided for 'sase memory agent-docs';"
        " delegating to 'sase memory agent-docs list'."
    )


def test_bare_memory_still_delegates_to_memory_list() -> None:
    parser = create_parser()

    args = parser.parse_args(["memory"])

    assert args.memory_subcommand == "list"
    assert default_list_delegation_notice(args) == (
        "No subcommand provided for 'sase memory'; delegating to 'sase memory list'."
    )


def test_explicit_agent_docs_list_records_no_delegation() -> None:
    parser = create_parser()

    args = parser.parse_args(["memory", "agent-docs", "list"])

    assert default_list_delegation_notice(args) is None


def test_memory_agent_docs_dispatches_to_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[argparse.Namespace] = []

    def fake_list(args: argparse.Namespace) -> int:
        calls.append(args)
        return 0

    monkeypatch.setattr(inventory, "run_amd_list", fake_list)
    args = create_parser().parse_args(["memory", "agent-docs"])

    with pytest.raises(SystemExit) as exc:
        memory_handler.handle_memory_command(args)

    assert exc.value.code == 0
    assert calls == [args]


def test_memory_agent_docs_propagates_inventory_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(inventory, "run_amd_list", lambda args: 3)
    args = create_parser().parse_args(["memory", "agent-docs", "list"])

    with pytest.raises(SystemExit) as exc:
        memory_handler.handle_memory_command(args)

    assert exc.value.code == 3
