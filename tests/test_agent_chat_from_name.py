"""Tests for named-agent chat resolution."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sase.scripts.agent_chat_from_name import (
    _resolve_agent_chat_path,
    _resolve_agent_chat_sources,
    main,
)
from tests._agent_chat_from_name_helpers import write_agent


def test_explicit_completed_agent_uses_done_response_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    chat = tmp_path / "done-chat.md"
    fallback = tmp_path / "meta-chat.md"
    write_agent(
        tmp_path,
        "20260504010101",
        "alpha",
        done={"response_path": str(chat), "outcome": "completed"},
        meta={"chat_path": str(fallback)},
    )

    assert _resolve_agent_chat_path("alpha") == str(chat)


def test_agent_name_template_resolves_latest_completed_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    older_chat = tmp_path / "older-chat.md"
    newer_chat = tmp_path / "newer-chat.md"
    write_agent(
        tmp_path,
        "20260504010101",
        "build-1",
        done={"response_path": str(older_chat), "outcome": "completed"},
    )
    write_agent(
        tmp_path,
        "20260504020202",
        "build-3",
        done={"response_path": str(newer_chat), "outcome": "completed"},
    )

    assert _resolve_agent_chat_path("build-@") == str(newer_chat)


def test_agent_name_template_suffix_shape_resolves_latest_completed_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    older_chat = tmp_path / "older-chat.md"
    newer_chat = tmp_path / "newer-chat.md"
    write_agent(
        tmp_path,
        "20260504010101",
        "cld.0",
        done={"response_path": str(older_chat), "outcome": "completed"},
    )
    write_agent(
        tmp_path,
        "20260504020202",
        "cld.1",
        done={"response_path": str(newer_chat), "outcome": "completed"},
    )

    assert _resolve_agent_chat_path("cld.@") == str(newer_chat)


def test_agent_name_template_excludes_current_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    previous_chat = tmp_path / "previous-chat.md"
    write_agent(
        tmp_path,
        "20260504010101",
        "build-1",
        done={"response_path": str(previous_chat), "outcome": "completed"},
    )
    current_dir = write_agent(
        tmp_path,
        "20260504020202",
        "build-2",
        meta={"chat_path": str(tmp_path / "current-chat.md"), "pid": os.getpid()},
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(current_dir))

    assert _resolve_agent_chat_path("build-@") == str(previous_chat)


def test_explicit_running_agent_falls_back_to_meta_chat_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    chat = tmp_path / "running-chat.md"
    write_agent(
        tmp_path,
        "20260504010101",
        "bravo",
        meta={"chat_path": str(chat), "pid": os.getpid()},
    )

    assert _resolve_agent_chat_path("bravo") == str(chat)


def test_missing_chat_history_fails_clearly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    write_agent(
        tmp_path,
        "20260504010101",
        "charlie",
        done={"outcome": "completed"},
    )

    with pytest.raises(
        RuntimeError, match="No agent with chat history found for: charlie"
    ):
        _resolve_agent_chat_path("charlie")


def test_malformed_metadata_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    write_agent(tmp_path, "20260504010101", "bad", malformed_meta=True)

    with pytest.raises(RuntimeError, match="No agent with chat history found for: bad"):
        _resolve_agent_chat_path("bad")


def test_omitted_name_uses_most_recent_named_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    older_chat = tmp_path / "older.md"
    newer_chat = tmp_path / "newer.md"
    write_agent(
        tmp_path,
        "20260504010101",
        "older",
        done={"response_path": str(older_chat), "outcome": "completed"},
    )
    write_agent(
        tmp_path,
        "20260504020202",
        "newer",
        done={"response_path": str(newer_chat), "outcome": "completed"},
    )

    assert _resolve_agent_chat_path(None) == str(newer_chat)
    assert _resolve_agent_chat_path("") == str(newer_chat)


def test_omitted_name_excludes_current_artifacts_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    older_chat = tmp_path / "older.md"
    write_agent(
        tmp_path,
        "20260504010101",
        "older",
        done={"response_path": str(older_chat), "outcome": "completed"},
    )
    current_dir = write_agent(
        tmp_path,
        "20260504020202",
        "current",
        done={"response_path": str(tmp_path / "current.md"), "outcome": "completed"},
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(current_dir))

    assert _resolve_agent_chat_path(None) == str(older_chat)


def test_omitted_name_fails_when_no_previous_named_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    with pytest.raises(RuntimeError, match="No previous named agent found"):
        _resolve_agent_chat_path(None)


def test_main_emits_parseable_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    chat = tmp_path / "chat.md"
    write_agent(
        tmp_path,
        "20260504010101",
        "delta",
        done={"response_path": str(chat), "outcome": "completed"},
    )

    assert main(["delta"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["path"] == str(chat)
    assert json.loads(output["sources_json"]) == [
        {"kind": "agent", "name": "delta", "path": str(chat)}
    ]


def test_multiple_agents_resolve_in_invocation_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    planner_chat = tmp_path / "planner.md"
    coder_chat = tmp_path / "coder.md"
    write_agent(
        tmp_path,
        "20260504010101",
        "planner",
        done={"response_path": str(planner_chat), "outcome": "completed"},
    )
    write_agent(
        tmp_path,
        "20260504020202",
        "coder",
        done={"response_path": str(coder_chat), "outcome": "completed"},
    )

    sources = _resolve_agent_chat_sources(["coder", "planner"])

    assert [(source.name, source.path) for source in sources] == [
        ("coder", str(coder_chat)),
        ("planner", str(planner_chat)),
    ]


def test_multiple_agents_report_all_invalid_parents_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    valid_chat = tmp_path / "valid.md"
    write_agent(
        tmp_path,
        "20260504010101",
        "valid",
        done={"response_path": str(valid_chat), "outcome": "completed"},
    )

    with pytest.raises(RuntimeError) as exc_info:
        _resolve_agent_chat_sources(["missing-one", "valid", "missing-two"])

    message = str(exc_info.value)
    assert "missing-one" in message
    assert "missing-two" in message


def test_multiple_aliases_to_same_transcript_are_coalesced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    shared_chat = tmp_path / "shared.md"
    for index, name in enumerate(("planner", "planner-alias"), start=1):
        write_agent(
            tmp_path,
            f"2026050401010{index}",
            name,
            done={"response_path": str(shared_chat), "outcome": "completed"},
        )

    sources = _resolve_agent_chat_sources(["planner", "planner-alias"])

    assert [(source.name, source.path) for source in sources] == [
        ("planner", str(shared_chat))
    ]


def test_repeated_textual_parent_is_rejected_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    chat = tmp_path / "planner.md"
    write_agent(
        tmp_path,
        "20260504010101",
        "planner",
        done={"response_path": str(chat), "outcome": "completed"},
    )

    with pytest.raises(RuntimeError) as exc_info:
        _resolve_agent_chat_sources(["planner", "planner", "missing"])

    message = str(exc_info.value)
    assert "repeated parent argument 'planner'" in message
    assert "already requested as parent 1" in message
    assert "missing" in message


def test_unreadable_transcript_is_rejected_before_loading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    missing_chat = tmp_path / "missing.md"
    write_agent(
        tmp_path,
        "20260504010101",
        "planner",
        done={"response_path": str(missing_chat), "outcome": "completed"},
    )
    missing_chat.unlink()

    with pytest.raises(RuntimeError, match="not readable"):
        _resolve_agent_chat_sources(["planner"])
