"""Tests for the ``sase memory`` parser and handler."""

from __future__ import annotations

import argparse
from io import StringIO
from pathlib import Path
import sys

import pytest
from rich.console import Console

from sase.memory.cli_list import _render_memory_inventory
from sase.memory.inventory import build_memory_inventory
from sase.main import memory_handler
from sase.main.parser import create_parser


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


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


def test_memory_list_dashboard_renders_inventory_statuses(tmp_path: Path) -> None:
    _write(tmp_path / "AGENTS.md", "@memory/short/base.md\nmemory/long/missing.md\n")
    _write(
        tmp_path / "memory" / "short" / "base.md",
        "# Base\nSee memory/long/index.md\n",
    )
    _write(tmp_path / "memory" / "long" / "index.md", "# Index\n")
    _write(tmp_path / "memory" / "long" / "orphan.md", "# Orphan\n")

    inventory = build_memory_inventory(tmp_path)
    output = StringIO()
    console = Console(
        file=output,
        force_terminal=False,
        color_system=None,
        width=120,
    )

    _render_memory_inventory(inventory, console=console, project_name="demo")

    text = output.getvalue()
    assert "SASE Memory Context" in text
    assert str(tmp_path) in text
    assert "Project" in text
    assert "demo" in text
    assert "Loaded files" in text
    assert "Referenced-only files" in text
    assert "Available files" in text
    assert "Missing references" in text
    assert "Approx loaded tokens" in text
    assert "loaded" in text
    assert "memory/short/base.md" in text
    assert "referenced" in text
    assert "memory/long/index.md" in text
    assert "available" in text
    assert "memory/long/orphan.md" in text
    assert "missing" in text
    assert "memory/long/missing.md" in text
    assert "@path loads file contents" in text
    assert "Plain memory/... paths are visible references only." in text
    assert "Dynamic memory is prompt-dependent" in text
