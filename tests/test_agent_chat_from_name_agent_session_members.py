"""Agent-session member selection and exclusion tests.

Split from ``tests.test_agent_chat_from_name_agent_session``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.history.chat import build_fork_injected_history
from tests._agent_chat_from_name_session_helpers import (
    resolve_agent_chat_path,
    resolve_agent_chat_sources,
)
from tests._agent_chat_from_name_helpers import write_agent

__all__ = [
    "test_agent_session_source_includes_intermediate_handoff_without_done_marker",
    "test_agent_session_source_reports_running_tip_as_excluded",
    "test_agent_session_source_omits_current_member_from_own_agent_session_history",
    "test_agent_session_source_includes_failed_member_excludes_unavailable_transcripts",
    "test_agent_session_source_requires_at_least_one_completed_transcript",
]


def test_agent_session_source_includes_intermediate_handoff_without_done_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    planner_chat = tmp_path / "planner.md"
    coder_chat = tmp_path / "coder.md"
    write_agent(
        tmp_path,
        "20260718010101",
        "cx--plan",
        meta={"agent_session": "cx", "chat_path": str(planner_chat)},
    )
    write_agent(
        tmp_path,
        "20260718010202",
        "cx--code",
        done={"response_path": str(coder_chat), "outcome": "completed"},
        meta={"agent_session": "cx", "parent_timestamp": "20260718010101"},
    )

    source = resolve_agent_chat_sources(["cx"])[0]

    assert [member.name for member in source.members] == ["cx--plan", "cx--code"]
    assert [member.path for member in source.members] == [
        str(planner_chat),
        str(coder_chat),
    ]
    assert [member.outcome for member in source.members] == [
        "completed",
        "completed",
    ]
    assert source.excluded == ()


def test_agent_session_source_reports_running_tip_as_excluded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    planner_chat = tmp_path / "planner.md"
    write_agent(
        tmp_path,
        "20260718010101",
        "cx--plan",
        done={"response_path": str(planner_chat), "outcome": "completed"},
        meta={"agent_session": "cx"},
    )
    write_agent(
        tmp_path,
        "20260718010202",
        "cx--code",
        meta={"agent_session": "cx", "parent_timestamp": "20260718010101"},
    )

    source = resolve_agent_chat_sources(["cx"])[0]

    assert [member.name for member in source.members] == ["cx--plan"]
    assert [(member.name, member.status) for member in source.excluded] == [
        ("cx--code", "running")
    ]
    assert source.path == str(planner_chat)
    rendered = build_fork_injected_history([source.to_json_data()])
    assert "**Members shown:** 1 of 2 (sequential chain, oldest first)" in rendered
    assert "**Not shown:** `cx--code` (running)" in rendered


def test_agent_session_source_omits_current_member_from_own_agent_session_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    planner_chat = tmp_path / "planner.md"
    planner_dir = write_agent(
        tmp_path,
        "20260718010101",
        "cx--plan",
        done={"response_path": str(planner_chat), "outcome": "completed"},
        meta={"agent_session": "cx"},
    )
    current_dir = write_agent(
        tmp_path,
        "20260718010202",
        "cx--code",
        meta={"agent_session": "cx", "parent_timestamp": "20260718010101"},
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(current_dir))

    source = resolve_agent_chat_sources(["cx"])[0]

    assert source.to_json_data() == {
        "kind": "session",
        "name": "cx",
        "members": [
            {
                "kind": "agent",
                "name": "cx--plan",
                "path": str(planner_chat),
                "artifact_dir": str(planner_dir),
                "outcome": "completed",
            }
        ],
        "excluded": [],
    }
    rendered = build_fork_injected_history([source.to_json_data()])
    assert "**Members shown:** 1 of 1 (sequential chain, oldest first)" in rendered
    assert "Not shown:" not in rendered
    assert "`cx--code`" not in rendered


def test_agent_session_source_includes_failed_member_excludes_unavailable_transcripts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A terminal failed member is included with failure context, not dropped.

    Only a still-missing or unreadable transcript is excluded from the roster.
    """
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    planner_chat = tmp_path / "planner.md"
    unreadable_chat = tmp_path / "unreadable.md"
    write_agent(
        tmp_path,
        "20260718010101",
        "cx--plan",
        done={"response_path": str(planner_chat), "outcome": "completed"},
        meta={"agent_session": "cx"},
    )
    write_agent(
        tmp_path,
        "20260718010202",
        "cx--code",
        done={"outcome": "completed"},
        meta={"agent_session": "cx", "parent_timestamp": "20260718010101"},
    )
    write_agent(
        tmp_path,
        "20260718010303",
        "cx--test",
        done={"outcome": "failed", "error": "assertion failed"},
        meta={"agent_session": "cx", "parent_timestamp": "20260718010202"},
    )
    write_agent(
        tmp_path,
        "20260718010404",
        "cx--fix",
        done={"response_path": str(unreadable_chat), "outcome": "completed"},
        meta={"agent_session": "cx", "parent_timestamp": "20260718010303"},
    )
    unreadable_chat.unlink()

    source = resolve_agent_chat_sources(["cx"])[0]

    assert [member.name for member in source.members] == ["cx--plan", "cx--test"]
    session_data = source.to_json_data()
    member_data = session_data["members"]
    assert isinstance(member_data, list)
    failed_member = member_data[1]
    assert isinstance(failed_member, dict)
    assert failed_member["kind"] == "agent"
    assert failed_member["outcome"] == "failed"
    failure = failed_member["failure"]
    assert isinstance(failure, dict)
    assert failure["error"] == "assertion failed"
    assert [(member.name, member.status) for member in source.excluded] == [
        ("cx--code", "missing transcript"),
        ("cx--fix", "unreadable transcript"),
    ]


def test_agent_session_source_requires_at_least_one_completed_transcript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    write_agent(
        tmp_path,
        "20260718010101",
        "cx--plan",
        meta={"agent_session": "cx"},
    )

    with pytest.raises(RuntimeError, match="No agent with chat history found for: cx"):
        resolve_agent_chat_sources(["cx"])
