"""Tests for ``sase glossary log``."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from sase.glossary import cli_log
from sase.glossary.cli_common import GlossaryCliError
from sase.glossary.read_log import (
    GlossaryReadEvent,
    append_glossary_read_event,
    glossary_read_log_path,
)
from sase.main.parser import create_parser


def _event(**overrides: object) -> GlossaryReadEvent:
    payload: dict[str, object] = {
        "schema_version": 1,
        "id": "read-a",
        "timestamp": "2026-05-23T12:00:00+00:00",
        "project": "sase",
        "cwd": "/tmp/demo",
        "agent_name": "agent-a",
        "agent_source": "SASE_AGENT_NAME",
        "artifacts_dir": "/tmp/artifacts",
        "reason": "Need hood",
        "terms": ("Agent Hood",),
        "related_terms": ("Sase Agent",),
        "depth_limit": None,
        "definition_bytes": 42,
        "source_path": "/tmp/sase/sase/sase.yml",
    }
    payload.update(overrides)
    return GlossaryReadEvent(**payload)  # type: ignore[arg-type]


def _patch_log_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "sase.glossary.read_log.sase_projects_dir",
        lambda: tmp_path / "projects",
    )
    monkeypatch.setattr(
        "sase.glossary.read_log.resolve_project_alias_ref",
        lambda ref: ref,
    )
    monkeypatch.setattr(
        cli_log, "resolve_glossary_cli_project_name", lambda *_a, **_kw: "sase"
    )


def _append(*events: GlossaryReadEvent) -> None:
    for event in events:
        append_glossary_read_event(
            event, log_path=glossary_read_log_path(event.project)
        )


def _console(output: StringIO) -> Console:
    return Console(file=output, force_terminal=False, color_system=None, width=180)


def _sample_events() -> tuple[GlossaryReadEvent, ...]:
    return (
        _event(),
        _event(
            id="read-b",
            timestamp="2026-05-23T12:01:00+00:00",
            agent_name="agent-b",
            reason="Need stitch",
            terms=("Stitch",),
            related_terms=(),
            definition_bytes=10,
        ),
        _event(
            id="read-c",
            timestamp="2026-05-23T12:02:00+00:00",
            reason="Need hood again",
            terms=("Agent Hood",),
            related_terms=("Sase Agent",),
            definition_bytes=20,
        ),
    )


def test_log_empty_state_is_clean_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_log_store(monkeypatch, tmp_path)
    args = create_parser().parse_args(["glossary", "log"])

    cli_log.handle_glossary_log_command(args)

    captured = capsys.readouterr()
    assert captured.out == "No glossary read events found.\n"
    assert captured.err == ""


def test_log_empty_filter_mentions_filters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_log_store(monkeypatch, tmp_path)
    _append(*_sample_events())
    args = create_parser().parse_args(["glossary", "log", "-t", "missing"])

    cli_log.handle_glossary_log_command(args)

    captured = capsys.readouterr()
    assert captured.out == (
        "No glossary read events match the current filters (term=missing).\n"
    )


def test_log_summary_renders_by_term_agent_and_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_log_store(monkeypatch, tmp_path)
    _append(*_sample_events())
    output = StringIO()
    args = create_parser().parse_args(["glossary", "log"])

    cli_log.handle_glossary_log_command(args, console=_console(output))

    text = output.getvalue()
    assert "SASE Glossary Read Log" in text
    assert "Filters" in text
    assert "none" in text
    assert "Read events" in text
    assert "Requested terms" in text
    assert "Definition bytes" in text
    assert "Need hood again" in text
    assert "Terms (3)" in text
    assert "Agent Hood" in text
    assert "Sase Agent" in text
    assert "Stitch" in text
    assert "Agents (2)" in text
    assert "agent-a" in text
    assert "agent-b" in text
    assert "Glossary Read Events (3)" in text
    assert "read-a" in text
    assert "read-b" in text
    assert "read-c" in text
    assert "Need stitch" in text


def test_log_filters_are_reflected_in_header(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_log_store(monkeypatch, tmp_path)
    _append(*_sample_events())
    output = StringIO()
    args = create_parser().parse_args(
        ["glossary", "log", "-t", "agent-hood", "-a", "agent-a"]
    )

    cli_log.handle_glossary_log_command(args, console=_console(output))

    text = output.getvalue()
    assert "term=agent-hood, agent=agent-a" in text
    assert "Glossary Read Events (2)" in text
    assert "read-a" in text
    assert "read-c" in text
    assert "read-b" not in text
    assert "Need stitch" not in text


def test_log_json_is_deterministic_and_sorted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_log_store(monkeypatch, tmp_path)
    _append(*_sample_events())
    args = create_parser().parse_args(["glossary", "log", "-f", "json"])

    cli_log.handle_glossary_log_command(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["project"] == "sase"
    assert payload["total_reads"] == 3
    assert payload["distinct_agents"] == 2
    assert payload["distinct_requested_terms"] == 2
    assert payload["definition_bytes"] == 72
    assert payload["most_recent_read_at"] == "2026-05-23T12:02:00+00:00"
    assert payload["most_recent_agent"] == "agent-a"
    assert payload["most_recent_reason"] == "Need hood again"
    assert payload["filters"] == {"agent": None, "term": None}
    assert [item["term"] for item in payload["by_term"]] == [
        "Agent Hood",
        "Sase Agent",
        "Stitch",
    ]
    assert [item["agent_name"] for item in payload["by_agent"]] == [
        "agent-a",
        "agent-b",
    ]
    assert [item["id"] for item in payload["events"]] == ["read-c", "read-b", "read-a"]


def test_log_json_empty_is_structured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_log_store(monkeypatch, tmp_path)
    args = create_parser().parse_args(["glossary", "log", "-f", "json"])

    cli_log.handle_glossary_log_command(args)

    assert json.loads(capsys.readouterr().out) == {
        "by_agent": [],
        "by_term": [],
        "definition_bytes": 0,
        "distinct_agents": 0,
        "distinct_requested_terms": 0,
        "events": [],
        "filters": {"agent": None, "term": None},
        "most_recent_agent": None,
        "most_recent_read_at": None,
        "most_recent_reason": None,
        "project": "sase",
        "total_reads": 0,
    }


def test_log_id_renders_full_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_log_store(monkeypatch, tmp_path)
    _append(*_sample_events())
    output = StringIO()
    args = create_parser().parse_args(["glossary", "log", "-i", "read-b"])

    cli_log.handle_glossary_log_command(args, console=_console(output))

    text = output.getvalue()
    assert "Glossary Read Event read-b" in text
    assert "Need stitch" in text
    assert "agent-b" in text
    assert "Stitch" in text
    assert "unlimited" in text
    assert "/tmp/demo" in text


def test_log_json_id_outputs_raw_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_log_store(monkeypatch, tmp_path)
    event = _event(
        id="read-b", reason="Need stitch", terms=("Stitch",), related_terms=()
    )
    _append(event)
    args = create_parser().parse_args(["glossary", "log", "-i", "read-b", "-f", "json"])

    cli_log.handle_glossary_log_command(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == "read-b"
    assert payload["reason"] == "Need stitch"
    assert payload["terms"] == ["Stitch"]
    assert payload["related_terms"] == []
    assert payload["agent_name"] == "agent-a"


def test_log_unknown_id_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_log_store(monkeypatch, tmp_path)
    _append(*_sample_events())
    args = create_parser().parse_args(["glossary", "log", "-i", "missing"])

    with pytest.raises(SystemExit) as exc:
        cli_log.handle_glossary_log_command(args)

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert captured.out == ""
    assert "unknown glossary read id: missing" in captured.err


def test_log_ambiguous_id_prefix_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_log_store(monkeypatch, tmp_path)
    _append(*_sample_events())
    args = create_parser().parse_args(["glossary", "log", "-i", "read-"])

    with pytest.raises(SystemExit) as exc:
        cli_log.handle_glossary_log_command(args)

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert captured.out == ""
    assert "glossary read id prefix is ambiguous: read-" in captured.err
    assert "read-a" in captured.err
    assert "read-b" in captured.err


def test_log_skips_corrupt_jsonl_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_log_store(monkeypatch, tmp_path)
    _append(_event())
    log_path = glossary_read_log_path("sase")
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write("not json\n")
        handle.write(json.dumps({"schema_version": 2, "id": "other"}) + "\n")
    args = create_parser().parse_args(["glossary", "log", "-f", "json"])

    cli_log.handle_glossary_log_command(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["total_reads"] == 1
    assert payload["events"][0]["id"] == "read-a"


def test_log_exits_nonzero_on_project_resolution_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_resolve(*_a: object, **_kw: object) -> str:
        raise GlossaryCliError("no such project: missing")

    monkeypatch.setattr(cli_log, "resolve_glossary_cli_project_name", fake_resolve)
    args = create_parser().parse_args(["glossary", "log", "-p", "missing"])

    with pytest.raises(SystemExit) as exc:
        cli_log.handle_glossary_log_command(args)

    assert exc.value.code == 1
    assert "no such project: missing" in capsys.readouterr().err
