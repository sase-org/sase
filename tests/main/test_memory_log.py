"""Tests for ``sase memory log`` rendering and filtering."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from sase.memory.legacy_glossary_read_log import (
    GlossaryReadEvent,
    glossary_read_log_path,
)
from sase.memory.cli_log import _render_memory_log_summary, handle_memory_log_command
from sase.memory.read_log import append_memory_read_event
from sase.main.parser import create_parser

from .memory_handler_helpers import memory_read_event


def test_memory_log_summary_renders_grouped_read_stats() -> None:
    events = (
        memory_read_event(
            read_id="read-a",
            canonical_path="foo.md",
            agent_name="agent-a",
            timestamp="2026-05-23T12:00:00+00:00",
            reason="Need foo context",
        ),
        memory_read_event(
            read_id="read-b",
            canonical_path="foo.md",
            agent_name="agent-b",
            timestamp="2026-05-23T12:01:00+00:00",
            reason="Need updated foo context",
        ),
        memory_read_event(
            read_id="read-c",
            canonical_path="bar.md",
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
    assert "foo.md" in text
    assert "bar.md" in text
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
        path_filter="missing.md",
    )

    text = output.getvalue()
    assert "path=missing.md" in text
    assert "No memory read events match the current filters." in text


def test_memory_log_path_drilldown_renders_individual_events() -> None:
    events = (
        memory_read_event(
            read_id="read-a",
            canonical_path="foo.md",
            agent_name="agent-a",
            timestamp="2026-05-23T12:00:00+00:00",
            reason="Need foo context",
        ),
        memory_read_event(
            read_id="read-b",
            canonical_path="foo.md",
            agent_name="agent-b",
            timestamp="2026-05-23T12:01:00+00:00",
            reason="Need updated foo context",
        ),
    )
    output = StringIO()
    console = Console(
        file=output,
        force_terminal=False,
        color_system=None,
        width=180,
    )

    _render_memory_log_summary(
        events,
        console=console,
        project_name="demo",
        path_filter="foo.md",
    )

    text = output.getvalue()
    assert "path=foo.md" in text
    assert "Memory Paths (1)" in text
    assert "Memory Read Events (2)" in text
    assert "read-a" in text
    assert "read-b" in text
    assert "agent-b" in text
    assert "Need updated foo context" in text


def test_memory_log_composed_filters_render_matching_agent_drilldown() -> None:
    events = (
        memory_read_event(
            read_id="read-b",
            canonical_path="foo.md",
            agent_name="agent-b",
            timestamp="2026-05-23T12:01:00+00:00",
            reason="Need updated foo context",
        ),
    )
    output = StringIO()
    console = Console(
        file=output,
        force_terminal=False,
        color_system=None,
        width=180,
    )

    _render_memory_log_summary(
        events,
        console=console,
        project_name="demo",
        path_filter="foo.md",
        agent_filter="agent-b",
    )

    text = output.getvalue()
    assert "path=foo.md, agent=agent-b" in text
    assert "Memory Paths (1)" in text
    assert "Agents (1)" in text
    assert "Memory Read Events (1)" in text
    assert "read-b" in text
    assert "foo.md" in text
    assert "agent-b" in text


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
        memory_read_event(
            read_id="read-a",
            canonical_path="foo.md",
            agent_name="agent-a",
            timestamp="2026-05-23T12:00:00+00:00",
            reason="First",
            project=project,
        )
    )
    append_memory_read_event(
        memory_read_event(
            read_id="read-b",
            canonical_path="foo.md",
            agent_name="agent-b",
            timestamp="2026-05-23T12:01:00+00:00",
            reason="Second",
            project=project,
        )
    )
    append_memory_read_event(
        memory_read_event(
            read_id="read-c",
            canonical_path="bar.md",
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
            "foo.md",
            "--agent",
            "agent-b",
            "--json",
        ]
    )

    handle_memory_log_command(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "filters": {"agent": "agent-b", "path": "foo.md"},
        "project": project,
        "summary": [
            {
                "canonical_path": "foo.md",
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


def _seed_glossary_read_event(tmp_path: Path, *, project: str) -> None:
    event = GlossaryReadEvent(
        schema_version=1,
        id="glossary-read-a",
        timestamp="2026-05-23T12:00:00+00:00",
        project=project,
        cwd=str(tmp_path),
        agent_name="agent-a",
        agent_source="SASE_AGENT_NAME",
        artifacts_dir=None,
        reason="Need Stitch",
        terms=("Stitch",),
        related_terms=("Patch",),
        depth_limit=None,
        definition_bytes=0,
        source_path=None,
    )
    log_path = glossary_read_log_path(project)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        json.dumps(
            {
                "schema_version": event.schema_version,
                "id": event.id,
                "timestamp": event.timestamp,
                "project": event.project,
                "cwd": event.cwd,
                "agent_name": event.agent_name,
                "agent_source": event.agent_source,
                "artifacts_dir": event.artifacts_dir,
                "reason": event.reason,
                "terms": list(event.terms),
                "related_terms": list(event.related_terms),
                "depth_limit": event.depth_limit,
                "definition_bytes": event.definition_bytes,
                "source_path": event.source_path,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def test_memory_log_include_glossary_json_adds_glossary_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path.name
    home = tmp_path / "home"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    _seed_glossary_read_event(tmp_path, project=project)
    args = create_parser().parse_args(
        ["memory", "log", "--include", "glossary", "--json"]
    )

    handle_memory_log_command(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["glossary_summary"] == {"total_events": 1, "total_terms": 1}
    (event,) = payload["glossary_events"]
    assert event["terms"] == ["Stitch"]
    assert event["related_terms"] == ["Patch"]


def test_memory_log_include_glossary_rich_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path.name
    home = tmp_path / "home"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    _seed_glossary_read_event(tmp_path, project=project)
    output = StringIO()
    console = Console(file=output, force_terminal=False, color_system=None, width=180)
    args = create_parser().parse_args(["memory", "log", "--include", "glossary"])

    handle_memory_log_command(args, console=console)

    text = output.getvalue()
    assert "Glossary Read Events (1)" in text
    assert "Stitch" in text


def test_memory_log_json_id_outputs_raw_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path.name
    home = tmp_path / "home"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    event = memory_read_event(
        read_id="read-b",
        canonical_path="foo.md",
        agent_name="agent-b",
        timestamp="2026-05-23T12:01:00+00:00",
        reason="Need updated foo context",
        project=project,
    )
    append_memory_read_event(event)
    args = create_parser().parse_args(["memory", "log", "--id", "read-b", "--json"])

    handle_memory_log_command(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "agent_name": "agent-b",
        "agent_source": "SASE_AGENT_NAME",
        "artifacts_dir": None,
        "byte_count": 123,
        "canonical_path": "foo.md",
        "cwd": "/tmp/demo",
        "depth": None,
        "frontmatter_stripped": True,
        "id": "read-b",
        "included_targets": [],
        "kind": "note",
        "project": project,
        "reason": "Need updated foo context",
        "resolved_path": "/tmp/demo/memory/foo.md",
        "resolved_targets": [],
        "schema_version": 1,
        "scope_origin": [],
        "selectors": [],
        "timestamp": "2026-05-23T12:01:00+00:00",
    }


def test_memory_log_id_drilldown_renders_full_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path.name
    home = tmp_path / "home"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    append_memory_read_event(
        memory_read_event(
            read_id="read-b",
            canonical_path="foo.md",
            agent_name="agent-b",
            timestamp="2026-05-23T12:01:00+00:00",
            reason="Need updated foo context",
            project=project,
        )
    )
    output = StringIO()
    console = Console(
        file=output,
        force_terminal=False,
        color_system=None,
        width=180,
    )
    args = create_parser().parse_args(["memory", "log", "--id", "read-b"])

    handle_memory_log_command(args, console=console)

    text = output.getvalue()
    assert "Memory Read Event read-b" in text
    assert "Timestamp" in text
    assert "2026-05-23 08:01:00" in text
    assert "Agent" in text
    assert "agent-b" in text
    assert "Agent source" in text
    assert "SASE_AGENT_NAME" in text
    assert "Reason" in text
    assert "Need updated foo context" in text
    assert "CWD" in text
    assert "/tmp/demo" in text
    assert "Memory path" in text
    assert "foo.md" in text
    assert "Resolved path" in text
    assert "/tmp/demo/memory/foo.md" in text
    assert "Artifacts dir" in text
    assert "none" in text


def test_memory_log_unknown_id_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    args = create_parser().parse_args(["memory", "log", "--id", "missing"])

    with pytest.raises(SystemExit) as exc:
        handle_memory_log_command(args)

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert captured.out == ""
    assert "unknown memory read id: missing" in captured.err
