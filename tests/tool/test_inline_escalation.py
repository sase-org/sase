"""Inline-then-escalate: an agent's plain ``sase tool run`` starts detached."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest
import yaml

from sase.config.core import clear_config_cache
from sase.core.process_identity import process_identity_token
from sase.core.tool_run import tool_run_list, tool_run_show
from sase.feature_flags import override_flags
from sase.tool.argv import resolve_run_argv
from sase.tool.control import ToolWaitCliRequest, handle_wait
from sase.tool.executor import ToolRunCliRequest, execute_tool_run
from sase.tool.handoff import reserve_handoff_run


def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("SASE_HOME", str(home))
    for key in (
        "SASE_AGENT",
        "SASE_AGENT_NAME",
        "SASE_ARTIFACTS_DIR",
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
        "SASE_PROVIDER_SYNC_CEILING_SECONDS",
        "SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    clear_config_cache()
    return home


def _agent_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    name: str = "agent-1",
) -> Path:
    """Agent env whose runner PID is live (this test process)."""

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(exist_ok=True)
    (artifacts / "agent_meta.json").write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "process_identity": process_identity_token(os.getpid()),
                "name": name,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_AGENT_NAME", name)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    return artifacts


def _request(
    *words: str, quiet: bool = False, verbose: bool = False
) -> ToolRunCliRequest:
    return ToolRunCliRequest(
        quiet=quiet,
        verbose=verbose,
        tail_lines=200,
        words=tuple(words),
    )


def _rows() -> list:
    listed = tool_run_list({"schema_version": 1, "limit": 100})
    return list(listed.get("runs") or [])


def _first_run_id_line(text: str) -> str:
    line = next(item for item in text.splitlines() if item.startswith("sase tool run "))
    return line.split("sase tool run ")[1].strip().split()[0]


def test_fast_success_matches_inline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from sase.procs import read_procs, wait_for_proc

    _clean_env(monkeypatch, tmp_path)
    _agent_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS", "8")
    argv = ("--", "sh", "-c", "printf out")
    with override_flags(tool_run_escalation=True):
        code = execute_tool_run(_request(*argv))
    assert code == 0
    captured = capsys.readouterr()
    run_id = _first_run_id_line(captured.err)
    assert "succeeded" in captured.err
    assert f"sase tool show {run_id} -l" in captured.err
    rows = _rows()
    assert len(rows) == 1
    assert rows[0]["launch_mode"] == "handoff"
    shown = tool_run_show(run_id)["run"]
    assert shown["starter"]["agent"] == "agent-1"
    for proc in read_procs(tag=f"tool-run:{run_id}"):
        wait_for_proc(proc.proc_id, timeout=30)

    with override_flags(tool_run_escalation=False):
        assert execute_tool_run(_request(*argv)) == code
    capsys.readouterr()


def test_fast_failure_matches_inline_with_tail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from sase.procs import read_procs, wait_for_proc

    _clean_env(monkeypatch, tmp_path)
    _agent_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS", "8")
    argv = ("--", "sh", "-c", "printf 'line1\\nline2\\nline3\\n'; exit 3")
    with override_flags(tool_run_escalation=True):
        code = execute_tool_run(_request(*argv))
    assert code == 3
    captured = capsys.readouterr()
    run_id = _first_run_id_line(captured.err)
    assert "failed/3" in captured.err
    assert "line3" in captured.err
    assert f"sase tool show {run_id} -l" in captured.err
    assert len(_rows()) == 1
    for proc in read_procs(tag=f"tool-run:{run_id}"):
        wait_for_proc(proc.proc_id, timeout=30)

    with override_flags(tool_run_escalation=False):
        assert execute_tool_run(_request(*argv)) == code
    capsys.readouterr()


def test_verbose_streams_child_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from sase.procs import read_procs, wait_for_proc

    _clean_env(monkeypatch, tmp_path)
    _agent_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS", "8")
    with override_flags(tool_run_escalation=True):
        code = execute_tool_run(_request("--", "sh", "-c", "printf out", verbose=True))
    assert code == 0
    captured = capsys.readouterr()
    # The streamed record is the proc log, which also carries the worker's
    # own wrapper lines: assert the child's bytes are present, not exclusive.
    assert "out" in captured.out
    assert "succeeded" in captured.err
    run_id = _first_run_id_line(captured.err)
    for proc in read_procs(tag=f"tool-run:{run_id}"):
        wait_for_proc(proc.proc_id, timeout=30)


def test_slow_command_escalates_and_wait_returns_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from sase.procs import read_procs, wait_for_proc

    _clean_env(monkeypatch, tmp_path)
    _agent_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS", "8")
    with override_flags(tool_run_escalation=True):
        code = execute_tool_run(_request("--", "sh", "-c", "sleep 14; exit 3"))
    assert code == 124
    captured = capsys.readouterr()
    run_id = _first_run_id_line(captured.err)
    assert "ad-hoc" in captured.err
    assert "was not stopped" in captured.err
    assert "SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS" in captured.err
    assert f"sase monitor start -J {run_id}" in captured.err
    assert f"sase tool wait {run_id}" in captured.err
    assert tool_run_show(run_id)["run"]["state"] in ("created", "running")

    monkeypatch.delenv("SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS")
    with override_flags(tool_run_escalation=True):
        assert handle_wait(ToolWaitCliRequest(run_id=run_id)) == 3
    capsys.readouterr()
    assert len(_rows()) == 1
    for proc in read_procs(tag=f"tool-run:{run_id}"):
        wait_for_proc(proc.proc_id, timeout=30)


def test_sigterm_leaves_run_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import signal as signal_module

    from sase.procs import read_procs, wait_for_proc
    from sase.tool.control import ToolStopCliRequest, handle_stop

    _clean_env(monkeypatch, tmp_path)
    _agent_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS", "60")
    previous_term = signal_module.getsignal(signal_module.SIGTERM)
    previous_int = signal_module.getsignal(signal_module.SIGINT)
    previous_hup = signal_module.getsignal(signal_module.SIGHUP)
    stop_fired = threading.Event()

    def _kill_after_launch() -> None:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and not stop_fired.is_set():
            try:
                rows = _rows()
            except Exception:  # noqa: BLE001 - the main thread owns the store.
                rows = []
            if any(row.get("launch_mode") == "handoff" for row in rows):
                break
            time.sleep(0.2)  # sase-test-wait: follower reservation handshake
        time.sleep(2.0)  # sase-test-wait: follower is inside its bounded wait
        if stop_fired.is_set():
            return
        os.kill(os.getpid(), signal_module.SIGTERM)

    killer = threading.Thread(target=_kill_after_launch, daemon=True)
    try:
        with override_flags(tool_run_escalation=True):
            killer.start()
            code = execute_tool_run(_request("--", "sh", "-c", "sleep 60"))
    finally:
        stop_fired.set()
        killer.join(timeout=10)
        assert signal_module.getsignal(signal_module.SIGTERM) is previous_term
        assert signal_module.getsignal(signal_module.SIGINT) is previous_int
        assert signal_module.getsignal(signal_module.SIGHUP) is previous_hup
    assert code == 143
    captured = capsys.readouterr()
    run_id = _first_run_id_line(captured.err)
    assert "was not stopped" in captured.err
    assert f"sase monitor start -J {run_id}" in captured.err
    assert tool_run_show(run_id)["run"]["state"] in ("created", "running")
    assert handle_stop(ToolStopCliRequest(run_id=run_id)) == 0
    capsys.readouterr()
    for proc in read_procs(tag=f"tool-run:{run_id}"):
        wait_for_proc(proc.proc_id, timeout=30)


def _write_run_silent_catalog(tmp_path: Path) -> None:
    (tmp_path / "sase").mkdir(exist_ok=True)
    (tmp_path / "sase" / "sase.yml").write_text(
        yaml.dump(
            {
                "tools": {
                    "staged": {
                        "argv": ["true"],
                        "args": "deny",
                        "stages": "run_silent",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    clear_config_cache()


@pytest.mark.parametrize(
    ("flag", "expected"),
    [("keep_going", "always"), ("fail_fast", "never")],
)
def test_continuation_flags_travel_in_envelope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    flag: str,
    expected: str,
) -> None:
    from sase.tool import handoff_launch
    from sase.tool.handoff import HandoffReservation
    from sase.tool.handoff_launch import HandoffSubmitResult

    _clean_env(monkeypatch, tmp_path)
    _agent_env(monkeypatch, tmp_path)
    _write_run_silent_catalog(tmp_path)
    monkeypatch.setenv("SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS", "8")
    seen: dict[str, object] = {}

    def _fake_submit(resolved: object, **kwargs: object) -> HandoffSubmitResult:
        seen.update(kwargs)
        return HandoffSubmitResult(
            reservation=HandoffReservation(
                run_id="0" * 32,
                owner_kind="proc",
                owner_id="proc-0",
                events_path=None,
                error="injected",
            ),
            proc_id="proc-0",
        )

    monkeypatch.setattr(handoff_launch, "submit_handoff_run", _fake_submit)
    request = ToolRunCliRequest(
        quiet=False,
        verbose=False,
        tail_lines=200,
        words=("staged",),
        keep_going=(flag == "keep_going"),
        fail_fast=(flag == "fail_fast"),
    )
    with override_flags(tool_run_escalation=True):
        assert execute_tool_run(request) == 0
    assert seen.get("continuation_mode") == expected
    assert seen.get("detached") is True
    assert "inline escalation unavailable" in capsys.readouterr().err


def test_agent_default_continuation_is_known(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from sase.tool import handoff_launch
    from sase.tool.handoff import HandoffReservation
    from sase.tool.handoff_launch import HandoffSubmitResult

    _clean_env(monkeypatch, tmp_path)
    _agent_env(monkeypatch, tmp_path)
    _write_run_silent_catalog(tmp_path)
    monkeypatch.setenv("SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS", "8")
    seen: dict[str, object] = {}

    def _fake_submit(resolved: object, **kwargs: object) -> HandoffSubmitResult:
        seen.update(kwargs)
        return HandoffSubmitResult(
            reservation=HandoffReservation(
                run_id="0" * 32,
                owner_kind="proc",
                owner_id="proc-0",
                events_path=None,
                error="injected",
            ),
            proc_id="proc-0",
        )

    monkeypatch.setattr(handoff_launch, "submit_handoff_run", _fake_submit)
    with override_flags(tool_run_escalation=True):
        assert execute_tool_run(_request("staged")) == 0
    assert seen.get("continuation_mode") == "known"
    capsys.readouterr()


def test_unresolvable_starter_falls_back_inline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-1")
    monkeypatch.setenv("SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS", "8")
    with override_flags(tool_run_escalation=True):
        code = execute_tool_run(_request("--", "printf", "hi"))
    assert code == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count("inline escalation unavailable") == 1
    assert "running inline" in captured.err
    rows = _rows()
    assert len(rows) == 1
    assert rows[0].get("starter") is None
    inline_run = tool_run_show(rows[0]["run_id"])["run"]
    assert inline_run["state"] == "succeeded"
    stdout_log = Path(inline_run["logs"]["stdout_path"])
    assert stdout_log.read_bytes() == b"hi"


def test_submit_error_falls_back_inline_with_launch_failed_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import sase.procs

    _clean_env(monkeypatch, tmp_path)
    _agent_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS", "8")

    def _boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("proc submit boom")

    monkeypatch.setattr(sase.procs, "submit_proc_request", _boom)
    with override_flags(tool_run_escalation=True):
        code = execute_tool_run(_request("--", "printf", "hi"))
    assert code == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count("inline escalation unavailable") == 1
    rows = _rows()
    assert len(rows) == 2
    shown = [tool_run_show(row["run_id"])["run"] for row in rows]
    assert "launch_failed" in {run.get("terminal_cause") for run in shown}
    inline_run = next(
        run for run in shown if run.get("terminal_cause") != "launch_failed"
    )
    assert inline_run["state"] == "succeeded"
    stdout_log = Path(inline_run["logs"]["stdout_path"])
    assert stdout_log.read_bytes() == b"hi"


def test_flag_off_stays_inline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    _agent_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS", "8")
    with override_flags(tool_run_escalation=False):
        code = execute_tool_run(_request("--", "sh", "-c", "exit 4"))
    assert code == 4
    captured = capsys.readouterr()
    assert "inline escalation unavailable" not in captured.err
    rows = _rows()
    assert len(rows) == 1
    assert rows[0].get("launch_mode") != "handoff"
    assert rows[0].get("starter") is None


def test_no_agent_stays_inline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS", "8")
    with override_flags(tool_run_escalation=True):
        code = execute_tool_run(_request("--", "sh", "-c", "exit 4"))
    assert code == 4
    captured = capsys.readouterr()
    assert "inline escalation unavailable" not in captured.err
    assert len(_rows()) == 1


def test_no_ceiling_stays_inline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    _agent_env(monkeypatch, tmp_path)
    with override_flags(tool_run_escalation=True):
        code = execute_tool_run(_request("--", "sh", "-c", "exit 4"))
    assert code == 4
    captured = capsys.readouterr()
    assert "inline escalation unavailable" not in captured.err
    rows = _rows()
    assert len(rows) == 1
    assert rows[0].get("starter") is None


def test_live_monitor_stays_inline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    _agent_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS", "8")
    monkeypatch.setenv("SASE_MONITOR_ID", "mon-live")
    with override_flags(tool_run_escalation=True):
        code = execute_tool_run(_request("--", "sh", "-c", "exit 4"))
    assert code == 4
    captured = capsys.readouterr()
    assert "inline escalation unavailable" not in captured.err
    rows = _rows()
    assert len(rows) == 1
    assert rows[0].get("starter") is None


def test_parent_run_stays_inline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    _agent_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS", "8")
    resolved = resolve_run_argv(["--", "true"])
    reservation = reserve_handoff_run(
        resolved, owner_kind="proc", owner_id="proc-parent"
    )
    assert reservation.reserved
    monkeypatch.setenv("SASE_TOOL_RUN_ID", reservation.run_id)
    with override_flags(tool_run_escalation=True):
        code = execute_tool_run(_request("--", "sh", "-c", "exit 4"))
    assert code == 4
    captured = capsys.readouterr()
    assert "inline escalation unavailable" not in captured.err
    rows = _rows()
    assert len(rows) == 2
    inline_row = next(row for row in rows if row["run_id"] != reservation.run_id)
    assert inline_row.get("launch_mode") != "handoff"
    assert inline_row.get("starter") is None


def test_long_tool_refusal_stays_in_front(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    _agent_env(monkeypatch, tmp_path)
    marker = tmp_path / "slow.marker"
    (tmp_path / "sase").mkdir(exist_ok=True)
    (tmp_path / "sase" / "sase.yml").write_text(
        yaml.dump(
            {
                "tools": {
                    "slow": {
                        "argv": ["sh", "-c", f"touch {marker}"],
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
    with override_flags(tool_run_escalation=True):
        code = execute_tool_run(_request("slow"))
    assert code == 2
    captured = capsys.readouterr()
    assert "refused before starting slow" in captured.err
    assert not marker.exists()
    assert _rows() == []


def test_settled_exit_mapping() -> None:
    from sase.tool.inline_escalation import _settled_exit

    assert _settled_exit({"exit_code": 3, "state": "failed"}) == 3
    assert _settled_exit({"exit_code": 0, "state": "succeeded"}) == 0
    assert _settled_exit({"exit_code": 130, "state": "interrupted"}) == 130
    assert (
        _settled_exit({"terminal_cause": "stop_requested", "state": "signaled"}) == 143
    )
    assert _settled_exit({"state": "signaled"}) == 143
    assert _settled_exit({"state": "lost"}) == 1
    assert _settled_exit({"state": "failed"}) == 1


def test_ledger_footer_renderer_shapes(capsys: pytest.CaptureFixture[str]) -> None:
    from sase.tool.executor_display import write_run_footer

    stages = (
        {
            "description": "staged",
            "started_ts": 1_000,
            "finished_ts": 2_000,
            "elapsed_ms": 1_000,
            "exit_code": 3,
            "incomplete": False,
        },
    )
    write_run_footer(
        durable_id="abc123",
        state="failed",
        exit_code=3,
        duration_ms=1000,
        compact=True,
        tail_lines=200,
        stdout_sink=None,
        stderr_sink=None,
        stages=stages,
        truncation=["retained output truncated: stdout dropped 10 bytes"],
        triage={"triaged": False, "diagnostics": ["boom"]},
        triage_enabled=True,
        tail_text="child bytes\n",
    )
    err = capsys.readouterr().err
    assert "failed/3" in err
    assert "child bytes" in err
    assert "retained output truncated" in err
    assert "sase tool show abc123 -l" in err
    assert "triage unavailable: boom" in err

    write_run_footer(
        durable_id="abc123",
        state="failed",
        exit_code=3,
        duration_ms=1000,
        compact=False,
        tail_lines=200,
        stdout_sink=None,
        stderr_sink=None,
        stages=stages,
        truncation=[],
        triage={
            "triaged": True,
            "verdict": "new_failures",
            "items": [],
            "stages": [],
            "run_facts": {},
        },
        triage_enabled=True,
        tail_text="child bytes\n",
    )
    err = capsys.readouterr().err
    assert "exit=3" in err
    assert "verdict: new_failures; exit 3" in err
    assert "sase tool show" not in err
