"""Fork-history binding tests for agent sessions.

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
    "test_bound_session_fork_history_selects_the_recorded_root_generation",
    "test_bound_turn_fork_history_omits_members_after_pinned_turn",
    "test_legacy_bound_bare_agent_record_heals_to_promoted_session",
    "test_bound_exact_member_fork_history_uses_the_recorded_artifact",
]


def test_bound_session_fork_history_selects_the_recorded_root_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    old_plan_chat = tmp_path / "old-plan.md"
    old_code_chat = tmp_path / "old-code.md"
    new_plan_chat = tmp_path / "new-plan.md"
    old_root = write_agent(
        tmp_path,
        "20261030010101",
        "cx--plan",
        done={"response_path": str(old_plan_chat), "outcome": "completed"},
        meta={"agent_session": "cx"},
    )
    write_agent(
        tmp_path,
        "20261030010202",
        "cx--code",
        done={"response_path": str(old_code_chat), "outcome": "completed"},
        meta={"agent_session": "cx", "parent_timestamp": "20261030010101"},
    )
    write_agent(
        tmp_path,
        "20261030010303",
        "cx--plan",
        done={"response_path": str(new_plan_chat), "outcome": "completed"},
        meta={"agent_session": "cx"},
    )
    launcher = write_agent(
        tmp_path,
        "20261030010404",
        "forker",
        meta={
            "wait_for_fork_sources": [
                {
                    "kind": "session",
                    "name": "cx",
                    "requested": "cx",
                    "target": "session",
                    "artifact_dir": str(old_root),
                    "timestamp": old_root.name,
                }
            ]
        },
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(launcher))

    source = resolve_agent_chat_sources(["cx"])[0]

    assert source.kind == "session"
    assert [member.name for member in source.members] == ["cx--plan", "cx--code"]
    assert [member.path for member in source.members] == [
        str(old_plan_chat),
        str(old_code_chat),
    ]


def test_bound_turn_fork_history_omits_members_after_pinned_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    plan_chat = tmp_path / "plan.md"
    gate_chat = tmp_path / "gate.md"
    code_chat = tmp_path / "code.md"
    root = write_agent(
        tmp_path,
        "20261030020101",
        "cx--plan",
        done={"response_path": str(plan_chat), "outcome": "completed"},
        meta={"agent_session": "cx"},
    )
    write_agent(
        tmp_path,
        "20261030020202",
        "cx--gate",
        meta={
            "agent_session": "cx",
            "agent_session_role": "gate",
            "gate_id": "gate0123456789ab",
            "gate_state": "answered",
            "parent_timestamp": root.name,
            "chat_path": str(gate_chat),
        },
    )
    write_agent(
        tmp_path,
        "20261030020303",
        "cx--code",
        done={"response_path": str(code_chat), "outcome": "completed"},
        meta={"agent_session": "cx", "parent_timestamp": "20261030020202"},
    )
    launcher = write_agent(
        tmp_path,
        "20261030020404",
        "forker",
        meta={
            "wait_for_fork_sources": [
                {
                    "kind": "agent",
                    "name": "cx",
                    "requested": "cx",
                    "target": "turn",
                    "target_explicit": True,
                    "turn_name": "cx--plan",
                    "artifact_dir": str(root),
                    "timestamp": root.name,
                }
            ]
        },
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(launcher))

    source = resolve_agent_chat_sources(["cx"])[0]
    rendered = build_fork_injected_history([source.to_json_data()])

    assert [member.name for member in source.members] == ["cx--plan"]
    assert [(member.name, member.status) for member in source.excluded] == [
        ("cx--gate", "after the bound turn"),
        ("cx--code", "after the bound turn"),
    ]
    assert "**Not shown:** `cx--gate` (after the bound turn), " in rendered
    assert "`cx--code` (after the bound turn)" in rendered
    assert "plan.md" in rendered
    assert "gate.md" not in rendered
    assert "code.md" not in rendered


def test_legacy_bound_bare_agent_record_heals_to_promoted_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    plan_chat = tmp_path / "plan.md"
    code_chat = tmp_path / "code.md"
    root = write_agent(
        tmp_path,
        "20261030030101",
        "cx--plan",
        done={"response_path": str(plan_chat), "outcome": "completed"},
        meta={"agent_session": "cx"},
    )
    write_agent(
        tmp_path,
        "20261030030202",
        "cx--code",
        done={"response_path": str(code_chat), "outcome": "completed"},
        meta={"agent_session": "cx", "parent_timestamp": root.name},
    )
    launcher = write_agent(
        tmp_path,
        "20261030030303",
        "forker",
        meta={
            "wait_for_fork_sources": [
                {
                    "kind": "agent",
                    "name": "cx",
                    "artifact_dir": str(root),
                    "timestamp": root.name,
                }
            ]
        },
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(launcher))

    source = resolve_agent_chat_sources(["cx"])[0]

    assert source.kind == "session"
    assert [member.name for member in source.members] == ["cx--plan", "cx--code"]


def test_bound_exact_member_fork_history_uses_the_recorded_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    old_chat = tmp_path / "old-plan.md"
    new_chat = tmp_path / "new-plan.md"
    old_root = write_agent(
        tmp_path,
        "20261030040101",
        "cx--plan",
        done={"response_path": str(old_chat), "outcome": "completed"},
        meta={"agent_session": "cx"},
    )
    write_agent(
        tmp_path,
        "20261030040202",
        "cx--plan",
        done={"response_path": str(new_chat), "outcome": "completed"},
        meta={"agent_session": "cx"},
    )
    launcher = write_agent(
        tmp_path,
        "20261030040303",
        "forker",
        meta={
            "wait_for_fork_sources": [
                {
                    "kind": "agent",
                    "name": "cx",
                    "requested": "cx--plan",
                    "target": "turn",
                    "turn_name": "cx--plan",
                    "artifact_dir": str(old_root),
                    "timestamp": old_root.name,
                }
            ]
        },
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(launcher))

    source = resolve_agent_chat_sources(["cx--plan"])[0]

    assert source.kind == "agent"
    assert source.path == str(old_chat)
