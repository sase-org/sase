"""Parser and presentation tests for ``sase file-hook``."""

from __future__ import annotations

import argparse
import io
import json
from typing import Any

from rich.console import Console

from sase.config.file_hooks import FileHookConfig
from sase.main.file_hook_handler import (
    FILE_HOOK_LIST_JSON_SCHEMA_VERSION,
    _handle_file_hook_list_command,
)
from sase.main.parser import create_parser, default_list_delegation_notice


def _hook() -> FileHookConfig:
    return FileHookConfig(
        name="research-highlights",
        description="Render new research reports.",
        command="bob highlights create",
        projects=("sase",),
        sidecars=("research",),
        globs=("20*/*/*.md", "!20*/*/*__*.md"),
        ops=("ADD",),
        timeout_seconds=120,
        source_layer="user",
    )


def test_bare_file_hook_defaults_to_list_with_notice() -> None:
    args = create_parser().parse_args(["file-hook"])

    assert args.command == "file-hook"
    assert args.file_hook_subcommand == "list"
    assert args.json is False
    assert default_list_delegation_notice(args) == (
        "No subcommand provided for 'sase file-hook'; delegating to "
        "'sase file-hook list'."
    )


def test_file_hook_list_accepts_short_and_long_json_flags() -> None:
    short = create_parser().parse_args(["file-hook", "list", "-j"])
    long = create_parser().parse_args(["file-hook", "list", "--json"])

    assert short.json is True
    assert long.json is True
    assert default_list_delegation_notice(short) is None


def test_file_hook_list_json_is_versioned(capsys: Any) -> None:
    code = _handle_file_hook_list_command(
        argparse.Namespace(json=True),
        hooks_fn=lambda: [_hook()],
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["schema_version"] == FILE_HOOK_LIST_JSON_SCHEMA_VERSION
    assert payload["count"] == 1
    assert payload["file_hooks"][0]["source_layer"] == "user"
    assert payload["file_hooks"][0]["timeout_seconds"] == 120


def test_file_hook_list_renders_all_fields() -> None:
    stream = io.StringIO()
    console = Console(file=stream, width=180, no_color=True)

    code = _handle_file_hook_list_command(
        argparse.Namespace(json=False),
        console=console,
        hooks_fn=lambda: [_hook()],
    )

    rendered = stream.getvalue()
    assert code == 0
    assert "research-highlights" in rendered
    assert "Render new research reports." in rendered
    assert "bob highlights create" in rendered
    assert "projects: sase" in rendered
    assert "sidecars: research" in rendered
    assert "20*/*/*.md" in rendered
    assert "ops: ADD" in rendered
    assert "120s" in rendered
    assert "user" in rendered


def test_file_hook_list_empty_state() -> None:
    stream = io.StringIO()
    console = Console(file=stream, no_color=True)

    code = _handle_file_hook_list_command(
        argparse.Namespace(json=False),
        console=console,
        hooks_fn=list,
    )

    assert code == 0
    assert stream.getvalue().strip() == "No file hooks configured."
