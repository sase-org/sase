"""Tests for stand-alone proc-shell ``#fork`` source resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.procs import Proc, append_proc, proc_log_path
from sase.scripts.agent_chat_from_name import _resolve_agent_chat_sources
from tests._agent_chat_from_name_helpers import write_agent


def _write_proc(
    proc_id: str,
    *,
    status: str = "success",
    label: str = "Build docs",
    command: list[str] | None = None,
    cwd: str = "/tmp/work",
    project: str | None = "proj",
    exit_code: int | None = 0,
    started_at: str | None = "2026-07-25T12:00:00Z",
    finished_at: str | None = "2026-07-25T12:00:05Z",
    shell_name: str | None = None,
    log_text: str | None = None,
) -> Proc:
    proc = Proc(
        proc_id=proc_id,
        label=label,
        kind="command",
        status=status,
        command=command or ["just", "docs"],
        cwd=cwd,
        origin="xprompt-proc",
        created_at=started_at or "2026-07-25T12:00:00Z",
        log_path=str(proc_log_path(proc_id)),
        project=project,
        started_at=started_at,
        finished_at=finished_at,
        exit_code=exit_code,
        shell_name=shell_name,
    )
    append_proc(proc)
    if log_text is not None:
        path = proc_log_path(proc_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(log_text, encoding="utf-8")
    return proc


def test_standalone_proc_resolves_by_exact_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    _write_proc("abcdef0123456789", log_text="hello from the proc\n")

    source = _resolve_agent_chat_sources(["abcdef0123456789"])[0]

    assert source.kind == "proc"
    assert source.name == "abcdef0123456789"
    assert source.proc is not None
    assert source.proc.proc_id == "abcdef0123456789"
    assert source.proc.terminal is True
    assert source.proc.failed is False
    assert source.proc.status == "success"
    assert source.proc.log_tail == "hello from the proc"


def test_standalone_proc_resolves_by_unique_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    _write_proc("abc1112223334445", status="error", exit_code=1)

    source = _resolve_agent_chat_sources(["abc111"])[0]

    assert source.kind == "proc"
    assert source.proc is not None
    assert source.proc.proc_id == "abc1112223334445"
    assert source.proc.terminal is True
    assert source.proc.failed is True


def test_standalone_proc_ambiguous_prefix_raises_actionable_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    _write_proc("aaa1112223334445")
    _write_proc("aaa2223334445556")

    with pytest.raises(RuntimeError, match="ambiguous"):
        _resolve_agent_chat_sources(["aaa"])


def test_unresolvable_name_raises_original_agent_error_not_proc_lookup_noise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    with pytest.raises(
        RuntimeError, match="No agent with chat history found for: nope"
    ):
        _resolve_agent_chat_sources(["nope"])


def test_existing_agent_name_wins_over_colliding_proc_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    chat = tmp_path / "chat.md"
    write_agent(
        tmp_path,
        "20260718010101",
        "sharedname",
        done={"response_path": str(chat), "outcome": "completed"},
    )
    _write_proc("sharedname")  # not a real proc id shape, but should never be tried

    source = _resolve_agent_chat_sources(["sharedname"])[0]

    assert source.kind == "agent"
    assert source.path == str(chat)


def test_proc_sources_with_same_proc_id_are_coalesced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    _write_proc("dedupe0123456789")

    sources = _resolve_agent_chat_sources(["dedupe0123456789", "dedupe012"])

    assert len(sources) == 1
    assert sources[0].proc is not None
    assert sources[0].proc.proc_id == "dedupe0123456789"


def test_standalone_proc_source_json_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    _write_proc("json0123456789ab", command=["bash", "-c", "echo hi"])

    source = _resolve_agent_chat_sources(["json0123456789ab"])[0]
    data = source.to_json_data()

    assert data["kind"] == "proc"
    assert data["name"] == "json0123456789ab"
    proc_data = data["proc"]
    assert isinstance(proc_data, dict)
    assert proc_data["proc_id"] == "json0123456789ab"
    assert proc_data["is_monitor"] is False
    assert proc_data["command"] == "bash -c echo hi"
    assert proc_data["status"] == "success"
    assert proc_data["terminal"] is True
    assert proc_data["failed"] is False


def test_standalone_proc_log_tail_redacts_sensitive_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    _write_proc(
        "secret0123456789",
        log_text="starting up\npassword: hunter2\ndone\n",
    )

    source = _resolve_agent_chat_sources(["secret0123456789"])[0]

    assert source.proc is not None
    assert "hunter2" not in (source.proc.log_tail or "")
    assert "<redacted sensitive line>" in (source.proc.log_tail or "")
