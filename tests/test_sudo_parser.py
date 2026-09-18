"""Parser coverage for detached sudo answer flags and hidden finalize."""

from __future__ import annotations

import argparse

import pytest

from sase.main.parser import create_parser
from sase.main.parser_sudo import register_sudo_parser


def _parse(*argv: str) -> argparse.Namespace:
    return create_parser().parse_args(["sudo", *argv])


def test_sudo_answer_detach_flags_default_off() -> None:
    args = _parse("answer", "sudo-123", "--run")

    assert args.detach is False
    assert args.no_detach is False


def test_sudo_answer_detach_and_no_detach_are_mutually_exclusive() -> None:
    parser = create_parser()

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(
            ["sudo", "answer", "sudo-123", "--run", "--detach", "--no-detach"]
        )

    assert excinfo.value.code == 2


def test_sudo_answer_short_detach_aliases() -> None:
    detached = _parse("answer", "sudo-123", "--run", "-D")
    foreground = _parse("answer", "sudo-123", "--run", "-N")

    assert detached.detach is True
    assert detached.no_detach is False
    assert foreground.detach is False
    assert foreground.no_detach is True


def test_sudo_finalize_is_hidden_but_parseable() -> None:
    parser = argparse.ArgumentParser(prog="sase")
    register_sudo_parser(parser.add_subparsers(dest="command"))
    sudo_parser = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    ).choices["sudo"]
    help_text = sudo_parser.format_help()
    args = parser.parse_args(["sudo", "finalize", "sudo-123", "--json"])

    assert "Internal detached sudo finalizer" not in help_text
    assert "finalize            ==SUPPRESS==" in help_text
    assert "exec                ==SUPPRESS==" in help_text
    assert args.sudo_subcommand == "finalize"
    assert args.gate_ref == "sudo-123"
    assert args.json is True


def test_sudo_exec_detach_args_are_parseable() -> None:
    args = _parse(
        "exec",
        "--detach",
        "--manifest",
        "/tmp/manifest.json",
        "--expected-sha256",
        "abc",
        "--handshake",
        "/tmp/handshake.json",
        "--ledger",
        "/tmp/ledger.json",
    )

    assert args.sudo_subcommand == "exec"
    assert args.detach is True
    assert args.manifest == "/tmp/manifest.json"
    assert args.expected_sha256 == "abc"
    assert args.handshake == "/tmp/handshake.json"
    assert args.ledger == "/tmp/ledger.json"


def test_sudo_answer_help_documents_detach() -> None:
    parser = argparse.ArgumentParser(prog="sase")
    register_sudo_parser(parser.add_subparsers(dest="command"))
    answer = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    ).choices["sudo"]
    answer_parser = next(
        action
        for action in answer._actions
        if isinstance(action, argparse._SubParsersAction)
    ).choices["answer"]
    help_text = answer_parser.format_help()

    assert "--detach" in help_text
    assert "--no-detach" in help_text
    assert "-D" in help_text
    assert "-N" in help_text
