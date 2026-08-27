"""Tests for gate-shell family members as typed ``#fork`` sources."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.scripts.agent_chat_from_name import (
    _ForkFamilyMemberSource,
    _resolve_agent_chat_sources,
)
from tests._agent_chat_from_name_helpers import write_agent

_BASE_GATE_META: dict[str, object] = {
    "agent_family": "cx",
    "agent_family_role": "gate",
    "gate_id": "custom-gate0123456789",
    "gate_kind": "custom",
}


def _write_gate_member(
    tmp_path: Path,
    suffix: str,
    name: str,
    *,
    parent_timestamp: str,
    gate_state: str | None,
    chat_path: Path | None = None,
) -> Path:
    meta: dict[str, object] = {
        **_BASE_GATE_META,
        "parent_timestamp": parent_timestamp,
        "gate_state": gate_state,
    }
    if chat_path is not None:
        meta["chat_path"] = str(chat_path)
    return write_agent(tmp_path, suffix, name, meta=meta)


def _write_planner(tmp_path: Path) -> None:
    write_agent(
        tmp_path,
        "20260718010101",
        "cx--plan",
        done={"response_path": str(tmp_path / "planner.md"), "outcome": "completed"},
        meta={"agent_family": "cx"},
    )
    (tmp_path / "planner.md").write_text("hi", encoding="utf-8")


def test_family_source_includes_settled_gate_shell_as_gate_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    _write_planner(tmp_path)
    chat_path = tmp_path / "gate_decision.md"
    _write_gate_member(
        tmp_path,
        "20260718010202",
        "cx--gate",
        parent_timestamp="20260718010101",
        gate_state="answered",
        chat_path=chat_path,
    )

    source = _resolve_agent_chat_sources(["cx"])[0]

    assert [member.name for member in source.members] == ["cx--plan", "cx--gate"]
    gate_member = source.members[1]
    assert isinstance(gate_member, _ForkFamilyMemberSource)
    assert gate_member.kind == "gate"
    assert gate_member.outcome == "answered"
    assert gate_member.path == str(chat_path)
    assert source.excluded == ()


def test_family_source_excludes_pending_gate_shell_as_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    _write_planner(tmp_path)
    _write_gate_member(
        tmp_path,
        "20260718010202",
        "cx--gate",
        parent_timestamp="20260718010101",
        gate_state="pending",
    )

    source = _resolve_agent_chat_sources(["cx"])[0]

    assert [member.name for member in source.members] == ["cx--plan"]
    assert [(member.name, member.status) for member in source.excluded] == [
        ("cx--gate", "running")
    ]


def test_family_fork_history_labels_gate_shell_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    _write_planner(tmp_path)
    chat_path = tmp_path / "gate_decision.md"
    _write_gate_member(
        tmp_path,
        "20260718010202",
        "cx--gate",
        parent_timestamp="20260718010101",
        gate_state="answered",
        chat_path=chat_path,
    )
    chat_path.write_text("# Gate answered\n\ncleanup, verify", encoding="utf-8")

    from sase.history.chat import build_fork_injected_history

    history = build_fork_injected_history(
        [source.to_json_data() for source in _resolve_agent_chat_sources(["cx"])]
    )

    assert "gate shell `cx--gate`" in history
    assert "cleanup, verify" in history


def test_explicit_gate_member_fork_yields_gate_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    _write_planner(tmp_path)
    chat_path = tmp_path / "gate_decision.md"
    _write_gate_member(
        tmp_path,
        "20260718010202",
        "cx--gate",
        parent_timestamp="20260718010101",
        gate_state="answered",
        chat_path=chat_path,
    )

    source = _resolve_agent_chat_sources(["cx--gate"])[0]

    assert source.path == str(chat_path)
