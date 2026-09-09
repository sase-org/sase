"""Tests for the ``sase notify`` parser."""

from __future__ import annotations

import argparse

import pytest

from sase.main.parser import create_parser


def test_parser_defaults_bare_notify_to_list() -> None:
    parser = create_parser()
    args = parser.parse_args(["notify"])
    assert args.command == "notify"
    assert args.notify_subcommand == "list"
    assert args.json is False
    assert args.limit == 20
    assert args.query is None
    assert args.sender is None
    assert args.tag is None
    assert args.unread is False
    assert args.all is False


def test_parser_registers_notify_list_options() -> None:
    parser = create_parser()
    args = parser.parse_args(
        [
            "notify",
            "list",
            "-j",
            "-l",
            "5",
            "-q",
            "digest",
            "-s",
            "axe",
            "-u",
            "-a",
            "--tag",
            "done",
        ]
    )
    assert args.command == "notify"
    assert args.notify_subcommand == "list"
    assert args.json is True
    assert args.limit == 5
    assert args.query == "digest"
    assert args.sender == "axe"
    assert args.unread is True
    assert args.all is True
    assert args.tag == "done"


def test_parser_registers_notify_show_options() -> None:
    parser = create_parser()
    args = parser.parse_args(["notify", "show", "--id", "n1", "-f", "json"])
    assert args.notify_subcommand == "show"
    assert args.id == "n1"
    assert args.format == "json"

    with pytest.raises(SystemExit):
        parser.parse_args(["notify", "show"])
    with pytest.raises(SystemExit):
        parser.parse_args(["notify", "show", "--id", "n1", "-f", "raw"])


def test_parser_registers_explicit_create_alias() -> None:
    parser = create_parser()
    args = parser.parse_args(["notify", "create", "-s", "worker", "-t", "Review"])
    assert args.notify_subcommand == "create"
    assert args.sender == "worker"
    assert args.tag == ["Review"]


def test_parser_registers_create_upsert_flags() -> None:
    parser = create_parser()
    args = parser.parse_args(
        [
            "notify",
            "create",
            "-k",
            "combo",
            "-p",
            "still failing",
            "-S",
            "old-combo",
        ]
    )
    assert args.dedup_key == "combo"
    assert args.plus_one_note == "still failing"
    assert args.supersedes == "old-combo"


def test_parser_registers_plus_one_by_id_and_by_key() -> None:
    parser = create_parser()
    args = parser.parse_args(["notify", "+1", "n1", "churn again"])
    assert args.notify_subcommand == "+1"
    assert args.id == "n1"
    assert args.note == "churn again"
    assert args.dedup_key is None

    key_args = parser.parse_args(["notify", "+1", "resolved", "-k", "combo"])
    assert key_args.id is None
    assert key_args.note == "resolved"
    assert key_args.dedup_key == "combo"


def test_parser_registers_gate_create_wait_options_and_help() -> None:
    parser = create_parser()
    create_args = parser.parse_args(
        [
            "gate",
            "create",
            "--origin-agent",
            "filer.agent",
            "--panel",
            "reviews",
            "--sender",
            "worker",
            "--tag",
            "review",
        ]
    )
    assert create_args.command == "gate"
    assert create_args.gate_subcommand == "create"
    assert create_args.origin_agent == "filer.agent"
    assert create_args.panel == "reviews"
    assert create_args.sender == "worker"
    assert create_args.tag == ["review"]

    args = parser.parse_args(
        [
            "gate",
            "wait",
            "--id",
            "custom-123",
            "-j",
            "--kind",
            "custom",
            "-t",
            "30",
        ]
    )

    assert args.gate_subcommand == "wait"
    assert args.id == "custom-123"
    assert args.json is True
    assert args.kind == "custom"
    assert args.timeout == 30.0

    gate_parser = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    ).choices["gate"]
    gate_subparsers = next(
        action
        for action in gate_parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    assert list(gate_subparsers.choices) == [
        "act",
        "answer",
        "cancel",
        "create",
        "list",
        "show",
        "wait",
    ]
    create_help = gate_subparsers.choices["create"].format_help()
    assert "--origin-agent" in create_help
    assert "--panel" in create_help
    assert "sase gate create --panel deployments" in create_help
    wait_subparsers = next(
        action
        for action in gate_parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    wait_help = wait_subparsers.choices["wait"].format_help()
    assert "--id REQUEST_ID" in wait_help
    assert "--json" in wait_help
    assert "--kind" in wait_help
    assert "--timeout SECONDS" in wait_help
    assert "answered" in wait_help
    assert "cancelled" in wait_help
    assert "timeout" in wait_help


def test_parser_retires_notify_gate_entrypoints() -> None:
    parser = create_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["notify", "create", "--gate"])
    with pytest.raises(SystemExit):
        parser.parse_args(["notify", "wait", "--id", "custom-123", "--kind", "custom"])
