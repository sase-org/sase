"""Shared helpers for ``sase artifact`` CLI tests."""

from __future__ import annotations

import argparse
import sys

import pytest

from sase.main import entry
from sase.main.parser import create_parser


def artifact_parser() -> argparse.ArgumentParser:
    parser = create_parser()
    subparser_action = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    return subparser_action.choices["artifact"]


def subparser_action(
    parser: argparse.ArgumentParser,
) -> argparse._SubParsersAction:
    return next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )


def run_entry(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *argv: str,
) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "argv", ["sase", *argv])
    with pytest.raises(SystemExit) as exc_info:
        entry.main()
    captured = capsys.readouterr()
    code = exc_info.value.code
    return int(code) if isinstance(code, int) else 0, captured.out, captured.err
