"""Tests for the ``agent_chat_from_name`` resume resolver."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sase.scripts.agent_chat_from_name import main, resolve_agent_chat_path


def _write_agent(
    home: Path,
    suffix: str,
    name: str,
    *,
    done: dict[str, object] | None = None,
    meta: dict[str, object] | None = None,
    malformed_meta: bool = False,
) -> Path:
    artifacts_dir = (
        home / ".sase" / "projects" / "proj" / "artifacts" / "ace-run" / suffix
    )
    artifacts_dir.mkdir(parents=True)
    if malformed_meta:
        (artifacts_dir / "agent_meta.json").write_text("{", encoding="utf-8")
    else:
        meta_data: dict[str, object] = {"name": name}
        if meta:
            meta_data.update(meta)
        (artifacts_dir / "agent_meta.json").write_text(
            json.dumps(meta_data), encoding="utf-8"
        )
    if done is not None:
        (artifacts_dir / "done.json").write_text(json.dumps(done), encoding="utf-8")
    return artifacts_dir


def test_explicit_completed_agent_uses_done_response_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    chat = tmp_path / "done-chat.md"
    fallback = tmp_path / "meta-chat.md"
    _write_agent(
        tmp_path,
        "20260504010101",
        "alpha",
        done={"response_path": str(chat), "outcome": "completed"},
        meta={"chat_path": str(fallback)},
    )

    assert resolve_agent_chat_path("alpha") == str(chat)


def test_explicit_running_agent_falls_back_to_meta_chat_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    chat = tmp_path / "running-chat.md"
    _write_agent(
        tmp_path,
        "20260504010101",
        "bravo",
        meta={"chat_path": str(chat), "pid": os.getpid()},
    )

    assert resolve_agent_chat_path("bravo") == str(chat)


def test_missing_chat_history_fails_clearly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    _write_agent(
        tmp_path,
        "20260504010101",
        "charlie",
        done={"outcome": "completed"},
    )

    with pytest.raises(
        RuntimeError, match="No agent with chat history found for: charlie"
    ):
        resolve_agent_chat_path("charlie")


def test_malformed_metadata_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    _write_agent(tmp_path, "20260504010101", "bad", malformed_meta=True)

    with pytest.raises(RuntimeError, match="No agent with chat history found for: bad"):
        resolve_agent_chat_path("bad")


def test_omitted_name_uses_most_recent_named_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    older_chat = tmp_path / "older.md"
    newer_chat = tmp_path / "newer.md"
    _write_agent(
        tmp_path,
        "20260504010101",
        "older",
        done={"response_path": str(older_chat), "outcome": "completed"},
    )
    _write_agent(
        tmp_path,
        "20260504020202",
        "newer",
        done={"response_path": str(newer_chat), "outcome": "completed"},
    )

    assert resolve_agent_chat_path(None) == str(newer_chat)
    assert resolve_agent_chat_path("") == str(newer_chat)


def test_omitted_name_excludes_current_artifacts_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    older_chat = tmp_path / "older.md"
    _write_agent(
        tmp_path,
        "20260504010101",
        "older",
        done={"response_path": str(older_chat), "outcome": "completed"},
    )
    current_dir = _write_agent(
        tmp_path,
        "20260504020202",
        "current",
        done={"response_path": str(tmp_path / "current.md"), "outcome": "completed"},
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(current_dir))

    assert resolve_agent_chat_path(None) == str(older_chat)


def test_omitted_name_fails_when_no_previous_named_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    with pytest.raises(RuntimeError, match="No previous named agent found"):
        resolve_agent_chat_path(None)


def test_main_emits_parseable_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    chat = tmp_path / "chat.md"
    _write_agent(
        tmp_path,
        "20260504010101",
        "delta",
        done={"response_path": str(chat), "outcome": "completed"},
    )

    assert main(["delta"]) == 0
    assert json.loads(capsys.readouterr().out) == {"path": str(chat)}
