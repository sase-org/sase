"""Standalone hand-off: worker paths and ``sase tool run -H``."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.config.core import clear_config_cache
from sase.core.tool_run import tool_run_list, tool_run_request_stop, tool_run_show
from sase.feature_flags import override_flags
from sase.tool.adopt import execute_adopted_run
from sase.tool.argv import resolve_run_argv
from sase.tool.executor import ToolRunCliRequest, execute_tool_run
from sase.tool.handoff import (
    envelope_from_resolved,
    owner_request_fingerprint,
    owner_tags,
    reserve_handoff_run,
    resolved_from_envelope,
    worker_argv,
    worker_env_overlay,
)


def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("SASE_HOME", str(home))
    for key in (
        "SASE_AGENT",
        "SASE_AGENT_NAME",
        "SASE_MONITOR_ID",
        "SASE_MONITOR_ARTIFACTS_DIR",
        "SASE_PROC_ID",
        "SASE_PROC_LOG_PATH",
        "SASE_TOOL_RUN_ID",
        "SASE_TOOL_RUN_EVENTS",
        "SASE_TOOL_RUN_AGENT",
        "SASE_BEAD_ID",
        "SASE_BEAD",
        "SASE_WORKSPACE_NUM",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    clear_config_cache()
    return home


def _handoff_request(*words: str, quiet: bool = False) -> ToolRunCliRequest:
    return ToolRunCliRequest(
        quiet=quiet,
        verbose=False,
        tail_lines=200,
        words=tuple(words),
        hand_off=True,
        tail_lines_explicit=False,
    )


def test_envelope_round_trip_preserves_shape() -> None:
    resolved = resolve_run_argv(["--", "printf", "hi"])
    envelope = envelope_from_resolved(resolved)
    assert envelope["argv"] == ["printf", "hi"]
    assert envelope["adhoc"] is True
    rebuilt = resolved_from_envelope(envelope)
    assert rebuilt.argv == resolved.argv
    assert rebuilt.display_argv == resolved.display_argv
    assert rebuilt.adhoc is True


def test_worker_helpers_have_expected_shape() -> None:
    assert worker_argv("abc")[-2:] == ["_adopt", "abc"]
    assert worker_argv("abc")[0] == sys.executable
    assert worker_env_overlay() == {
        "SASE_TOOL_RUN_ID": "",
        "SASE_TOOL_RUN_EVENTS": "",
    }
    assert owner_tags("abc") == ["tool-run", "tool-run:abc"]
    assert owner_request_fingerprint("abc") == "tool-run:abc"


def test_adopt_claimed_runs_frozen_argv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    marker = tmp_path / "claimed.marker"
    resolved = resolve_run_argv(["--", "sh", "-c", f"echo ok > {marker}; exit 0"])
    reservation = reserve_handoff_run(resolved, owner_kind="proc", owner_id="proc-1")
    assert reservation.reserved, reservation.error
    monkeypatch.setenv("SASE_PROC_ID", "proc-1")
    monkeypatch.setenv("SASE_PROC_LOG_PATH", str(tmp_path / "owner.log"))
    with override_flags(tool_handoff=True):
        code = execute_adopted_run(reservation.run_id)
    assert code == 0
    assert marker.read_text(encoding="utf-8").strip() == "ok"
    shown = tool_run_show(reservation.run_id)
    run = shown["run"]
    assert run["owner_kind"] == "proc"
    assert run["owner_id"] == "proc-1"
    assert run["logs"]["owner_log_path"] == str(tmp_path / "owner.log")
    assert run["terminal_cause"] == "exited"
    assert run["launch_mode"] == "handoff"
    captured = capsys.readouterr()
    assert f"sase tool run {reservation.run_id}" in captured.err


def test_adopt_refused_owner_mismatch_spawns_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    marker = tmp_path / "refused.marker"
    resolved = resolve_run_argv(["--", "sh", "-c", f"echo bad > {marker}; exit 0"])
    reservation = reserve_handoff_run(resolved, owner_kind="proc", owner_id="proc-1")
    assert reservation.reserved
    monkeypatch.setenv("SASE_PROC_ID", "proc-2")
    monkeypatch.setenv("SASE_PROC_LOG_PATH", str(tmp_path / "owner.log"))
    with override_flags(tool_handoff=True):
        code = execute_adopted_run(reservation.run_id)
    assert code == 2
    assert not marker.exists()
    captured = capsys.readouterr()
    assert "owner_mismatch" in captured.err
    assert "command was not run" in captured.err


def test_adopt_stopped_before_claim_spawns_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    marker = tmp_path / "stopped.marker"
    resolved = resolve_run_argv(["--", "sh", "-c", f"echo bad > {marker}; exit 0"])
    reservation = reserve_handoff_run(resolved, owner_kind="proc", owner_id="proc-1")
    assert reservation.reserved
    tool_run_request_stop(
        {"schema_version": 1, "run_id": reservation.run_id, "requested_by": "t"}
    )
    monkeypatch.setenv("SASE_PROC_ID", "proc-1")
    monkeypatch.setenv("SASE_PROC_LOG_PATH", str(tmp_path / "owner.log"))
    with override_flags(tool_handoff=True):
        code = execute_adopted_run(reservation.run_id)
    assert code == 143
    assert not marker.exists()
    shown = tool_run_show(reservation.run_id)
    assert shown["run"]["state"] == "signaled"
    assert shown["run"]["terminal_cause"] == "stop_requested"
    captured = capsys.readouterr()
    assert "stopped before it started" in captured.err


def test_adopt_no_owner_touches_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    with override_flags(tool_handoff=True):
        code = execute_adopted_run("deadbeef" * 4)
    assert code == 2
    captured = capsys.readouterr()
    assert "no owner in the environment" in captured.err
    listed = tool_run_list({"schema_version": 1, "limit": 10})
    assert not listed.get("runs")


def test_handoff_end_to_end_settles_through_proc(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    from sase.procs import read_procs, wait_for_proc

    with override_flags(tool_handoff=True):
        started = time.monotonic()
        code = execute_tool_run(_handoff_request("--", "sh", "-c", "sleep 2; exit 7"))
        elapsed = time.monotonic() - started
    assert code == 0
    assert elapsed < 2.0
    captured = capsys.readouterr()
    run_id = None
    for line in captured.out.splitlines():
        if line.startswith("sase tool run "):
            run_id = line.split("sase tool run ")[1].strip().split()[0]
    assert run_id
    # Exactly one ToolRun and one proc tagged to it.
    listed = tool_run_list({"schema_version": 1, "limit": 10})
    assert len(listed.get("runs") or []) == 1
    assert listed["runs"][0]["run_id"] == run_id
    tagged = read_procs(tag=f"tool-run:{run_id}")
    assert len(tagged) == 1
    proc = tagged[0]
    assert proc.proc_id
    finished_proc = wait_for_proc(proc.proc_id, timeout=30)
    assert finished_proc.status in ("error", "success", "killed")
    # Poll the run until it settles (worker finish or reconcile).
    deadline = time.monotonic() + 30
    shown = None
    while time.monotonic() < deadline:
        shown = tool_run_show(run_id)
        if shown["run"]["state"] not in ("created", "running"):
            break
        time.sleep(0.2)
    assert shown is not None
    run = shown["run"]
    assert run["state"] == "failed"
    assert run["exit_code"] == 7
    assert run["owner_kind"] == "proc"
    assert run["owner_id"] == proc.proc_id
    assert run["launch_mode"] == "handoff"
    assert run["terminal_cause"] == "exited"


def test_handoff_quiet_prints_only_run_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    from sase.procs import read_procs, wait_for_proc

    with override_flags(tool_handoff=True):
        code = execute_tool_run(
            _handoff_request("--", "sh", "-c", "exit 0", quiet=True)
        )
    assert code == 0
    captured = capsys.readouterr()
    run_id = captured.out.strip().splitlines()[0].strip()
    assert len(run_id) == 32
    assert len(captured.out.strip().splitlines()) == 1
    tagged = read_procs(tag=f"tool-run:{run_id}")
    assert len(tagged) == 1
    wait_for_proc(tagged[0].proc_id, timeout=30)


def test_handoff_secret_never_reaches_proc_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    from sase.procs import read_procs, wait_for_proc

    with override_flags(tool_handoff=True):
        code = execute_tool_run(
            _handoff_request("--", "sh", "-c", "echo hi", "--token", "SECRET123")
        )
    assert code == 0
    captured = capsys.readouterr()
    run_id = next(
        line.split("sase tool run ")[1].strip().split()[0]
        for line in captured.out.splitlines()
        if line.startswith("sase tool run ")
    )
    tagged = read_procs(tag=f"tool-run:{run_id}")
    assert len(tagged) == 1
    proc = tagged[0]
    assert "SECRET123" not in " ".join(proc.argv)
    assert "SECRET123" not in " ".join(proc.command or [])
    from sase.main.proc_render import proc_show_json

    payload = proc_show_json(proc, log="", live_session_ids=set())
    assert "SECRET123" not in json.dumps(payload)
    wait_for_proc(proc.proc_id, timeout=30)


def test_handoff_unwritable_store_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = _clean_env(monkeypatch, tmp_path)
    (home / "tools").write_text("not-a-directory", encoding="utf-8")
    from sase.procs import read_procs

    with override_flags(tool_handoff=True):
        code = execute_tool_run(_handoff_request("--", "printf", "hi"))
    assert code == 1
    captured = capsys.readouterr()
    assert "nothing was started" in captured.err
    assert not read_procs()
    # Foreground stays fail-open in the same state.
    from sase.tool.executor import ToolRunCliRequest as ForegroundRequest

    capsys.readouterr()
    code_fg = execute_tool_run(
        ForegroundRequest(
            quiet=False, verbose=False, tail_lines=200, words=("--", "printf", "hi")
        )
    )
    assert code_fg == 0
    captured_fg = capsys.readouterr()
    assert captured_fg.out == "hi"


def test_handoff_frozen_argv_survives_catalog_edit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import yaml

    _clean_env(monkeypatch, tmp_path)
    (tmp_path / "sase").mkdir()
    marker = tmp_path / "frozen.marker"
    (tmp_path / "sase" / "sase.yml").write_text(
        yaml.dump(
            {
                "tools": {
                    "mytool": {
                        "argv": ["sh", "-c", f"echo frozen > {marker}"],
                        "args": "deny",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    clear_config_cache()
    resolved = resolve_run_argv(["mytool"], cwd=tmp_path)
    reservation = reserve_handoff_run(resolved, owner_kind="proc", owner_id="proc-9")
    assert reservation.reserved
    (tmp_path / "sase" / "sase.yml").write_text(
        yaml.dump(
            {
                "tools": {
                    "mytool": {
                        "argv": ["sh", "-c", f"echo edited > {marker}"],
                        "args": "deny",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    clear_config_cache()
    monkeypatch.setenv("SASE_PROC_ID", "proc-9")
    monkeypatch.setenv("SASE_PROC_LOG_PATH", str(tmp_path / "owner.log"))
    with override_flags(tool_handoff=True):
        code = execute_adopted_run(reservation.run_id)
    assert code == 0
    assert marker.read_text(encoding="utf-8").strip() == "frozen"


def test_handoff_submit_failure_settles_launch_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)

    def _boom(*args, **kwargs):  # type: ignore[no-untyped-def]
        from sase.procs.submission import ProcSubmitError

        raise ProcSubmitError("supervisor down")

    monkeypatch.setattr("sase.procs.submit_proc_request", _boom)
    with override_flags(tool_handoff=True):
        code = execute_tool_run(_handoff_request("--", "printf", "hi"))
    assert code == 1
    captured = capsys.readouterr()
    assert "command was not run" in captured.err
    listed = tool_run_list({"schema_version": 1, "limit": 10})
    assert len(listed.get("runs") or []) == 1
    run = listed["runs"][0]
    assert run["state"] == "failed"
    assert run["terminal_cause"] == "launch_failed"
    shown = tool_run_show(run["run_id"])
    assert any("command was not run" in d for d in shown["run"]["diagnostics"])


def test_handoff_refuses_inside_agent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_AGENT", "1")
    with override_flags(tool_handoff=True):
        code = execute_tool_run(_handoff_request("--", "printf", "hi"))
    assert code == 2
    captured = capsys.readouterr()
    assert (
        "sase monitor start -p verify --reason 'hand off tool run' -- sase tool run"
        in captured.err
    )
    listed = tool_run_list({"schema_version": 1, "limit": 10})
    assert not listed.get("runs")


def test_handoff_refuses_inside_live_proc(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_PROC_ID", "proc-live")
    monkeypatch.setattr(
        "sase.procs.store.get_proc",
        lambda proc_id: SimpleNamespace(
            status="running", origin="cli", proc_id=proc_id
        ),
    )
    with override_flags(tool_handoff=True):
        code = execute_tool_run(_handoff_request("--", "printf", "hi"))
    assert code == 2
    captured = capsys.readouterr()
    assert "proc proc-live" in captured.err
    listed = tool_run_list({"schema_version": 1, "limit": 10})
    assert not listed.get("runs")


def test_handoff_tui_proc_message_says_drop_H(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_PROC_ID", "proc-tui")
    monkeypatch.setattr(
        "sase.procs.store.get_proc",
        lambda proc_id: SimpleNamespace(
            status="running", origin="ace", proc_id=proc_id
        ),
    )
    with override_flags(tool_handoff=True):
        code = execute_tool_run(_handoff_request("--", "printf", "hi"))
    assert code == 2
    captured = capsys.readouterr()
    assert "already a detached proc" in captured.err
    assert "drop -H" in captured.err


def test_handoff_verbose_and_tail_are_usage_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    with override_flags(tool_handoff=True):
        code_v = execute_tool_run(
            ToolRunCliRequest(
                quiet=False,
                verbose=True,
                tail_lines=200,
                words=("--", "printf", "hi"),
                hand_off=True,
                tail_lines_explicit=False,
            )
        )
        assert code_v == 2
        capsys.readouterr()
        code_t = execute_tool_run(
            ToolRunCliRequest(
                quiet=False,
                verbose=False,
                tail_lines=5,
                words=("--", "printf", "hi"),
                hand_off=True,
                tail_lines_explicit=True,
            )
        )
        assert code_t == 2
    listed = tool_run_list({"schema_version": 1, "limit": 10})
    assert not listed.get("runs")


def test_handoff_flag_off_refuses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    from sase.procs import read_procs

    with override_flags(tool_handoff=False):
        code = execute_tool_run(_handoff_request("--", "printf", "hi"))
    assert code == 2
    captured = capsys.readouterr()
    assert "tool_handoff" in captured.err
    listed = tool_run_list({"schema_version": 1, "limit": 10})
    assert not listed.get("runs")
    assert not read_procs()


def test_parser_adopt_hidden_and_hand_off_present(
    capsys: pytest.CaptureFixture[str],
) -> None:
    import argparse

    from sase.main.parser_tool import register_tool_parser

    parser = argparse.ArgumentParser(prog="sase")
    subs = parser.add_subparsers(dest="command")
    register_tool_parser(subs)
    args = parser.parse_args(["tool", "run", "-H", "--", "printf", "hi"])
    assert args.hand_off is True
    assert args.tail_lines is None
    args2 = parser.parse_args(["tool", "run", "--", "printf", "hi"])
    assert args2.hand_off is False
    assert args2.tail_lines is None
    adopt = parser.parse_args(["tool", "_adopt", "abc123"])
    assert adopt.adopt_run_id == "abc123"
    tool_help = parser.format_help()
    assert "_adopt" not in tool_help
    # run subparser help mentions -H.
    run_help = None
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                if name == "tool":
                    for sub_action in sub._actions:
                        if isinstance(sub_action, argparse._SubParsersAction):
                            run_parser = sub_action.choices.get("run")
                            if run_parser is not None:
                                run_help = run_parser.format_help()
    assert run_help is not None
    assert "-H" in run_help
    assert "--hand-off" in run_help
