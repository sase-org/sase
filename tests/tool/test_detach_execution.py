"""Execution behavior for detached tool runs."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from ._detach_helpers import agent_env, clean_env, detach_request
from sase.config.core import clear_config_cache
from sase.core.tool_run import (
    tool_run_claim,
    tool_run_list,
    tool_run_reserve_staged_join,
    tool_run_show,
)
from sase.tool.argv import resolve_run_argv
from sase.tool.executor import execute_tool_run
from sase.tool.handoff import reserve_handoff_run


def _rows() -> list:
    listed = tool_run_list({"schema_version": 1, "limit": 100})
    return list(listed.get("runs") or [])


def test_detach_refuses_human_with_handoff_alternative(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clean_env(monkeypatch, tmp_path)
    code = execute_tool_run(detach_request("--", "printf", "hi"))
    assert code == 2
    captured = capsys.readouterr()
    assert "sase tool run -H" in captured.err
    assert _rows() == []


def test_detach_refuses_hand_off_together_verbose_and_tail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clean_env(monkeypatch, tmp_path)
    agent_env(monkeypatch, tmp_path)
    assert execute_tool_run(detach_request("--", "printf", "hi", hand_off=True)) == 2
    capsys.readouterr()
    assert execute_tool_run(detach_request("--", "printf", "hi", verbose=True)) == 2
    assert "verbose" in capsys.readouterr().err
    assert (
        execute_tool_run(detach_request("--", "printf", "hi", tail_lines_explicit=True))
        == 2
    )
    assert "tail-lines" in capsys.readouterr().err
    assert _rows() == []


def test_detach_refuses_inside_live_owner_and_parent_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clean_env(monkeypatch, tmp_path)
    agent_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_PROC_ID", "proc-live")
    monkeypatch.setattr(
        "sase.procs.store.get_proc",
        lambda proc_id: SimpleNamespace(
            status="running", origin="cli", proc_id=proc_id
        ),
    )
    code = execute_tool_run(detach_request("--", "printf", "hi"))
    assert code == 2
    assert "proc-live" in capsys.readouterr().err
    monkeypatch.delenv("SASE_PROC_ID")

    resolved = resolve_run_argv(["--", "printf", "hi"])
    reservation = reserve_handoff_run(resolved, owner_kind="proc", owner_id="proc-1")
    assert reservation.reserved
    monkeypatch.setenv("SASE_TOOL_RUN_ID", reservation.run_id)
    code = execute_tool_run(detach_request("--", "printf", "hi"))
    assert code == 2
    assert "parent tool run" in capsys.readouterr().err


def test_detach_unresolvable_starter_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clean_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-1")
    code = execute_tool_run(detach_request("--", "printf", "hi"))
    assert code == 1
    captured = capsys.readouterr()
    assert (
        "cannot identify the starting agent runner; nothing was started" in captured.err
    )
    assert _rows() == []


def test_detach_accepts_long_tool_skipping_inline_refusal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from sase.procs import read_procs, wait_for_proc

    clean_env(monkeypatch, tmp_path)
    agent_env(monkeypatch, tmp_path)
    (tmp_path / "sase").mkdir(exist_ok=True)
    (tmp_path / "sase" / "sase.yml").write_text(
        yaml.dump(
            {
                "tools": {
                    "slow": {
                        "argv": ["sh", "-c", "exit 0"],
                        "args": "deny",
                        "duration_class": "long",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    clear_config_cache()
    monkeypatch.setenv("SASE_PROVIDER_SYNC_CEILING_SECONDS", "600")
    code = execute_tool_run(detach_request("slow"))
    assert code == 0
    captured = capsys.readouterr()
    run_id = next(
        line.split("sase tool run ")[1].strip().split()[0]
        for line in captured.out.splitlines()
        if line.startswith("sase tool run ")
    )
    assert "detached: stopped when this agent's turn ends" in captured.out
    assert f"sase monitor start -J {run_id}" in captured.out
    shown = tool_run_show(run_id)["run"]
    assert shown["starter"]["agent"] == "agent-1"
    assert shown["starter"]["pid"] == os.getpid()
    assert shown.get("join") is None
    tagged = read_procs(tag=f"tool-run:{run_id}")
    assert len(tagged) == 1
    assert "tool-run-detached" in (tagged[0].tags or [])
    wait_for_proc(tagged[0].proc_id, timeout=30)


def test_detach_quiet_prints_only_run_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from sase.procs import wait_for_proc, read_procs

    clean_env(monkeypatch, tmp_path)
    agent_env(monkeypatch, tmp_path)
    code = execute_tool_run(detach_request("--", "printf", "hi", quiet=True))
    assert code == 0
    captured = capsys.readouterr()
    assert len(captured.out.strip().splitlines()) == 1
    run_id = captured.out.strip()
    tagged = read_procs(tag=f"tool-run:{run_id}")
    assert len(tagged) == 1
    wait_for_proc(tagged[0].proc_id, timeout=30)


def test_detach_keep_going_travels_in_envelope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clean_env(monkeypatch, tmp_path)
    resolved = resolve_run_argv(["--", "printf", "hi"])
    starter = {
        "agent": "agent-1",
        "pid": os.getpid(),
        "boot_id": "boot-1",
        "process_start_identity": "boot-1:1",
    }
    reservation = reserve_handoff_run(
        resolved,
        owner_kind="proc",
        owner_id="proc-9",
        agent="agent-1",
        starter=starter,
        continuation_mode="always",
    )
    assert reservation.reserved
    claimed = tool_run_claim(
        {
            "schema_version": 1,
            "run_id": reservation.run_id,
            "owner_kind": "proc",
            "owner_id": "proc-9",
            "wrapper_pid": os.getpid(),
        }
    )
    assert claimed.get("outcome") == "claimed"
    launch = claimed.get("launch")
    assert isinstance(launch, dict)
    assert launch.get("continuation_mode") == "always"
    shown = tool_run_show(reservation.run_id)["run"]
    assert shown["starter"]["agent"] == "agent-1"
