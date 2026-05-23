"""Tests for the ``sase memory`` parser and handler."""

from __future__ import annotations

import argparse
import json
from io import StringIO
from pathlib import Path
import sys

import pytest
from rich.console import Console

from sase.memory.cli_list import _render_memory_inventory
from sase.memory.cli_log import _render_memory_log_summary, handle_memory_log_command
from sase.memory.cli_read import handle_memory_read_command
from sase.memory.inventory import build_memory_inventory
from sase.memory.read_log import (
    MemoryReadEvent,
    append_memory_read_event,
    memory_read_log_path,
    read_memory_read_events,
)
from sase.main import memory_handler
from sase.main.parser import create_parser


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _memory_read_event(
    *,
    read_id: str,
    canonical_path: str,
    agent_name: str,
    timestamp: str,
    reason: str,
    project: str = "demo",
) -> MemoryReadEvent:
    return MemoryReadEvent(
        schema_version=1,
        id=read_id,
        timestamp=timestamp,
        project=project,
        cwd="/tmp/demo",
        canonical_path=canonical_path,
        resolved_path=f"/tmp/demo/memory/{canonical_path}",
        agent_name=agent_name,
        agent_source="SASE_AGENT_NAME",
        artifacts_dir=None,
        reason=reason,
        byte_count=123,
        frontmatter_stripped=True,
    )


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

    default_args = parser.parse_args(["memory"])
    assert default_args.command == "memory"
    assert default_args.memory_subcommand is None


def test_parser_requires_memory_read_reason() -> None:
    parser = create_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["memory", "read", "long/foo.md"])


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
    assert "AGENTS.md" in text
    assert "loaded" in text
    assert "memory/short/base.md" in text
    assert "referenced" in text
    assert "memory/long/index.md" in text
    assert "available" in text
    assert "memory/long/orphan.md" in text
    assert "missing" in text
    assert "memory/long/missing.md" in text
    assert "@path loads file contents" in text
    assert "AGENTS.md is counted because it is loaded instruction context." in text
    assert "Plain memory/... paths are visible references only." in text
    assert "Dynamic memory under .sase/memory is prompt-dependent" in text
    assert "agent launch" in text


def test_memory_read_prints_body_and_appends_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    artifacts_dir = tmp_path / "artifacts"
    _write(
        tmp_path / "memory" / "long" / "foo.md",
        "---\nkeywords: [foo]\n---\n# Body\n\n",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-a")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))

    handle_memory_read_command(
        argparse.Namespace(memory_path="long/foo.md", reason=" Need foo ")
    )

    captured = capsys.readouterr()
    assert captured.out == "# Body\n\n"
    assert captured.err == ""
    events = read_memory_read_events(log_path=memory_read_log_path(cwd=tmp_path))
    assert len(events) == 1
    assert events[0].canonical_path == "long/foo.md"
    assert events[0].agent_name == "agent-a"
    assert events[0].artifacts_dir == str(artifacts_dir)
    assert events[0].reason == "Need foo"
    assert events[0].frontmatter_stripped is True


def test_memory_read_rejects_short_memory_without_logging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    _write(tmp_path / "memory" / "short" / "foo.md", "# Short\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-a")

    with pytest.raises(SystemExit) as exc:
        handle_memory_read_command(
            argparse.Namespace(memory_path="short/foo.md", reason="Need short")
        )

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert captured.out == ""
    assert "memory/short" in captured.err
    assert not memory_read_log_path(cwd=tmp_path).exists()


def test_memory_read_rejects_blank_reason_before_logging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    _write(tmp_path / "memory" / "long" / "foo.md", "# Body\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-a")

    with pytest.raises(SystemExit) as exc:
        handle_memory_read_command(
            argparse.Namespace(memory_path="long/foo.md", reason="   ")
        )

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert captured.out == ""
    assert "reason" in captured.err
    assert not memory_read_log_path(cwd=tmp_path).exists()


def test_memory_read_requires_agent_attribution_before_logging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    _write(tmp_path / "memory" / "long" / "foo.md", "# Body\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    monkeypatch.delenv("SASE_AGENT", raising=False)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)

    with pytest.raises(SystemExit) as exc:
        handle_memory_read_command(
            argparse.Namespace(memory_path="long/foo.md", reason="Need foo")
        )

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert captured.out == ""
    assert "agent attribution" in captured.err
    assert not memory_read_log_path(cwd=tmp_path).exists()


def test_memory_list_dashboard_renders_home_context_paths(tmp_path: Path) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    _write(project / "AGENTS.md", "@memory/short/project.md\n")
    _write(project / "memory" / "short" / "project.md", "# Project\n")
    _write(home / "AGENTS.md", "@memory/short/home.md\n")
    _write(home / "memory" / "short" / "home.md", "# Home\n")

    inventory = build_memory_inventory(project, home_root=home)
    output = StringIO()
    console = Console(
        file=output,
        force_terminal=False,
        color_system=None,
        width=140,
    )

    _render_memory_inventory(inventory, console=console, project_name="demo")

    text = output.getvalue()
    assert "AGENTS.md" in text
    assert "memory/short/project.md" in text
    assert "~/AGENTS.md" in text
    assert "~/memory/short/home.md" in text
    assert "~/AGENTS.md -> @memory/short/home.md" in text


def test_memory_log_summary_renders_grouped_read_stats() -> None:
    events = (
        _memory_read_event(
            read_id="read-a",
            canonical_path="long/foo.md",
            agent_name="agent-a",
            timestamp="2026-05-23T12:00:00+00:00",
            reason="Need foo context",
        ),
        _memory_read_event(
            read_id="read-b",
            canonical_path="long/foo.md",
            agent_name="agent-b",
            timestamp="2026-05-23T12:01:00+00:00",
            reason="Need updated foo context",
        ),
        _memory_read_event(
            read_id="read-c",
            canonical_path="long/bar.md",
            agent_name="agent-a",
            timestamp="2026-05-23T12:02:00+00:00",
            reason="Need bar context",
        ),
    )
    output = StringIO()
    console = Console(
        file=output,
        force_terminal=False,
        color_system=None,
        width=160,
    )

    _render_memory_log_summary(events, console=console, project_name="demo")

    text = output.getvalue()
    assert "SASE Memory Read Log" in text
    assert "Read events" in text
    assert "3" in text
    assert "Memory Paths (2)" in text
    assert "long/foo.md" in text
    assert "long/bar.md" in text
    assert "agent-b" in text
    assert "Need updated foo context" in text


def test_memory_log_summary_renders_empty_state_for_unknown_filter() -> None:
    output = StringIO()
    console = Console(
        file=output,
        force_terminal=False,
        color_system=None,
        width=120,
    )

    _render_memory_log_summary(
        (),
        console=console,
        project_name="demo",
        path_filter="long/missing.md",
    )

    text = output.getvalue()
    assert "path=long/missing.md" in text
    assert "No memory read events match the current filters." in text


def test_memory_log_json_output_filters_and_summarizes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path.name
    home = tmp_path / "home"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    append_memory_read_event(
        _memory_read_event(
            read_id="read-a",
            canonical_path="long/foo.md",
            agent_name="agent-a",
            timestamp="2026-05-23T12:00:00+00:00",
            reason="First",
            project=project,
        )
    )
    append_memory_read_event(
        _memory_read_event(
            read_id="read-b",
            canonical_path="long/foo.md",
            agent_name="agent-b",
            timestamp="2026-05-23T12:01:00+00:00",
            reason="Second",
            project=project,
        )
    )
    append_memory_read_event(
        _memory_read_event(
            read_id="read-c",
            canonical_path="long/bar.md",
            agent_name="agent-b",
            timestamp="2026-05-23T12:02:00+00:00",
            reason="Third",
            project=project,
        )
    )
    args = create_parser().parse_args(
        [
            "memory",
            "log",
            "--path",
            "long/foo.md",
            "--agent",
            "agent-b",
            "--json",
        ]
    )

    handle_memory_log_command(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "filters": {"agent": "agent-b", "path": "long/foo.md"},
        "project": project,
        "summary": [
            {
                "canonical_path": "long/foo.md",
                "distinct_agent_count": 1,
                "last_agent": "agent-b",
                "last_read_at": "2026-05-23T12:01:00+00:00",
                "last_reason": "Second",
                "read_count": 1,
            }
        ],
        "total_agents": 1,
        "total_memory_paths": 1,
        "total_reads": 1,
    }
