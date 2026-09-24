"""Monitor-start ToolRun reservation (phase monitor-handoff).

A monitor whose proc would run a ToolRun reserves that run up front
(owned by the monitor) and execs the claiming worker instead, leaving
``monitor_command`` / ``monitor_execution_argv`` and ``-f`` bindings
untouched and failing open to E1.5 wrapping when the reservation cannot be
committed.
"""

from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path

import pytest

from sase.monitor.models import MonitorRecord
from sase.monitor.proc_adapter import _compile_monitor_argv
from sase.monitor.start import StartMonitorRequest, start_monitor
from sase.monitor.tool_handoff import (
    _parse_monitor_tool_words,
    format_reservation_fallback_line,
    maybe_reserve_monitor_tool_run,
)
from sase.monitor.tool_wrap import monitor_tool_run_words
from sase.procs.store import get_proc
from sase.running_field import WorkspaceClaim

from ._fixtures import make_starter_agent, wait_for_done, write_project_file

SANDBOX_CATALOG = """\
tools:
  check:
    argv: ["true"]
    description: sandbox verify probe
    stages: none
    inputs: []
    env: []
    args: deny
    fingerprint:
      repos: []
      toolchain: {}
"""


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    for key in (
        "SASE_AGENT",
        "SASE_AGENT_NAME",
        "SASE_MONITOR_ID",
        "SASE_PROC_ID",
        "SASE_TOOL_BYPASS",
        "SASE_TOOL_NAME",
        "SASE_TOOL_PROJECT_ROOT",
        "SASE_TOOL_RUN_AGENT",
        "SASE_TOOL_RUN_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    from sase.config.core import clear_config_cache

    clear_config_cache()


def _sase_argv() -> list[str]:
    return [sys.executable, "-m", "sase"]


def _sandbox_project(tmp_path: Path, name: str = "proj") -> Path:
    root = tmp_path / name
    (root / ".git").mkdir(parents=True)
    sase_dir = root / "sase"
    sase_dir.mkdir(parents=True)
    (sase_dir / "sase.yml").write_text(SANDBOX_CATALOG, encoding="utf-8")
    return root


def test_words_rule2_agent_written_single_run() -> None:
    assert monitor_tool_run_words(
        "sase tool run check", None, ["/bin/sh", "-c", "sase tool run check"], None
    ) == ["check"]


def test_words_rule2_python_m_spelling() -> None:
    command = f"{sys.executable} -m sase tool run check"
    assert monitor_tool_run_words(command, None, ["/bin/sh", "-c", command], None) == [
        "check"
    ]


def test_words_rule7_named_upgrade() -> None:
    assert monitor_tool_run_words(
        "true", None, [*_sase_argv(), "tool", "run", "check"], None
    ) == ["check"]


def test_words_rule8_adhoc_wrap() -> None:
    command = "true && true"
    assert monitor_tool_run_words(
        command,
        None,
        [*_sase_argv(), "tool", "run", "--", "/bin/sh", "-c", command],
        None,
    ) == ["--", "/bin/sh", "-c", command]


def test_words_rule1_execution_argv_never_reserves() -> None:
    execution = [sys.executable, "bootstrap.py"]
    assert (
        monitor_tool_run_words("sase bead work plan.md", execution, execution, None)
        is None
    )


def test_words_unwrapped_reason_never_reserves() -> None:
    # Bypass leaves the raw shell in place: reserving would double-record.
    assert (
        monitor_tool_run_words(
            "sase tool run check",
            None,
            ["/bin/sh", "-c", "sase tool run check"],
            "SASE_TOOL_BYPASS is set",
        )
        is None
    )
    assert (
        monitor_tool_run_words(
            "true", None, _compile_monitor_argv("true"), "monitor.tool_wrap is off"
        )
        is None
    )


def test_parse_rejects_output_mode_options() -> None:
    assert _parse_monitor_tool_words(["check"]) == ("check",)
    assert _parse_monitor_tool_words(["--", "/bin/sh", "-c", "true"]) == (
        "--",
        "/bin/sh",
        "-c",
        "true",
    )
    assert _parse_monitor_tool_words(["-v", "check"]) is None
    assert _parse_monitor_tool_words(["-q", "check"]) is None
    assert _parse_monitor_tool_words(["-T", "5", "check"]) is None
    assert _parse_monitor_tool_words(["-H", "check"]) is None
    assert _parse_monitor_tool_words([]) is None


def test_reserve_declines_without_words(tmp_path: Path) -> None:
    assert (
        maybe_reserve_monitor_tool_run(
            None, cwd=str(tmp_path), monitor_id="m1"
        ).attempted
        is False
    )
    assert (
        maybe_reserve_monitor_tool_run([], cwd=str(tmp_path), monitor_id="m1").attempted
        is False
    )


def test_reserve_declines_output_mode_words(tmp_path: Path) -> None:
    handoff = maybe_reserve_monitor_tool_run(
        ["-v", "check"], cwd=str(tmp_path), monitor_id="m1"
    )
    assert handoff.attempted is False


def test_fallback_line_is_one_line() -> None:
    line = format_reservation_fallback_line("store gone")
    assert line == "sase: tool run not reserved (store gone); running wrapped\n"
    assert line.count("\n") == 1


def _start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    command: str,
    cwd: str,
    profile: str | None = None,
    tool_wrap: str = "verify",
    execution_argv: list[str] | None = None,
    timeout_seconds: float = 120.0,
    timestamp: str = "20260812120000",
) -> MonitorRecord:
    from sase.monitor import store as store_module

    import sase.monitor.start as start_module

    monkeypatch.setattr(start_module, "get_monitor_tool_wrap", lambda: tool_wrap)
    write_project_file(
        "proj",
        running_claims=[WorkspaceClaim(3, "ace-run", "acme", pid=os.getpid())],
    )
    make_starter_agent(
        "proj",
        timestamp,
        "acme",
        model="claude-sonnet-5",
        workspace_dir=cwd,
        workspace_num=3,
        pid=os.getpid(),
        cl_name="acme",
    )

    def live_records(
        project_name: str | None, *, only_monitors: bool = False
    ) -> list[object]:
        from sase.core.paths import sase_projects_dir

        records = []
        for name in [project_name] if project_name else ["proj"]:
            artifacts_root = sase_projects_dir() / name / "artifacts" / "ace-run"
            for meta_path in artifacts_root.glob("*/*/*/agent_meta.json"):
                from ._fixtures import record_from_disk

                record = record_from_disk(meta_path.parent)
                if only_monitors and (
                    record.agent_meta is None
                    or record.agent_meta.agent_session_role != "monitor"
                ):
                    continue
                records.append(record)
        return records

    monkeypatch.setattr(store_module, "project_records", live_records)
    # Production starts run in the starter agent's own shell, so the
    # reservation attributes SASE_AGENT_NAME directly.
    monkeypatch.setenv("SASE_AGENT_NAME", "acme")
    return start_monitor(
        StartMonitorRequest(
            command=command,
            reason="verify wrap",
            timeout_seconds=timeout_seconds,
            cwd=cwd,
            project_name="proj",
            start_status="TESTING",
            stop_status="TESTED",
            lane="acme",
            profile=profile,
            execution_argv=tuple(execution_argv) if execution_argv else None,
        )
    )


def _meta(record: MonitorRecord) -> dict[str, object]:
    meta_path = Path(record.artifacts_dir) / "agent_meta.json"
    return json.loads(meta_path.read_text(encoding="utf-8"))


def test_named_upgrade_reserves_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.core.tool_run import tool_run_list, tool_run_show

    root = _sandbox_project(tmp_path)
    record = _start(
        tmp_path, monkeypatch, command="true", cwd=str(root), profile="verify"
    )
    assert record.tool_run_id
    run_id = record.tool_run_id
    assert _meta(record)["monitor_tool_run_id"] == run_id
    assert _meta(record)["monitor_command"] == "true"
    assert "monitor_execution_argv" not in _meta(record)

    proc = get_proc(record.monitor_id)
    assert proc is not None
    assert proc.argv == [*_sase_argv(), "tool", "_adopt", run_id]
    assert f"tool-run:{run_id}" in list(proc.tags or ())

    done = wait_for_done(record.artifacts_dir)
    assert done["monitor_state"] == "completed"

    runs = tool_run_list({"schema_version": 1, "limit": 10})["runs"]
    assert len(runs) == 1
    run = runs[0]
    assert run.get("run_id") == run_id
    assert run.get("launch_mode") == "handoff"
    assert run.get("owner_kind") == "monitor"
    assert run.get("owner_id") == record.monitor_id
    assert run.get("agent") == "acme"
    shown = tool_run_show(run_id)["run"]
    assert shown["state"] == "succeeded"

    log = Path(record.artifacts_dir) / "live_reply.md"
    text = log.read_text(encoding="utf-8", errors="replace")
    assert f"sase tool run {run_id}" in text
    assert "running unwrapped" not in text
    assert "tool run not reserved" not in text


def test_explicit_tool_run_reserved_not_doubled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.core.tool_run import tool_run_list

    root = _sandbox_project(tmp_path)
    command = shlex.join([*_sase_argv(), "tool", "run", "check"])
    record = _start(
        tmp_path, monkeypatch, command=command, cwd=str(root), profile="verify"
    )
    assert record.tool_run_id
    proc = get_proc(record.monitor_id)
    assert proc is not None
    assert proc.argv == [*_sase_argv(), "tool", "_adopt", record.tool_run_id]
    assert _meta(record)["monitor_command"] == command

    done = wait_for_done(record.artifacts_dir)
    assert done["monitor_state"] == "completed"
    runs = tool_run_list({"schema_version": 1, "limit": 10})["runs"]
    assert len(runs) == 1
    assert runs[0].get("run_id") == record.tool_run_id


def test_output_option_keeps_e15(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.monitor import stop_monitor

    root = _sandbox_project(tmp_path)
    command = shlex.join([*_sase_argv(), "tool", "run", "-q", "check"])
    record = _start(
        tmp_path, monkeypatch, command=command, cwd=str(root), profile="verify"
    )
    # Output-mode options cannot be honored by a hand-off worker: the E1.5
    # argv stays untouched and nothing is reserved. (The inner `-q` run is
    # refused by the owner-presentation rule, so stop the monitor instead
    # of waiting for a follow-up no sandbox runner can deliver.)
    assert record.tool_run_id is None
    assert "monitor_tool_run_id" not in _meta(record)
    proc = get_proc(record.monitor_id)
    assert proc is not None
    assert proc.argv == ["/bin/sh", "-c", command]
    stop_monitor(record)
    done = wait_for_done(record.artifacts_dir)
    assert done["monitor_state"] == "stopped"


def test_epic_launch_creates_no_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.core.tool_run import tool_run_list

    root = _sandbox_project(tmp_path)
    execution = [sys.executable, "bootstrap.py", "--", "sase", "bead", "work"]
    record = _start(
        tmp_path,
        monkeypatch,
        command="sase bead work plan.md",
        cwd=str(root),
        profile="verify",
        execution_argv=execution,
    )
    assert record.tool_run_id is None
    proc = get_proc(record.monitor_id)
    assert proc is not None
    assert proc.argv == execution
    assert tool_run_list({"schema_version": 1, "limit": 10})["runs"] == []


def test_completion_argv_still_raw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.monitor.host_completion_state import _command_argv

    root = _sandbox_project(tmp_path)
    record = _start(
        tmp_path, monkeypatch, command="true", cwd=str(root), profile="verify"
    )
    meta = _meta(record)
    assert meta["monitor_command"] == "true"
    assert "monitor_execution_argv" not in meta
    assert _command_argv(meta) == ["true"]
    wait_for_done(record.artifacts_dir)


def test_failed_reservation_falls_back_with_reason_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.tool.handoff import HandoffReservation

    import sase.monitor.tool_handoff as handoff_module

    root = _sandbox_project(tmp_path)
    monkeypatch.setattr(
        handoff_module,
        "reserve_handoff_run",
        lambda *args, **kwargs: HandoffReservation(
            run_id="deadbeef",
            owner_kind="monitor",
            owner_id="m1",
            events_path=None,
            error="store gone",
        ),
    )
    record = _start(
        tmp_path, monkeypatch, command="true", cwd=str(root), profile="verify"
    )
    assert record.tool_run_id is None
    proc = get_proc(record.monitor_id)
    assert proc is not None
    assert proc.argv == [*_sase_argv(), "tool", "run", "check"]
    log = Path(record.artifacts_dir) / "live_reply.md"
    text = log.read_text(encoding="utf-8", errors="replace")
    assert "sase: tool run not reserved (store gone); running wrapped\n" in text
    done = wait_for_done(record.artifacts_dir)
    assert done["monitor_state"] == "completed"


def test_start_failure_after_reservation_settles_launch_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.monitor import MonitorError
    from sase.procs.submission import ProcSubmitError

    import sase.monitor.start as start_module

    root = _sandbox_project(tmp_path)

    def _boom(*args: object, **kwargs: object) -> object:
        raise ProcSubmitError("supervisor gone")

    monkeypatch.setattr(start_module, "submit_proc_request", _boom)
    with pytest.raises(MonitorError):
        _start(
            tmp_path,
            monkeypatch,
            command="true",
            cwd=str(root),
            profile="verify",
            timestamp="20260812120001",
        )
    from sase.core.tool_run import tool_run_list

    runs = tool_run_list({"schema_version": 1, "limit": 10})["runs"]
    assert len(runs) == 1
    run = runs[0]
    assert run.get("state") == "failed"
    assert run.get("terminal_cause") == "launch_failed"
    assert run.get("launch_mode") == "handoff"
    diagnostics = run.get("diagnostics") or []
    assert any("command was not run" in str(line) for line in diagnostics)


def test_start_json_and_show_carry_tool_run_id() -> None:
    from dataclasses import replace

    from sase.main.monitor_render import monitor_show_json, monitor_start_json

    record = MonitorRecord(
        monitor_id="m" * 32,
        member_agent_name="agent--mon",
        lane="agent",
        project_name="proj",
        artifacts_dir="/tmp/member",
        timestamp="20260812120000",
        command="true",
        cwd="/tmp",
        reason="verify",
        label="true",
        start_status="TESTING",
        stop_status="TESTED",
        timeout_seconds=30.0,
        tail_lines=200,
        monitor_state="running",
        tool_run_id="run123",
    )
    assert monitor_start_json(record, handed_off=False)["monitor"]["tool_run_id"] == (
        "run123"
    )
    payload = monitor_show_json(record, output="")
    assert payload["monitor"]["tool_run_id"] == "run123"
    plain = replace(record, tool_run_id=None)
    assert monitor_start_json(plain, handed_off=False)["monitor"]["tool_run_id"] is None


def test_followup_prompt_lists_tool_run() -> None:
    from sase.monitor.followup_prompt import compose_followup_prompt

    def _prompt(tool_run_id: str | None) -> str:
        return compose_followup_prompt(
            starter_name="acme",
            command="true",
            cwd="/tmp",
            reason="verify",
            monitor_state="completed",
            exit_code=0,
            started_at=None,
            stopped_at=None,
            elapsed_seconds=1.0,
            timeout_seconds=30.0,
            monitor_id="m1",
            output_text="ok",
            tail_lines=200,
            total_bytes=2,
            output_truncated=False,
            next_action="done",
            tool_run_id=tool_run_id,
        )

    assert "sase tool show run123" in _prompt("run123")
    assert "sase tool show" not in _prompt(None)


def test_auto_evidence_tolerates_reservation_fallback_line(
    tmp_path: Path,
) -> None:
    from sase.monitor.result_projection import (
        build_monitor_result_wire,
        select_monitor_result_evidence,
        selected_raw_limits,
    )

    command = "echo hello-evidence; sleep 60"
    log_path = tmp_path / "live_reply.md"
    log_path.write_text(
        "sase: tool run not reserved (store gone); running wrapped\n"
        "sase tool run ef3fe08789955213264bf594c3025804\n"
        "hello-evidence\n"
        "succeeded  exit=0  duration=12ms\n",
        encoding="utf-8",
    )
    result = build_monitor_result_wire(
        monitor_id="mon-evidence",
        monitor_state="timeout",
        exit_code=None,
        command=command,
        cwd=str(tmp_path),
        started_at="unknown",
        stopped_at="unknown",
        elapsed_seconds=5.0,
        timeout_seconds=5.0,
        timeout_kind="total-timeout",
        retained_log={
            "log_ref": "file:monitor-retained-log:test",
            "local_locator": str(log_path),
            "total_observed_bytes": log_path.stat().st_size,
            "complete": True,
            "drain_confirmed": True,
        },
    )
    selection = select_monitor_result_evidence(result, next_output="auto")
    limits = selected_raw_limits(selection, requested_tail_lines=200)
    assert limits is not None
    tail_lines, max_chars = limits
    text = log_path.read_text(encoding="utf-8")
    tail = "".join(text.splitlines(keepends=True)[-tail_lines:])[:max_chars]
    assert "hello-evidence" in tail
