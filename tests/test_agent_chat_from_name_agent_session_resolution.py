"""Agent-session name and source-resolution tests.

Split from ``tests.test_agent_chat_from_name_agent_session``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._agent_chat_from_name_session_helpers import (
    resolve_agent_chat_path,
    resolve_agent_chat_sources,
)
from tests._agent_chat_from_name_helpers import write_agent
from tests._dismissed_completion_helpers import (
    add_archive_identity,
    rebuild_completion_archive,
    write_dismissed_completion,
)

__all__ = [
    "test_agent_session_name_and_explicit_children_use_member_owned_transcripts",
    "test_explicit_target_is_honored_without_a_bound_launch_record",
    "test_agent_session_source_reads_dismissed_member_transcript_from_bundle",
    "test_agent_session_source_includes_completed_members_in_chain_order",
    "test_dotted_numeric_agent_session_root_resolves_as_agent_session_not_legacy_child",
    "test_agent_session_and_explicit_member_duplicate_transcript_are_coalesced",
    "test_agent_then_overlapping_agent_session_keeps_unique_later_member",
    "test_legacy_rootless_agent_session_source_includes_all_completed_members",
]


def test_agent_session_name_and_explicit_children_use_member_owned_transcripts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    planner_chat = tmp_path / "planner.md"
    coder_chat = tmp_path / "coder.md"
    write_agent(
        tmp_path,
        "20260718010101",
        "cx--plan",
        done={"response_path": str(coder_chat), "outcome": "completed"},
        meta={
            "workflow_name": "cx",
            "agent_session": "cx",
            "agent_session_role": "root",
            "role_suffix": "--plan",
            "chat_path": str(planner_chat),
        },
    )
    write_agent(
        tmp_path,
        "20260718010202",
        "cx--code",
        done={"response_path": str(coder_chat), "outcome": "completed"},
        meta={
            "workflow_name": "cx",
            "agent_session": "cx",
            "agent_session_role": "code",
            "role_suffix": "--code",
            "parent_timestamp": "20260718010101",
        },
    )

    assert resolve_agent_chat_path("cx") == str(coder_chat)
    assert resolve_agent_chat_path("cx--plan") == str(planner_chat)
    assert resolve_agent_chat_path("cx--code") == str(coder_chat)


def test_explicit_target_is_honored_without_a_bound_launch_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    planner_chat = tmp_path / "planner.md"
    coder_chat = tmp_path / "coder.md"
    write_agent(
        tmp_path,
        "20260718010101",
        "cx--plan",
        done={"response_path": str(planner_chat), "outcome": "completed"},
        meta={"workflow_name": "cx", "agent_session": "cx"},
    )
    write_agent(
        tmp_path,
        "20260718010202",
        "cx--code",
        done={"response_path": str(coder_chat), "outcome": "completed"},
        meta={
            "workflow_name": "cx",
            "agent_session": "cx",
            "parent_timestamp": "20260718010101",
        },
    )

    turn_source = resolve_agent_chat_sources(["cx--plan"], target="turn")[0]
    session_source = resolve_agent_chat_sources(["cx--plan"], target="session")[0]

    assert turn_source.kind == "agent"
    assert turn_source.path == str(planner_chat)
    assert session_source.kind == "session"
    assert [member.name for member in session_source.members] == [
        "cx--plan",
        "cx--code",
    ]


def test_agent_session_source_reads_dismissed_member_transcript_from_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    planner_chat = tmp_path / "planner.md"
    coder_chat = tmp_path / "coder.md"
    write_agent(
        tmp_path,
        "20260720190100",
        "cx--plan",
        done={"response_path": str(planner_chat), "outcome": "completed"},
        meta={"agent_session": "cx"},
    )
    coder_dir = write_agent(
        tmp_path,
        "20260720190200",
        "cx--code",
        done={"response_path": str(coder_chat), "outcome": "completed"},
        meta={
            "agent_session": "cx",
            "parent_timestamp": "20260720190100",
            "changespec_name": "change",
        },
    )
    add_archive_identity(coder_dir)
    write_dismissed_completion(
        tmp_path,
        coder_dir,
        "cx--code",
        response_path=str(coder_chat),
    )
    (coder_dir / "done.json").unlink()
    rebuild_completion_archive()

    source = resolve_agent_chat_sources(["cx"])[0]

    assert [(member.name, member.path) for member in source.members] == [
        ("cx--plan", str(planner_chat)),
        ("cx--code", str(coder_chat)),
    ]
    assert source.excluded == ()


def test_agent_session_source_includes_completed_members_in_chain_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    planner_chat = tmp_path / "planner.md"
    coder_chat = tmp_path / "coder.md"
    planner_dir = write_agent(
        tmp_path,
        "20260718010101",
        "cx--plan",
        done={"response_path": str(coder_chat), "outcome": "completed"},
        meta={"agent_session": "cx", "chat_path": str(planner_chat)},
    )
    coder_dir = write_agent(
        tmp_path,
        "20260718010202",
        "cx--code",
        done={"response_path": str(coder_chat), "outcome": "completed"},
        meta={"agent_session": "cx", "parent_timestamp": "20260718010101"},
    )

    source = resolve_agent_chat_sources(["cx"])[0]
    explicit_member = resolve_agent_chat_sources(["cx--plan"])[0]

    assert source.kind == "session"
    assert source.name == "cx"
    assert source.path == str(coder_chat)
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
            },
            {
                "kind": "agent",
                "name": "cx--code",
                "path": str(coder_chat),
                "artifact_dir": str(coder_dir),
                "outcome": "completed",
            },
        ],
        "excluded": [],
    }
    assert explicit_member.kind == "agent"
    assert explicit_member.path == str(planner_chat)


def test_dotted_numeric_agent_session_root_resolves_as_agent_session_not_legacy_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    base_name = "sase-x7.3.1.5"
    planner_chat = tmp_path / "planner.md"
    coder_chat = tmp_path / "coder.md"
    write_agent(
        tmp_path,
        "20260718010101",
        f"{base_name}--plan",
        done={"response_path": str(planner_chat), "outcome": "completed"},
        meta={"workflow_name": base_name, "agent_session": base_name},
    )
    write_agent(
        tmp_path,
        "20260718010202",
        f"{base_name}--code",
        done={"response_path": str(coder_chat), "outcome": "completed"},
        meta={"agent_session": base_name, "parent_timestamp": "20260718010101"},
    )

    source = resolve_agent_chat_sources([base_name])[0]

    assert resolve_agent_chat_path(base_name) == str(coder_chat)
    assert source.kind == "session"
    assert source.name == base_name
    assert [member.name for member in source.members] == [
        f"{base_name}--plan",
        f"{base_name}--code",
    ]


def test_agent_session_and_explicit_member_duplicate_transcript_are_coalesced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    planner_chat = tmp_path / "planner.md"
    coder_chat = tmp_path / "coder.md"
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
        done={"response_path": str(coder_chat), "outcome": "completed"},
        meta={"agent_session": "cx", "parent_timestamp": "20260718010101"},
    )

    sources = resolve_agent_chat_sources(["cx", "cx--code"])

    assert [source.name for source in sources] == ["cx"]
    assert [member.name for member in sources[0].members] == [
        "cx--plan",
        "cx--code",
    ]


def test_agent_then_overlapping_agent_session_keeps_unique_later_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    planner_chat = tmp_path / "planner.md"
    coder_chat = tmp_path / "coder.md"
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
        done={"response_path": str(coder_chat), "outcome": "completed"},
        meta={"agent_session": "cx", "parent_timestamp": "20260718010101"},
    )

    sources = resolve_agent_chat_sources(["cx--code", "cx"])

    assert [(source.kind, source.name) for source in sources] == [
        ("agent", "cx--code"),
        ("session", "cx"),
    ]
    assert [member.name for member in sources[1].members] == ["cx--plan"]
    assert sources[1].path == str(planner_chat)


def test_legacy_rootless_agent_session_source_includes_all_completed_members(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    planner_chat = tmp_path / "planner.md"
    coder_chat = tmp_path / "coder.md"
    # legacy agent-family spelling: pre-rename agent_meta.json files carry
    # ``agent_family`` instead of ``agent_session``.
    write_agent(
        tmp_path,
        "20260718010101",
        "cx--plan",
        done={"response_path": str(planner_chat), "outcome": "completed"},
        meta={"agent_family": "cx", "parent_timestamp": "missing-root"},
    )
    write_agent(
        tmp_path,
        "20260718010202",
        "cx--code",
        done={"response_path": str(coder_chat), "outcome": "completed"},
        meta={"agent_family": "cx", "parent_timestamp": "20260718010101"},
    )

    source = resolve_agent_chat_sources(["cx"])[0]

    assert source.kind == "session"
    assert [member.name for member in source.members] == ["cx--plan", "cx--code"]
    assert source.path == str(coder_chat)
