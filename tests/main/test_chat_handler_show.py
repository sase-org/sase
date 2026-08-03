"""Tests for the ``sase chat show`` command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from sase.chat.cli_show import handle_chat_show

from tests.main.chat_handler_helpers import (
    setup_fake_home,
    write_chat,
)


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
    home = setup_fake_home(monkeypatch, tmp_path)
    chat = write_chat(home, "branch-run-260429_101500")
    handle_chat_show(_show_args(path=str(chat), format="raw"))
    out = capsys.readouterr().out
    assert "# Chat History - run" in out
    assert "## Prompt" in out


def test_show_response_format(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = setup_fake_home(monkeypatch, tmp_path)
    chat = write_chat(
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
    home = setup_fake_home(monkeypatch, tmp_path)
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
    home = setup_fake_home(monkeypatch, tmp_path)
    chat = write_chat(
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
    home = setup_fake_home(monkeypatch, tmp_path)
    write_chat(home, "branch-run-260429_101500", response="resolved")
    handle_chat_show(_show_args(basename="branch-run-260429_101500", format="response"))
    assert "resolved" in capsys.readouterr().out


def test_show_unknown_path_exits_2(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    setup_fake_home(monkeypatch, tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        handle_chat_show(_show_args(path=str(tmp_path / "missing.md")))
    assert excinfo.value.code == 2
    assert "not found" in capsys.readouterr().err.lower()


def test_show_unknown_basename_exits_2(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    setup_fake_home(monkeypatch, tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        handle_chat_show(_show_args(basename="ghost-260429_101500"))
    assert excinfo.value.code == 2
    assert "not found" in capsys.readouterr().err.lower()


def test_show_unknown_agent_exits_2(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    setup_fake_home(monkeypatch, tmp_path)
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
    home = setup_fake_home(monkeypatch, tmp_path)
    chat = write_chat(home, "branch-run-alpha-260429_101500", response="answer")
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
