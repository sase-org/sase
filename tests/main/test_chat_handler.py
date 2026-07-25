"""Tests for the 'sase chat' parser, handler, and CLI subcommands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from sase.chat.cli_list import handle_chat_list
from sase.chat.cli_show import handle_chat_show
from sase.history.chat_catalog import ChatTranscriptInfo
from sase.history.chat_catalog_provenance import (
    CHAT_PROVENANCE_VALUES,
    ChatCatalogEntry,
    ChatCatalogSnapshot,
    chat_provenance_badge,
)
from sase.main.chat_handler import handle_chat_command
from sase.main.parser import create_parser

from tests.conftest import redirect_sase_home


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _setup_fake_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    sase_home = tmp_path / ".sase"
    sase_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    redirect_sase_home(monkeypatch, sase_home)
    return sase_home


def _write_chat(
    sase_home: Path,
    basename: str,
    *,
    workflow: str = "run",
    agent: str | None = None,
    prompt: str = "Hello",
    response: str = "World",
    shard: str = "202604",
) -> Path:
    chat_dir = sase_home / "chats" / shard
    chat_dir.mkdir(parents=True, exist_ok=True)
    path = chat_dir / f"{basename}.md"
    header = f"# Chat History - {workflow}"
    if agent:
        header += f" ({agent})"
    body = f"{header}\n\n## Prompt\n\n{prompt}\n\n## Response\n\n{response}\n"
    path.write_text(body, encoding="utf-8")
    return path


def _info(**overrides: Any) -> ChatTranscriptInfo:
    defaults: dict[str, Any] = {
        "path": "~/.sase/chats/202604/branch-run-260429_101500.md",
        "absolute_path": "/abs/branch-run-260429_101500.md",
        "basename": "branch-run-260429_101500",
        "mtime": "2026-04-29T10:15:08-04:00",
        "size_bytes": 123,
        "workflow": "run",
        "agent": None,
        "timestamp": "260429_101500",
        "prompt_snippet": "Hello there",
        "response_snippet": "World response",
    }
    defaults.update(overrides)
    return ChatTranscriptInfo(**defaults)


def _entry(**overrides: Any) -> ChatCatalogEntry:
    defaults: dict[str, Any] = {
        "provenance": "local",
        "source_machine": "athena",
        "source_username": "alice",
        "project_key": "sase",
        "agent_artifact_dir": "/abs/artifacts/run/260429_101500",
        "agent_local_name": "alpha",
        "agent_global_name": "athena.alpha",
        "sidecar_repo": None,
        "sidecar_relpath": None,
        "publication_pending": False,
        "publication_last_error": None,
        "publication_quarantined": False,
    }
    provenance_keys = set(defaults)
    defaults.update({k: v for k, v in overrides.items() if k in provenance_keys})
    info = _info(**{k: v for k, v in overrides.items() if k not in provenance_keys})
    return ChatCatalogEntry(
        path=info.path,
        absolute_path=info.absolute_path,
        basename=info.basename,
        mtime=info.mtime,
        size_bytes=info.size_bytes,
        workflow=info.workflow,
        agent=info.agent,
        timestamp=info.timestamp,
        prompt_snippet=info.prompt_snippet,
        response_snippet=info.response_snippet,
        **defaults,
    )


def _snapshot(entries: list[ChatCatalogEntry]) -> ChatCatalogSnapshot:
    return ChatCatalogSnapshot(
        entries=tuple(entries),
        provenance_counts={
            value: sum(e.provenance == value for e in entries)
            for value in CHAT_PROVENANCE_VALUES
        },
        remote_machines=frozenset(
            e.source_machine
            for e in entries
            if e.provenance == "remote" and e.source_machine
        ),
        truncated=False,
    )


def _fake_catalog(entries: list[ChatCatalogEntry]) -> Any:
    """A ``load_chat_catalog`` stand-in that applies the CLI-level filters."""

    calls: list[dict[str, Any]] = []

    def loader(**kwargs: Any) -> ChatCatalogSnapshot:
        calls.append(kwargs)
        provenance = kwargs.get("provenance")
        machine = kwargs.get("machine")
        limit = kwargs.get("limit")
        selected = [
            entry
            for entry in entries
            if (provenance is None or entry.provenance == provenance)
            and (
                machine is None
                or (
                    entry.source_machine is not None
                    and entry.source_machine.casefold() == machine.casefold()
                )
            )
        ]
        if limit is not None:
            selected = selected[:limit]
        return _snapshot(selected)

    loader.calls = calls  # type: ignore[attr-defined]
    return loader


# ===========================================================================
# parser
# ===========================================================================


def test_parser_registers_chat_command() -> None:
    parser = create_parser()
    args = parser.parse_args(["chat", "list", "-j", "-l", "5"])
    assert args.command == "chat"
    assert args.chat_subcommand == "list"
    assert args.json is True
    assert args.limit == 5


def test_parser_show_requires_a_selector() -> None:
    parser = create_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["chat", "show"])


def test_parser_show_rejects_multiple_selectors() -> None:
    parser = create_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["chat", "show", "-n", "alpha", "-p", "/tmp/x.md"])


def test_parser_show_format_choices() -> None:
    parser = create_parser()
    args = parser.parse_args(["chat", "show", "-n", "alpha", "-f", "response"])
    assert args.agent == "alpha"
    assert args.format == "response"
    args = parser.parse_args(["chat", "show", "-b", "x", "-f", "resume"])
    assert args.basename == "x"
    assert args.format == "resume"
    with pytest.raises(SystemExit):
        parser.parse_args(["chat", "show", "-n", "alpha", "-f", "bogus"])


def test_parser_show_default_format_is_raw() -> None:
    parser = create_parser()
    args = parser.parse_args(["chat", "show", "-p", "/tmp/x.md"])
    assert args.format == "raw"


def test_parser_list_short_options() -> None:
    parser = create_parser()
    args = parser.parse_args(["chat", "list", "-q", "foo"])
    assert args.query == "foo"
    assert args.limit == 20  # default
    assert args.machine is None
    assert args.provenance is None


def test_parser_list_provenance_filters() -> None:
    parser = create_parser()
    args = parser.parse_args(["chat", "list", "-P", "remote", "-m", "zeus"])
    assert args.provenance == "remote"
    assert args.machine == "zeus"
    with pytest.raises(SystemExit):
        parser.parse_args(["chat", "list", "-P", "bogus"])


def test_parser_list_provenance_choices_match_catalog() -> None:
    """The CLI choices must not drift from the catalog's provenance states."""
    subparser = _chat_list_subparser()
    choices = next(
        tuple(action.choices or ())
        for action in subparser._actions  # noqa: SLF001 - argparse has no public view
        if action.dest == "provenance"
    )
    assert choices == CHAT_PROVENANCE_VALUES


def _chat_list_subparser() -> argparse.ArgumentParser:
    parser = create_parser()
    command_action = next(
        action
        for action in parser._actions  # noqa: SLF001 - argparse offers no public view
        if isinstance(action, argparse._SubParsersAction)
    )
    chat_parser = command_action.choices["chat"]
    chat_action = next(
        action
        for action in chat_parser._actions  # noqa: SLF001 - see above
        if isinstance(action, argparse._SubParsersAction)
    )
    return chat_action.choices["list"]


# ===========================================================================
# handle_chat_command dispatch
# ===========================================================================


def test_dispatch_list(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _setup_fake_home(monkeypatch, tmp_path)
    args = argparse.Namespace(chat_subcommand="list", json=True, limit=5, query=None)
    with pytest.raises(SystemExit) as excinfo:
        handle_chat_command(args)
    assert excinfo.value.code == 0


def test_dispatch_unknown_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    args = argparse.Namespace(chat_subcommand=None)
    with pytest.raises(SystemExit) as excinfo:
        handle_chat_command(args)
    assert excinfo.value.code == 1
    assert "Usage: sase chat" in capsys.readouterr().out


# ===========================================================================
# sase chat list
# ===========================================================================


def _list_args(**overrides: Any) -> argparse.Namespace:
    defaults: dict[str, Any] = {
        "json": False,
        "limit": 20,
        "machine": None,
        "provenance": None,
        "query": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_list_json_empty(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _setup_fake_home(monkeypatch, tmp_path)
    handle_chat_list(_list_args(json=True))
    out = capsys.readouterr().out
    assert json.loads(out) == []


def test_list_json_shape_and_key_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = _setup_fake_home(monkeypatch, tmp_path)
    _write_chat(
        home,
        "branch-run-planner-260429_101500",
        workflow="run",
        agent="planner",
        prompt="Can you help",
        response="Implemented",
    )
    handle_chat_list(_list_args(json=True))
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    assert len(data) == 1
    row = data[0]
    assert list(row.keys()) == [
        "path",
        "basename",
        "mtime",
        "size_bytes",
        "workflow",
        "agent",
        "timestamp",
        "prompt_snippet",
        "response_snippet",
        "provenance",
        "source_machine",
        "source_username",
        "project_key",
        "agent_artifact_dir",
        "agent_local_name",
        "agent_global_name",
        "sidecar_repo",
        "sidecar_relpath",
        "publication_pending",
        "publication_last_error",
        "publication_quarantined",
    ]
    assert row["provenance"] in CHAT_PROVENANCE_VALUES
    assert row["basename"] == "branch-run-planner-260429_101500"
    assert row["workflow"] == "run"
    assert row["agent"] == "planner"
    assert row["prompt_snippet"] == "Can you help"
    assert row["response_snippet"] == "Implemented"


def test_list_projects_only_local_machine_hood(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        AgentOwnerIdentity,
    )

    identity = AgentIdentitySnapshot(
        AgentOwnerIdentity("alice", "athena"),
        ("athena", "zeus"),
    )
    monkeypatch.setattr(
        AgentIdentitySnapshot,
        "current",
        classmethod(lambda _cls: identity),
    )
    entries = [
        _entry(agent="athena.alpha"),
        _entry(agent="zeus.beta", basename="foreign"),
    ]

    with patch("sase.chat.cli_list.load_chat_catalog", _fake_catalog(entries)):
        handle_chat_list(_list_args(json=True))

    rows = json.loads(capsys.readouterr().out)
    assert [row["agent"] for row in rows] == ["alpha", "zeus.beta"]


def test_list_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = _setup_fake_home(monkeypatch, tmp_path)
    for i in range(5):
        _write_chat(home, f"branch-run-26042{i}_101500")
    handle_chat_list(_list_args(json=True, limit=2))
    data = json.loads(capsys.readouterr().out)
    assert len(data) == 2


def test_list_query(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = _setup_fake_home(monkeypatch, tmp_path)
    _write_chat(home, "alpha-run-260429_101500", prompt="brown fox")
    _write_chat(home, "beta-run-260429_101501", prompt="something else")
    handle_chat_list(_list_args(json=True, query="brown"))
    data = json.loads(capsys.readouterr().out)
    assert [r["basename"] for r in data] == ["alpha-run-260429_101500"]


def test_list_pretty_table_renders(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The pretty table delegates to load_chat_catalog and renders rows."""
    monkeypatch.setenv("COLUMNS", "200")
    entries = [
        _entry(basename="alpha-run-260429_101500", agent="alpha"),
        _entry(basename="beta-run-260429_101501", agent="beta"),
    ]
    with patch("sase.chat.cli_list.load_chat_catalog", _fake_catalog(entries)):
        handle_chat_list(_list_args(json=False))
    out = capsys.readouterr().out
    assert "Chat Transcripts (2)" in out
    assert "alpha-run-260429_101500" in out
    assert "beta-run-260429_101501" in out
    # The table trims the ISO mtime to minute precision; JSON keeps it whole.
    assert "2026-04-29 10:15" in out
    assert "10:15:08-04:00" not in out


def test_list_pretty_empty(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("sase.chat.cli_list.load_chat_catalog", _fake_catalog([])):
        handle_chat_list(_list_args(json=False))
    out = capsys.readouterr().out
    assert "Chat Transcripts (0)" in out
    assert "No chat transcripts found" in out


def test_list_pretty_renders_every_provenance_state(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Every provenance state renders its own badge without raising."""
    monkeypatch.setenv("COLUMNS", "200")
    entries = [
        _entry(
            basename=f"{provenance}-run-260429_10150{index}",
            provenance=provenance,
            source_machine="zeus" if provenance == "remote" else "athena",
        )
        for index, provenance in enumerate(CHAT_PROVENANCE_VALUES)
    ]
    with patch("sase.chat.cli_list.load_chat_catalog", _fake_catalog(entries)):
        handle_chat_list(_list_args(json=False))
    out = capsys.readouterr().out
    assert "SYNC" in out
    assert "MACHINE" in out
    for provenance in CHAT_PROVENANCE_VALUES:
        badge = chat_provenance_badge(provenance)
        assert badge.glyph in out
        if provenance != "unknown":
            assert badge.label in out
    assert "↓" in out
    assert "○" in out
    assert "⇣" not in out
    assert "◌" not in out
    assert "zeus" in out


def test_list_forwards_provenance_and_machine_filters(
    capsys: pytest.CaptureFixture[str],
) -> None:
    entries = [
        _entry(basename="local-chat", provenance="local", source_machine="athena"),
        _entry(basename="remote-chat", provenance="remote", source_machine="zeus"),
        _entry(basename="other-remote", provenance="remote", source_machine="hermes"),
    ]
    loader = _fake_catalog(entries)
    with patch("sase.chat.cli_list.load_chat_catalog", loader):
        handle_chat_list(_list_args(json=True, provenance="remote"))
    rows = json.loads(capsys.readouterr().out)
    assert [row["basename"] for row in rows] == ["remote-chat", "other-remote"]
    assert loader.calls[-1]["provenance"] == "remote"

    with patch("sase.chat.cli_list.load_chat_catalog", loader):
        handle_chat_list(_list_args(json=True, machine="ZEUS"))
    rows = json.loads(capsys.readouterr().out)
    assert [row["basename"] for row in rows] == ["remote-chat"]
    assert loader.calls[-1]["machine"] == "ZEUS"


def test_list_ignores_unrecognized_provenance_value(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A bogus provenance value degrades to "no filter" instead of raising."""
    entries = [_entry(basename="local-chat", provenance="local")]
    loader = _fake_catalog(entries)
    with patch("sase.chat.cli_list.load_chat_catalog", loader):
        handle_chat_list(_list_args(json=True, provenance="bogus"))
    rows = json.loads(capsys.readouterr().out)
    assert [row["basename"] for row in rows] == ["local-chat"]
    assert loader.calls[-1]["provenance"] is None


# ===========================================================================
# sase chat show
# ===========================================================================


def _show_args(**overrides: Any) -> argparse.Namespace:
    defaults: dict[str, Any] = {
        "agent": None,
        "path": None,
        "basename": None,
        "format": "raw",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_show_raw_prints_file_contents(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = _setup_fake_home(monkeypatch, tmp_path)
    chat = _write_chat(home, "branch-run-260429_101500")
    handle_chat_show(_show_args(path=str(chat), format="raw"))
    out = capsys.readouterr().out
    assert "# Chat History - run" in out
    assert "## Prompt" in out


def test_show_response_format(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = _setup_fake_home(monkeypatch, tmp_path)
    chat = _write_chat(
        home,
        "branch-run-260429_101500",
        prompt="ask",
        response="conclusion",
    )
    handle_chat_show(_show_args(path=str(chat), format="response"))
    out = capsys.readouterr().out
    assert "conclusion" in out
    # Raw markdown header should NOT be in response-only output.
    assert "# Chat History" not in out


def test_show_response_exits_nonzero_when_unparseable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = _setup_fake_home(monkeypatch, tmp_path)
    bad_dir = home / "chats" / "202604"
    bad_dir.mkdir(parents=True)
    bad = bad_dir / "broken-260429_101500.md"
    bad.write_text("no recognizable headings", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        handle_chat_show(_show_args(path=str(bad), format="response"))
    assert excinfo.value.code == 1
    assert "no response" in capsys.readouterr().err.lower()


def test_show_resume_format(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = _setup_fake_home(monkeypatch, tmp_path)
    chat = _write_chat(
        home,
        "branch-run-260429_101500",
        prompt="hello there",
        response="hi back",
    )
    handle_chat_show(_show_args(path=str(chat), format="resume"))
    out = capsys.readouterr().out
    # load_chat_for_resume emits **User:**/**Assistant:** flat turns.
    assert "hello there" in out
    assert "hi back" in out


def test_show_basename_resolves_via_sharded_lookup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = _setup_fake_home(monkeypatch, tmp_path)
    _write_chat(home, "branch-run-260429_101500", response="resolved")
    handle_chat_show(_show_args(basename="branch-run-260429_101500", format="response"))
    assert "resolved" in capsys.readouterr().out


def test_show_unknown_path_exits_2(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _setup_fake_home(monkeypatch, tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        handle_chat_show(_show_args(path=str(tmp_path / "missing.md")))
    assert excinfo.value.code == 2
    assert "not found" in capsys.readouterr().err.lower()


def test_show_unknown_basename_exits_2(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _setup_fake_home(monkeypatch, tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        handle_chat_show(_show_args(basename="ghost-260429_101500"))
    assert excinfo.value.code == 2
    assert "not found" in capsys.readouterr().err.lower()


def test_show_unknown_agent_exits_2(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _setup_fake_home(monkeypatch, tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        handle_chat_show(_show_args(agent="ghost"))
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "ghost" in err


def test_show_agent_via_done_response_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = _setup_fake_home(monkeypatch, tmp_path)
    chat = _write_chat(home, "branch-run-alpha-260429_101500", response="answer")
    artifact_dir = (
        home / "projects" / "sase" / "artifacts" / "ace-run" / "260429_101500"
    )
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "agent_meta.json").write_text(json.dumps({"name": "alpha"}))
    (artifact_dir / "done.json").write_text(
        json.dumps({"response_path": str(chat), "outcome": "completed"})
    )
    handle_chat_show(_show_args(agent="alpha", format="response"))
    assert "answer" in capsys.readouterr().out
