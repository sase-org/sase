"""Parser and presentation tests for ``sase file-hook``."""

from __future__ import annotations

import argparse
import io
import json
from typing import Any

from rich.console import Console

from sase.config.file_hooks import FileHookConfig, FileHookFilters
from sase.file_hooks.engine import dispatch_file_hook_events
from sase.main.file_hook_handler import (
    FILE_HOOK_HISTORY_JSON_SCHEMA_VERSION,
    FILE_HOOK_LIST_JSON_SCHEMA_VERSION,
    _handle_file_hook_history_command,
    _handle_file_hook_list_command,
    _handle_file_hook_show_command,
)
from sase.main.parser import create_parser, default_list_delegation_notice


def _hook() -> FileHookConfig:
    return FileHookConfig(
        name="research-highlights",
        description="Render new research reports.",
        command="bob highlights create",
        timeout_seconds=120,
        filters=FileHookFilters(
            projects=("sase",),
            sidecars=("research",),
            path_globs=("20*/**/*.md", "!20*/*/*__*.md"),
            agent_name_globs=("!research.*.cld", "!research.*.cdx"),
            ops=("ADD",),
        ),
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


def test_internal_exec_batch_parses_but_is_hidden_from_help() -> None:
    args = create_parser().parse_args(["file-hook", "exec-batch", "/tmp/batch.json"])
    parser = create_parser()
    file_hook_parser = next(
        action.choices["file-hook"]
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )

    assert args.file_hook_subcommand == "exec-batch"
    assert args.batch == "/tmp/batch.json"
    assert "exec-batch" not in file_hook_parser.format_help()
    assert "history" in file_hook_parser.format_help()
    assert "show" in file_hook_parser.format_help()


def test_file_hook_history_and_show_parse() -> None:
    history = create_parser().parse_args(["file-hook", "history", "-n", "5", "-j"])
    show = create_parser().parse_args(["file-hook", "show", "abc123", "--json"])

    assert history.file_hook_subcommand == "history"
    assert history.limit == 5
    assert history.json is True
    assert show.file_hook_subcommand == "show"
    assert show.audit_id == "abc123"
    assert show.json is True


def test_file_hook_list_json_is_versioned(capsys: Any) -> None:
    code = _handle_file_hook_list_command(
        argparse.Namespace(json=True),
        hooks_fn=lambda: [_hook()],
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["schema_version"] == FILE_HOOK_LIST_JSON_SCHEMA_VERSION == 3
    assert payload["count"] == 1
    entry = payload["file_hooks"][0]
    assert entry["source_layer"] == "user"
    assert entry["timeout_seconds"] == 120
    assert entry["filters"]["path_globs"] == [
        "20*/**/*.md",
        "!20*/*/*__*.md",
    ]
    assert entry["filters"]["agent_name_globs"] == [
        "!research.*.cld",
        "!research.*.cdx",
    ]
    assert entry["filters"]["projects"] == ["sase"]
    assert entry["filters"]["sidecars"] == ["research"]
    assert entry["filters"]["ops"] == ["ADD"]
    assert "filters" in entry
    assert "path_globs" not in entry
    assert "agent_name_globs" not in entry
    assert "projects" not in entry
    assert "sidecars" not in entry
    assert "ops" not in entry
    assert "globs" not in entry


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
    assert "path_globs: 20*/**/*.md, !20*/*/*__*.md" in rendered
    # The agent-name row wraps at this width, so assert its parts separately.
    assert "agent_name_globs: !research.*.cld," in rendered
    assert "!research.*.cdx" in rendered
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


def test_file_hook_history_and_show_render_audits(
    tmp_path: Any,
    capsys: Any,
) -> None:
    from pathlib import Path
    from unittest.mock import MagicMock

    from sase.config.file_hooks import FileHookConfig, FileHookFilters
    from sase.file_hooks.engine import CapturedFileEvent

    repo = tmp_path / "repo"
    repo.mkdir()
    event = CapturedFileEvent(
        abs_path=str(repo / "report.md"),
        repo_root=str(repo),
        project="sase",
        repo_kind="sidecar:research",
        sidecar_role="research",
        rel_path="report.md",
        op="ADD",
        agent_name="research.0v.final",
    )
    hook = FileHookConfig(
        name="research-highlights",
        description=None,
        command="true",
        timeout_seconds=120,
        filters=FileHookFilters(),
    )
    result = dispatch_file_hook_events(
        [event],
        hooks=[hook],
        popen=lambda *args, **kwargs: MagicMock(),
        producer="artifact",
    )
    assert result.audit_id

    history_code = _handle_file_hook_history_command(
        argparse.Namespace(json=True, limit=20)
    )
    history_payload = json.loads(capsys.readouterr().out)
    assert history_code == 0
    assert history_payload["schema_version"] == FILE_HOOK_HISTORY_JSON_SCHEMA_VERSION
    assert history_payload["count"] == 1
    assert history_payload["audits"][0]["outcome"] == "batch_dispatched"
    assert history_payload["audits"][0]["producer"] == "artifact"

    show_code = _handle_file_hook_show_command(
        argparse.Namespace(json=True, audit_id=result.audit_id[:8])
    )
    show_payload = json.loads(capsys.readouterr().out)
    assert show_code == 0
    assert show_payload["audit_id"] == result.audit_id
    assert show_payload["matched_hook_names"] == ["research-highlights"]

    missing = _handle_file_hook_show_command(
        argparse.Namespace(json=False, audit_id="missing")
    )
    assert missing == 1
    assert "not found" in capsys.readouterr().err
