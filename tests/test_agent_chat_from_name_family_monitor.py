"""Tests for monitor family members as typed proc-shell ``#fork`` sources."""

from __future__ import annotations

from pathlib import Path

import pytest

import sase.scripts._agent_chat_from_name_monitor as monitor_source
from sase.scripts.agent_chat_from_name import (
    _ForkFamilyMemberSource,
    _resolve_agent_chat_sources,
)
from tests._agent_chat_from_name_helpers import write_agent

_BASE_MONITOR_META: dict[str, object] = {
    "agent_family": "cx",
    "agent_family_role": "monitor",
    "monitor_id": "mon0123456789ab",
    "monitor_command": "pytest -k thing",
    "monitor_cwd": "/tmp/work",
    "monitor_reason": "watch the test suite",
    "monitor_label": "test watcher",
}


def _write_monitor_member(
    tmp_path: Path,
    suffix: str,
    name: str,
    *,
    parent_timestamp: str,
    done: dict[str, object] | None = None,
    output_path: Path | None = None,
) -> Path:
    meta: dict[str, object] = {
        **_BASE_MONITOR_META,
        "parent_timestamp": parent_timestamp,
    }
    if output_path is not None:
        meta["monitor_output_path"] = str(output_path)
    return write_agent(tmp_path, suffix, name, done=done, meta=meta)


def test_family_source_includes_terminal_completed_monitor_as_proc_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    planner_chat = tmp_path / "planner.md"
    write_agent(
        tmp_path,
        "20260718010101",
        "cx--plan",
        done={"response_path": str(planner_chat), "outcome": "completed"},
        meta={"agent_family": "cx"},
    )
    output_path = tmp_path / "monitor_output.log"
    output_path.write_text("watching...\nall green\n", encoding="utf-8")
    _write_monitor_member(
        tmp_path,
        "20260718010202",
        "cx--mon",
        parent_timestamp="20260718010101",
        done={
            "outcome": "monitored",
            "monitor_state": "completed",
            "monitor_exit_code": 0,
        },
        output_path=output_path,
    )

    source = _resolve_agent_chat_sources(["cx"])[0]

    assert [member.name for member in source.members] == ["cx--plan", "cx--mon"]
    monitor_member = source.members[1]
    assert isinstance(monitor_member, _ForkFamilyMemberSource)
    assert monitor_member.kind == "proc"
    assert monitor_member.outcome == "completed"
    assert monitor_member.proc is not None
    assert monitor_member.proc.is_monitor is True
    assert monitor_member.proc.terminal is True
    assert monitor_member.proc.failed is False
    assert monitor_member.proc.proc_id == "mon0123456789ab"
    assert monitor_member.proc.command == "pytest -k thing"
    assert "all green" in (monitor_member.proc.log_tail or "")
    assert source.excluded == ()


def test_family_source_includes_terminal_failed_monitor_with_failed_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    write_agent(
        tmp_path,
        "20260718010101",
        "cx--plan",
        done={"response_path": str(tmp_path / "planner.md"), "outcome": "completed"},
        meta={"agent_family": "cx"},
    )
    (tmp_path / "planner.md").write_text("hi", encoding="utf-8")
    _write_monitor_member(
        tmp_path,
        "20260718010202",
        "cx--mon",
        parent_timestamp="20260718010101",
        done={
            "outcome": "monitored",
            "monitor_state": "timeout",
            "monitor_exit_code": None,
        },
    )

    source = _resolve_agent_chat_sources(["cx"])[0]

    monitor_member = source.members[1]
    assert isinstance(monitor_member, _ForkFamilyMemberSource)
    assert monitor_member.kind == "proc"
    assert monitor_member.outcome == "timeout"
    assert monitor_member.proc is not None
    assert monitor_member.proc.terminal is True
    assert monitor_member.proc.failed is True


def test_family_source_excludes_still_running_monitor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    write_agent(
        tmp_path,
        "20260718010101",
        "cx--plan",
        done={"response_path": str(tmp_path / "planner.md"), "outcome": "completed"},
        meta={"agent_family": "cx"},
    )
    (tmp_path / "planner.md").write_text("hi", encoding="utf-8")
    _write_monitor_member(
        tmp_path,
        "20260718010202",
        "cx--mon",
        parent_timestamp="20260718010101",
        done=None,
    )

    source = _resolve_agent_chat_sources(["cx"])[0]

    assert [member.name for member in source.members] == ["cx--plan"]
    assert [(member.name, member.status) for member in source.excluded] == [
        ("cx--mon", "running")
    ]


def test_explicit_monitor_member_fork_resolves_as_proc_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    write_agent(
        tmp_path,
        "20260718010101",
        "cx--plan",
        done={"response_path": str(tmp_path / "planner.md"), "outcome": "completed"},
        meta={"agent_family": "cx"},
    )
    (tmp_path / "planner.md").write_text("hi", encoding="utf-8")
    _write_monitor_member(
        tmp_path,
        "20260718010202",
        "cx--mon",
        parent_timestamp="20260718010101",
        done={"outcome": "monitored", "monitor_state": "completed"},
    )

    source = _resolve_agent_chat_sources(["cx--mon"])[0]

    assert source.kind == "proc"
    assert source.proc is not None
    assert source.proc.is_monitor is True
    assert source.proc.proc_id == "mon0123456789ab"


def test_resolved_monitor_artifact_fork_resolves_as_proc_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    _write_monitor_member(
        tmp_path,
        "20260718010202",
        "watcher",
        parent_timestamp="20260718010101",
        done={"outcome": "monitored", "monitor_state": "completed"},
    )

    source = _resolve_agent_chat_sources(["watcher"])[0]

    assert source.kind == "proc"
    assert source.name == "watcher"
    assert source.proc is not None
    assert source.proc.is_monitor is True
    assert source.proc.proc_id == "mon0123456789ab"


def test_missing_monitor_record_for_resolved_artifact_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    _write_monitor_member(
        tmp_path,
        "20260718010202",
        "watcher",
        parent_timestamp="20260718010101",
        done={"outcome": "monitored", "monitor_state": "completed"},
    )
    monkeypatch.setattr(
        monitor_source,
        "read_monitor_marker",
        lambda project_name, artifacts_dir: None,
    )

    with pytest.raises(RuntimeError, match="Monitor record for agent 'watcher'"):
        _resolve_agent_chat_sources(["watcher"])
