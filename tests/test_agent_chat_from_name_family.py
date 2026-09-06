"""Tests for agent-family chat resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.history.chat import build_fork_injected_history
from sase.scripts.agent_chat_from_name import (
    _ForkFamilyMemberSource,
    _resolve_agent_chat_path,
    _resolve_agent_chat_sources,
)
from tests._agent_chat_from_name_helpers import write_agent
from tests._dismissed_completion_helpers import (
    add_archive_identity,
    rebuild_completion_archive,
    write_dismissed_completion,
)


def test_family_name_and_explicit_children_use_member_owned_transcripts(
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
            "agent_family": "cx",
            "agent_family_role": "root",
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
            "agent_family": "cx",
            "agent_family_role": "code",
            "role_suffix": "--code",
            "parent_timestamp": "20260718010101",
        },
    )

    assert _resolve_agent_chat_path("cx") == str(coder_chat)
    assert _resolve_agent_chat_path("cx--plan") == str(planner_chat)
    assert _resolve_agent_chat_path("cx--code") == str(coder_chat)


def test_family_source_reads_dismissed_member_transcript_from_bundle(
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
        meta={"agent_family": "cx"},
    )
    coder_dir = write_agent(
        tmp_path,
        "20260720190200",
        "cx--code",
        done={"response_path": str(coder_chat), "outcome": "completed"},
        meta={
            "agent_family": "cx",
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

    source = _resolve_agent_chat_sources(["cx"])[0]

    assert [(member.name, member.path) for member in source.members] == [
        ("cx--plan", str(planner_chat)),
        ("cx--code", str(coder_chat)),
    ]
    assert source.excluded == ()


def test_family_source_includes_completed_members_in_chain_order(
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
        meta={"agent_family": "cx", "chat_path": str(planner_chat)},
    )
    coder_dir = write_agent(
        tmp_path,
        "20260718010202",
        "cx--code",
        done={"response_path": str(coder_chat), "outcome": "completed"},
        meta={"agent_family": "cx", "parent_timestamp": "20260718010101"},
    )

    source = _resolve_agent_chat_sources(["cx"])[0]
    explicit_member = _resolve_agent_chat_sources(["cx--plan"])[0]

    assert source.kind == "family"
    assert source.name == "cx"
    assert source.path == str(coder_chat)
    assert source.to_json_data() == {
        "kind": "family",
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


def test_dotted_numeric_family_root_resolves_as_family_not_legacy_child(
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
        meta={"workflow_name": base_name, "agent_family": base_name},
    )
    write_agent(
        tmp_path,
        "20260718010202",
        f"{base_name}--code",
        done={"response_path": str(coder_chat), "outcome": "completed"},
        meta={"agent_family": base_name, "parent_timestamp": "20260718010101"},
    )

    source = _resolve_agent_chat_sources([base_name])[0]

    assert _resolve_agent_chat_path(base_name) == str(coder_chat)
    assert source.kind == "family"
    assert source.name == base_name
    assert [member.name for member in source.members] == [
        f"{base_name}--plan",
        f"{base_name}--code",
    ]


def test_family_source_includes_intermediate_handoff_without_done_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    planner_chat = tmp_path / "planner.md"
    coder_chat = tmp_path / "coder.md"
    write_agent(
        tmp_path,
        "20260718010101",
        "cx--plan",
        meta={"agent_family": "cx", "chat_path": str(planner_chat)},
    )
    write_agent(
        tmp_path,
        "20260718010202",
        "cx--code",
        done={"response_path": str(coder_chat), "outcome": "completed"},
        meta={"agent_family": "cx", "parent_timestamp": "20260718010101"},
    )

    source = _resolve_agent_chat_sources(["cx"])[0]

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


def test_family_source_reports_running_tip_as_excluded(
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
        meta={"agent_family": "cx"},
    )
    write_agent(
        tmp_path,
        "20260718010202",
        "cx--code",
        meta={"agent_family": "cx", "parent_timestamp": "20260718010101"},
    )

    source = _resolve_agent_chat_sources(["cx"])[0]

    assert [member.name for member in source.members] == ["cx--plan"]
    assert [(member.name, member.status) for member in source.excluded] == [
        ("cx--code", "running")
    ]
    assert source.path == str(planner_chat)
    rendered = build_fork_injected_history([source.to_json_data()])
    assert "**Members shown:** 1 of 2 (sequential chain, oldest first)" in rendered
    assert "**Not shown:** `cx--code` (running)" in rendered


def test_family_source_omits_current_member_from_own_family_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    planner_chat = tmp_path / "planner.md"
    planner_dir = write_agent(
        tmp_path,
        "20260718010101",
        "cx--plan",
        done={"response_path": str(planner_chat), "outcome": "completed"},
        meta={"agent_family": "cx"},
    )
    current_dir = write_agent(
        tmp_path,
        "20260718010202",
        "cx--code",
        meta={"agent_family": "cx", "parent_timestamp": "20260718010101"},
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(current_dir))

    source = _resolve_agent_chat_sources(["cx"])[0]

    assert source.to_json_data() == {
        "kind": "family",
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


def test_family_source_includes_failed_member_excludes_unavailable_transcripts(
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
        meta={"agent_family": "cx"},
    )
    write_agent(
        tmp_path,
        "20260718010202",
        "cx--code",
        done={"outcome": "completed"},
        meta={"agent_family": "cx", "parent_timestamp": "20260718010101"},
    )
    write_agent(
        tmp_path,
        "20260718010303",
        "cx--test",
        done={"outcome": "failed", "error": "assertion failed"},
        meta={"agent_family": "cx", "parent_timestamp": "20260718010202"},
    )
    write_agent(
        tmp_path,
        "20260718010404",
        "cx--fix",
        done={"response_path": str(unreadable_chat), "outcome": "completed"},
        meta={"agent_family": "cx", "parent_timestamp": "20260718010303"},
    )
    unreadable_chat.unlink()

    source = _resolve_agent_chat_sources(["cx"])[0]

    assert [member.name for member in source.members] == ["cx--plan", "cx--test"]
    failed_member = source.members[1]
    assert isinstance(failed_member, _ForkFamilyMemberSource)
    assert failed_member.kind == "agent"
    assert failed_member.outcome == "failed"
    assert failed_member.failure is not None
    assert failed_member.failure.error == "assertion failed"
    assert [(member.name, member.status) for member in source.excluded] == [
        ("cx--code", "missing transcript"),
        ("cx--fix", "unreadable transcript"),
    ]


def test_family_source_requires_at_least_one_completed_transcript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    write_agent(
        tmp_path,
        "20260718010101",
        "cx--plan",
        meta={"agent_family": "cx"},
    )

    with pytest.raises(RuntimeError, match="No agent with chat history found for: cx"):
        _resolve_agent_chat_sources(["cx"])


def test_family_and_explicit_member_duplicate_transcript_are_coalesced(
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
        meta={"agent_family": "cx"},
    )
    write_agent(
        tmp_path,
        "20260718010202",
        "cx--code",
        done={"response_path": str(coder_chat), "outcome": "completed"},
        meta={"agent_family": "cx", "parent_timestamp": "20260718010101"},
    )

    sources = _resolve_agent_chat_sources(["cx", "cx--code"])

    assert [source.name for source in sources] == ["cx"]
    assert [member.name for member in sources[0].members] == [
        "cx--plan",
        "cx--code",
    ]


def test_agent_then_overlapping_family_keeps_unique_later_member(
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
        meta={"agent_family": "cx"},
    )
    write_agent(
        tmp_path,
        "20260718010202",
        "cx--code",
        done={"response_path": str(coder_chat), "outcome": "completed"},
        meta={"agent_family": "cx", "parent_timestamp": "20260718010101"},
    )

    sources = _resolve_agent_chat_sources(["cx--code", "cx"])

    assert [(source.kind, source.name) for source in sources] == [
        ("agent", "cx--code"),
        ("family", "cx"),
    ]
    assert [member.name for member in sources[1].members] == ["cx--plan"]
    assert sources[1].path == str(planner_chat)


def test_legacy_rootless_family_source_includes_all_completed_members(
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
        meta={"agent_family": "cx", "parent_timestamp": "missing-root"},
    )
    write_agent(
        tmp_path,
        "20260718010202",
        "cx--code",
        done={"response_path": str(coder_chat), "outcome": "completed"},
        meta={"agent_family": "cx", "parent_timestamp": "20260718010101"},
    )

    source = _resolve_agent_chat_sources(["cx"])[0]

    assert source.kind == "family"
    assert [member.name for member in source.members] == ["cx--plan", "cx--code"]
    assert source.path == str(coder_chat)
