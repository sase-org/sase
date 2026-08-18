"""Tests for ``sase glossary read``."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from sase.glossary import cli_read, cli_show
from sase.glossary.cli_common import GlossaryCliError, ResolvedGlossaryProject
from sase.glossary.read_log import (
    glossary_read_log_path,
    read_glossary_read_events,
)
from sase.glossary.resolution import resolve_glossary_closure
from sase.main.parser import create_parser

from .glossary_cli_helpers import diamond_resolved_glossary_project


def _patch_resolved(
    monkeypatch: pytest.MonkeyPatch, resolved: ResolvedGlossaryProject
) -> None:
    monkeypatch.setattr(
        cli_show, "resolve_glossary_cli_project", lambda *_a, **_kw: resolved
    )


def _patch_read_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "sase.glossary.read_log.sase_projects_dir",
        lambda: tmp_path / "projects",
    )
    monkeypatch.setattr(
        "sase.glossary.read_log.resolve_project_alias_ref",
        lambda ref: ref,
    )
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-a")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "artifacts"))


def _console(output: StringIO) -> Console:
    return Console(file=output, force_terminal=False, color_system=None, width=160)


def test_read_records_event_then_matches_show_stdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved = diamond_resolved_glossary_project()
    _patch_resolved(monkeypatch, resolved)
    _patch_read_store(monkeypatch, tmp_path)
    show_out = StringIO()
    read_out = StringIO()
    show_args = create_parser().parse_args(["glossary", "show", "Alpha"])
    read_args = create_parser().parse_args(
        ["glossary", "read", "Alpha", "-r", " Need hood "]
    )

    cli_show.handle_glossary_show_command(show_args, console=_console(show_out))
    cli_read.handle_glossary_read_command(read_args, console=_console(read_out))

    assert read_out.getvalue() == show_out.getvalue()
    events = read_glossary_read_events(log_path=glossary_read_log_path("sase"))
    assert len(events) == 1
    event = events[0]
    closure = resolve_glossary_closure(resolved.catalog, resolved.compiled, ("Alpha",))
    expected_bytes = sum(
        len(node.entry.definition.strip().encode("utf-8")) for node in closure.nodes
    )
    assert event.reason == "Need hood"
    assert event.agent_name == "agent-a"
    assert event.project == "sase"
    assert event.terms == ("Alpha",)
    assert event.related_terms == ("Beta", "Gamma", "Delta")
    assert event.depth_limit is None
    assert event.definition_bytes == expected_bytes
    assert event.source_path == resolved.config_path


def test_read_json_stdout_matches_show(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_resolved(monkeypatch, diamond_resolved_glossary_project())
    _patch_read_store(monkeypatch, tmp_path)
    show_args = create_parser().parse_args(["glossary", "show", "Alpha", "-f", "json"])
    read_args = create_parser().parse_args(
        ["glossary", "read", "Alpha", "-f", "json", "-r", "Need hood"]
    )

    cli_show.handle_glossary_show_command(show_args)
    show_payload = json.loads(capsys.readouterr().out)
    cli_read.handle_glossary_read_command(read_args)
    read_payload = json.loads(capsys.readouterr().out)

    assert read_payload == show_payload


def test_read_rejects_blank_reason_without_recording(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_resolved(monkeypatch, diamond_resolved_glossary_project())
    _patch_read_store(monkeypatch, tmp_path)
    args = create_parser().parse_args(["glossary", "read", "Alpha", "-r", "   "])

    with pytest.raises(SystemExit) as exc:
        cli_read.handle_glossary_read_command(args)

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "glossary read reason must not be empty" in captured.err
    assert read_glossary_read_events(log_path=glossary_read_log_path("sase")) == ()


def test_read_rejects_missing_agent_identity_without_recording(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_resolved(monkeypatch, diamond_resolved_glossary_project())
    _patch_read_store(monkeypatch, tmp_path)
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    args = create_parser().parse_args(["glossary", "read", "Alpha", "-r", "Need hood"])

    with pytest.raises(SystemExit) as exc:
        cli_read.handle_glossary_read_command(args)

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "glossary reads require agent attribution" in captured.err
    assert read_glossary_read_events(log_path=glossary_read_log_path("sase")) == ()


def test_read_unknown_term_records_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_resolved(monkeypatch, diamond_resolved_glossary_project())
    _patch_read_store(monkeypatch, tmp_path)
    args = create_parser().parse_args(["glossary", "read", "Zzz", "-r", "Need hood"])

    with pytest.raises(SystemExit) as exc:
        cli_read.handle_glossary_read_command(args)

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unknown glossary term: Zzz" in captured.err
    assert read_glossary_read_events(log_path=glossary_read_log_path("sase")) == ()


def test_read_project_error_records_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_resolve(*_a: object, **_kw: object) -> ResolvedGlossaryProject:
        raise GlossaryCliError("sase has no glossary configured")

    monkeypatch.setattr(cli_show, "resolve_glossary_cli_project", fake_resolve)
    _patch_read_store(monkeypatch, tmp_path)
    args = create_parser().parse_args(
        ["glossary", "read", "Alpha", "-p", "sase", "-r", "Need hood"]
    )

    with pytest.raises(SystemExit) as exc:
        cli_read.handle_glossary_read_command(args)

    assert exc.value.code == 1
    assert "sase has no glossary configured" in capsys.readouterr().err
    assert read_glossary_read_events(log_path=glossary_read_log_path("sase")) == ()


def test_read_scopes_event_to_resolved_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved = diamond_resolved_glossary_project()
    resolved = ResolvedGlossaryProject(
        project_name="bob",
        catalog=resolved.catalog,
        compiled=resolved.compiled,
        config_path=resolved.config_path,
    )
    _patch_resolved(monkeypatch, resolved)
    _patch_read_store(monkeypatch, tmp_path)
    args = create_parser().parse_args(
        ["glossary", "read", "Alpha", "-p", "bob", "-d", "0", "-r", "Need alpha"]
    )

    cli_read.handle_glossary_read_command(args, console=_console(StringIO()))

    assert read_glossary_read_events(log_path=glossary_read_log_path("sase")) == ()
    events = read_glossary_read_events(log_path=glossary_read_log_path("bob"))
    assert len(events) == 1
    assert events[0].project == "bob"
    assert events[0].terms == ("Alpha",)
    assert events[0].related_terms == ()
    assert events[0].depth_limit == 0


def test_read_multi_term_records_one_event_with_disjoint_related(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved = diamond_resolved_glossary_project()
    _patch_resolved(monkeypatch, resolved)
    _patch_read_store(monkeypatch, tmp_path)
    args = create_parser().parse_args(
        ["glossary", "read", "Alpha", "Gamma", "-r", "Need both"]
    )

    cli_read.handle_glossary_read_command(args, console=_console(StringIO()))

    events = read_glossary_read_events(log_path=glossary_read_log_path("sase"))
    assert len(events) == 1
    assert events[0].terms == ("Alpha", "Gamma")
    assert events[0].related_terms == ("Beta", "Delta")
    assert set(events[0].terms).isdisjoint(events[0].related_terms)


def test_read_batch_unknown_term_records_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_resolved(monkeypatch, diamond_resolved_glossary_project())
    _patch_read_store(monkeypatch, tmp_path)
    args = create_parser().parse_args(
        ["glossary", "read", "Alpha", "Zzz", "-r", "Need both"]
    )

    with pytest.raises(SystemExit) as exc:
        cli_read.handle_glossary_read_command(args)

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert captured.out == ""
    assert "1 of 2 glossary references did not resolve" not in captured.err
    assert "unknown glossary term: Zzz" in captured.err
    assert read_glossary_read_events(log_path=glossary_read_log_path("sase")) == ()
