"""Tests for the 'sase chats' parser, handler, and CLI subcommands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from sase.chats.cli_list import handle_chats_list
from sase.chats.cli_show import handle_chats_show
from sase.history.chat_catalog import ChatTranscriptInfo
from sase.main.chats_handler import handle_chats_command
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


# ===========================================================================
# parser
# ===========================================================================


def test_parser_registers_chats_command() -> None:
    parser = create_parser()
    args = parser.parse_args(["chats", "list", "-j", "-l", "5"])
    assert args.command == "chats"
    assert args.chats_subcommand == "list"
    assert args.json is True
    assert args.limit == 5


def test_parser_show_requires_a_selector() -> None:
    parser = create_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["chats", "show"])


def test_parser_show_rejects_multiple_selectors() -> None:
    parser = create_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["chats", "show", "-n", "alpha", "-p", "/tmp/x.md"])


def test_parser_show_format_choices() -> None:
    parser = create_parser()
    args = parser.parse_args(["chats", "show", "-n", "alpha", "-f", "response"])
    assert args.agent == "alpha"
    assert args.format == "response"
    args = parser.parse_args(["chats", "show", "-b", "x", "-f", "resume"])
    assert args.basename == "x"
    assert args.format == "resume"
    with pytest.raises(SystemExit):
        parser.parse_args(["chats", "show", "-n", "alpha", "-f", "bogus"])


def test_parser_show_default_format_is_raw() -> None:
    parser = create_parser()
    args = parser.parse_args(["chats", "show", "-p", "/tmp/x.md"])
    assert args.format == "raw"


def test_parser_list_short_options() -> None:
    parser = create_parser()
    args = parser.parse_args(["chats", "list", "-q", "foo"])
    assert args.query == "foo"
    assert args.limit == 20  # default


# ===========================================================================
# handle_chats_command dispatch
# ===========================================================================


def test_dispatch_list(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _setup_fake_home(monkeypatch, tmp_path)
    args = argparse.Namespace(chats_subcommand="list", json=True, limit=5, query=None)
    with pytest.raises(SystemExit) as excinfo:
        handle_chats_command(args)
    assert excinfo.value.code == 0


def test_dispatch_unknown_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    args = argparse.Namespace(chats_subcommand=None)
    with pytest.raises(SystemExit) as excinfo:
        handle_chats_command(args)
    assert excinfo.value.code == 1
    assert "Usage: sase chats" in capsys.readouterr().out


# ===========================================================================
# sase chats list
# ===========================================================================


def _list_args(**overrides: Any) -> argparse.Namespace:
    defaults: dict[str, Any] = {"json": False, "limit": 20, "query": None}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_list_json_empty(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _setup_fake_home(monkeypatch, tmp_path)
    handle_chats_list(_list_args(json=True))
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
    handle_chats_list(_list_args(json=True))
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
    ]
    assert row["basename"] == "branch-run-planner-260429_101500"
    assert row["workflow"] == "run"
    assert row["agent"] == "planner"
    assert row["prompt_snippet"] == "Can you help"
    assert row["response_snippet"] == "Implemented"


def test_list_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = _setup_fake_home(monkeypatch, tmp_path)
    for i in range(5):
        _write_chat(home, f"branch-run-26042{i}_101500")
    handle_chats_list(_list_args(json=True, limit=2))
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
    handle_chats_list(_list_args(json=True, query="brown"))
    data = json.loads(capsys.readouterr().out)
    assert [r["basename"] for r in data] == ["alpha-run-260429_101500"]


def test_list_pretty_table_renders(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The pretty table delegates to list_chat_transcripts and renders rows."""
    infos = [
        _info(basename="alpha-run-260429_101500", agent="alpha"),
        _info(basename="beta-run-260429_101501", agent="beta"),
    ]
    with patch("sase.chats.cli_list.list_chat_transcripts", return_value=infos):
        handle_chats_list(_list_args(json=False))
    out = capsys.readouterr().out
    assert "Chat Transcripts (2)" in out
    assert "alpha-run-260429_101500" in out
    assert "beta-run-260429_101501" in out


def test_list_pretty_empty(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("sase.chats.cli_list.list_chat_transcripts", return_value=[]):
        handle_chats_list(_list_args(json=False))
    out = capsys.readouterr().out
    assert "Chat Transcripts (0)" in out
    assert "No chat transcripts found" in out


# ===========================================================================
# sase chats show
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
    handle_chats_show(_show_args(path=str(chat), format="raw"))
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
    handle_chats_show(_show_args(path=str(chat), format="response"))
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
        handle_chats_show(_show_args(path=str(bad), format="response"))
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
    handle_chats_show(_show_args(path=str(chat), format="resume"))
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
    handle_chats_show(
        _show_args(basename="branch-run-260429_101500", format="response")
    )
    assert "resolved" in capsys.readouterr().out


def test_show_unknown_path_exits_2(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _setup_fake_home(monkeypatch, tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        handle_chats_show(_show_args(path=str(tmp_path / "missing.md")))
    assert excinfo.value.code == 2
    assert "not found" in capsys.readouterr().err.lower()


def test_show_unknown_basename_exits_2(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _setup_fake_home(monkeypatch, tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        handle_chats_show(_show_args(basename="ghost-260429_101500"))
    assert excinfo.value.code == 2
    assert "not found" in capsys.readouterr().err.lower()


def test_show_unknown_agent_exits_2(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _setup_fake_home(monkeypatch, tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        handle_chats_show(_show_args(agent="ghost"))
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
    handle_chats_show(_show_args(agent="alpha", format="response"))
    assert "answer" in capsys.readouterr().out
