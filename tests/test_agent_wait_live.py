"""TTY live panel and settle-summary tests for ``sase agent wait``."""

from __future__ import annotations

import argparse
import os
import signal
from io import StringIO

import pytest
from rich.console import Console

from sase.agent.wait_watch import (
    WaitSettlement,
    WaitSettlementOutcome,
    WaitTick,
    classify_wait_targets,
    resolve_wait_targets,
)
from sase.agents._wait_live_rows import (
    build_wait_live_rows,
    terminal_blocker_warnings,
)
from sase.agents._wait_render_live import (
    WaitLiveDisplay,
    _render_wait_live_panel,
    render_wait_settle_panel,
    should_render_wait_live,
)
from sase.agents.cli_wait import _WaitSignalState, handle_agents_wait
from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentMetaWire,
    DoneMarkerWire,
    FamilyShellMonitorWire,
    FamilyShellWire,
    PendingQuestionMarkerWire,
    PlanPathMarkerWire,
    WaitingMarkerWire,
)


def _snapshot(*records: AgentArtifactRecordWire) -> AgentArtifactScanWire:
    return AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root="/tmp/sase/projects",
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=list(records),
    )


def _record(
    timestamp: str,
    *,
    name: str,
    pid: int | None = None,
    outcome: str | None = None,
    project_name: str = "sase",
    model: str | None = "grok",
    workspace_num: int | None = 12,
    waiting: WaitingMarkerWire | None = None,
    pending_question: PendingQuestionMarkerWire | None = None,
    plan_path: str | None = None,
    prompt: str | None = None,
    error: str | None = None,
    family_role: str | None = None,
    monitor_command: str | None = None,
    monitor_state: str | None = None,
    monitor_exit_code: int | None = None,
    monitor_start_status: str | None = None,
    monitor_stop_status: str | None = None,
    wait_for: list[str] | None = None,
) -> AgentArtifactRecordWire:
    done = None
    if outcome is not None:
        done_family_shell = (
            FamilyShellWire(
                kind="monitor",
                state=monitor_state,
                monitor=FamilyShellMonitorWire(exit_code=monitor_exit_code),
            )
            if monitor_state is not None or monitor_exit_code is not None
            else None
        )
        done = DoneMarkerWire(
            outcome=outcome,
            name=name,
            error=error,
            workspace_num=workspace_num,
            model=model,
            family_shell=done_family_shell,
            status_label=monitor_stop_status,
        )
    meta_family_shell = (
        FamilyShellWire(
            kind="monitor",
            state=monitor_state,
            start_status=monitor_start_status,
            stop_status=monitor_stop_status,
            monitor=FamilyShellMonitorWire(
                command=monitor_command, exit_code=monitor_exit_code
            ),
        )
        if any(
            value is not None
            for value in (
                monitor_command,
                monitor_state,
                monitor_exit_code,
                monitor_start_status,
                monitor_stop_status,
            )
        )
        else None
    )
    return AgentArtifactRecordWire(
        project_name=project_name,
        project_dir=f"/tmp/sase/projects/{project_name}",
        project_file=f"/tmp/sase/projects/{project_name}/{project_name}.gp",
        workflow_dir_name="ace-run",
        artifact_dir=(
            f"/tmp/sase/projects/{project_name}/artifacts/ace-run/{timestamp}"
        ),
        timestamp=timestamp,
        agent_meta=AgentMetaWire(
            name=name,
            pid=pid,
            model=model,
            workspace_num=workspace_num,
            run_started_at="2026-08-23T12:00:00Z" if pid is not None else None,
            wait_for=wait_for or [],
            agent_family_role=family_role,
            family_shell=meta_family_shell,
        ),
        done=done,
        waiting=waiting,
        pending_question=pending_question,
        plan_path=PlanPathMarkerWire(plan_path=plan_path) if plan_path else None,
        raw_prompt_snippet=prompt,
        has_done_marker=outcome is not None,
    )


def _tick(
    snapshot: AgentArtifactScanWire, *names: str, elapsed: float = 252.0
) -> WaitTick:
    targets = resolve_wait_targets(list(names), snapshot)
    states = classify_wait_targets(targets, snapshot)
    return WaitTick(index=0, elapsed_seconds=elapsed, target_states=states)


def _export(renderable: object) -> str:
    console = Console(
        file=StringIO(),
        record=True,
        width=120,
        color_system=None,
        force_terminal=True,
    )
    console.print(renderable)
    return console.export_text()


def _live_pid() -> int:
    return os.getpid()


def test_should_render_wait_live_only_for_interactive_stdout() -> None:
    assert should_render_wait_live(as_json=False, quiet=False, stdout_isatty=True)
    assert not should_render_wait_live(as_json=False, quiet=False, stdout_isatty=False)
    assert not should_render_wait_live(as_json=True, quiet=False, stdout_isatty=True)
    assert not should_render_wait_live(as_json=False, quiet=True, stdout_isatty=True)
    assert should_render_wait_live(
        as_json=False, quiet=False, use_live=True, stdout_isatty=False
    )


def test_live_rows_sort_unfinished_above_finished() -> None:
    snapshot = _snapshot(
        _record("20260823120000", name="done-agent", outcome="completed"),
        _record("20260823120001", name="still-running", pid=_live_pid()),
    )
    tick = _tick(snapshot, "done-agent", "still-running")
    rows = build_wait_live_rows(
        tick.target_states, snapshot, elapsed_seconds=tick.elapsed_seconds
    )

    assert [row.name for row in rows] == ["still-running", "done-agent"]


def test_why_column_for_waiting_queued_monitor_and_prompt() -> None:
    snapshot = _snapshot(
        _record(
            "20260823120000",
            name="runner",
            pid=_live_pid(),
            prompt="#gh:sase add the wait command",
            model="opus",
        ),
        _record(
            "20260823120001",
            name="waiter",
            pid=_live_pid(),
            waiting=WaitingMarkerWire(waiting_for=["runner"]),
        ),
        _record(
            "20260823120002",
            name="queued-a",
            pid=_live_pid(),
            waiting=WaitingMarkerWire(slot_requested_at="2026-08-23T12:00:01Z"),
        ),
        _record(
            "20260823120003",
            name="queued-b",
            pid=_live_pid(),
            waiting=WaitingMarkerWire(slot_requested_at="2026-08-23T12:00:02Z"),
        ),
        _record(
            "20260823120004",
            name="queued-c",
            pid=_live_pid(),
            waiting=WaitingMarkerWire(slot_requested_at="2026-08-23T12:00:03Z"),
        ),
        _record(
            "20260823120005",
            name="mon",
            pid=_live_pid(),
            outcome="monitored",
            family_role="monitor",
            monitor_command="just check-full",
            monitor_state="completed",
            monitor_exit_code=0,
            monitor_start_status="TESTING",
            monitor_stop_status="TESTED",
        ),
    )
    tick = _tick(snapshot, "runner", "waiter", "queued-b", "mon", elapsed=252.0)
    text = _export(_render_wait_live_panel(tick, snapshot))

    assert "runner" in text
    assert "add the wait command" in text
    assert "waits on runner" in text
    assert "slot 2 of 3" in text
    assert "TESTED" in text
    assert "exit 0" in text
    assert "Waiting on 4 agents" in text
    assert "04:12 elapsed" in text


def test_why_column_for_blocked_pending_states() -> None:
    snapshot = _snapshot(
        _record(
            "20260823120000",
            name="asker",
            pending_question=PendingQuestionMarkerWire(session_id="q1"),
        ),
        _record(
            "20260823120001",
            name="planner",
            plan_path="/tmp/plan.md",
        ),
        _record("20260823120002", name="dead"),
    )
    tick = _tick(snapshot, "asker", "planner", "dead")
    rows = {
        row.name: row
        for row in build_wait_live_rows(
            tick.target_states, snapshot, elapsed_seconds=30.0
        )
    }

    assert rows["asker"].why == "pending question"
    assert rows["asker"].status == "QUESTION"
    assert rows["planner"].why == "plan awaits review"
    assert rows["planner"].status == "PLAN"
    assert rows["dead"].why == "process exited without done"
    assert rows["dead"].status == "STALLED"


def test_terminal_blocker_warning_when_dependency_failed() -> None:
    snapshot = _snapshot(
        _record("20260823120000", name="sase-s7.1", outcome="failed"),
        _record(
            "20260823120001",
            name="sase-s7.3",
            pid=_live_pid(),
            waiting=WaitingMarkerWire(waiting_for=["sase-s7.1"]),
        ),
    )
    tick = _tick(snapshot, "sase-s7.3")
    warnings = terminal_blocker_warnings(tick.target_states, snapshot)
    text = _export(_render_wait_live_panel(tick, snapshot))

    assert warnings == (
        "sase-s7.3 waits on sase-s7.1, which FAILED — it will not start",
    )
    assert "⚠ sase-s7.3 waits on sase-s7.1, which FAILED" in text
    assert "it will not start" in text


def test_settle_summary_mixed_outcomes_include_inspect_pointers() -> None:
    snapshot = _snapshot(
        _record("20260823120000", name="0bd", outcome="completed", workspace_num=12),
        _record(
            "20260823120001",
            name="sase-s7.3",
            outcome="failed",
            error="provider error: context window exceeded",
            workspace_num=4,
            project_name="bob-cli",
            model="sonnet",
        ),
    )
    tick = _tick(snapshot, "0bd", "sase-s7.3", elapsed=724.0)
    settlement = WaitSettlement(
        outcome=WaitSettlementOutcome.FAILED,
        target_states=tick.target_states,
        elapsed_seconds=724.0,
        exit_code=1,
    )
    text = _export(render_wait_settle_panel(settlement, snapshot, exit_code=1))

    assert "Waited 12m4s" in text
    assert "0bd" in text
    assert "sase-s7.3" in text
    assert "FAILED" in text
    assert "provider error: context window exceeded" in text
    assert "sase agent show sase-s7.3" in text
    assert "sase chat sase-s7.3" in text
    assert "exit 1" in text
    assert "bob-cli" in text
    assert "ws4" in text


def test_settle_summary_blocked_target_prints_unblock_command() -> None:
    snapshot = _snapshot(
        _record(
            "20260823120000",
            name="planner",
            plan_path="/tmp/plan.md",
            workspace_num=3,
        )
    )
    tick = _tick(snapshot, "planner")
    settlement = WaitSettlement(
        outcome=WaitSettlementOutcome.BLOCKED,
        target_states=tick.target_states,
        elapsed_seconds=60.0,
        exit_code=3,
    )
    text = _export(render_wait_settle_panel(settlement, snapshot, exit_code=3))

    assert "plan awaits review" in text
    assert "sase plan approve" in text
    assert "sase agent show planner" in text
    assert "exit 3" in text


def test_project_column_uses_display_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.agents._wait_live_rows.project_display_name_for",
        lambda key, *args, **kwargs: "sase" if key == "gh_sase-org__sase" else key,
    )
    snapshot = _snapshot(
        _record(
            "20260823120000",
            name="runner",
            pid=_live_pid(),
            project_name="gh_sase-org__sase",
        )
    )
    tick = _tick(snapshot, "runner")
    text = _export(_render_wait_live_panel(tick, snapshot))

    assert "sase" in text
    assert "gh_sase-org__sase" not in text


def test_live_display_teardown_clears_live_context() -> None:
    snapshot = _snapshot(_record("20260823120000", name="runner", pid=_live_pid()))
    tick = _tick(snapshot, "runner")
    console = Console(
        file=StringIO(),
        record=True,
        width=100,
        force_terminal=True,
        color_system=None,
    )
    with WaitLiveDisplay(console) as display:
        display.update(tick, snapshot)
    display.update(tick, snapshot)


def _no_sleep(seconds: float) -> None:
    raise AssertionError(f"must not sleep, slept {seconds}")


def _args(names: list[str]) -> argparse.Namespace:
    return argparse.Namespace(
        names=names,
        all=False,
        project=None,
        json=False,
        quiet=False,
        wait_blocked=False,
        interval=None,
        timeout=None,
    )


def test_handle_agents_wait_live_interrupt_prints_summary_and_exits_130() -> None:
    snapshot = _snapshot(_record("20260823120000", name="runner", pid=_live_pid()))
    state = _WaitSignalState()
    state.signum = signal.SIGINT
    console = Console(
        file=StringIO(),
        record=True,
        width=120,
        force_terminal=True,
        color_system=None,
    )

    rc = handle_agents_wait(
        _args(["runner"]),
        snapshot_provider=lambda: snapshot,
        install_signal_handlers=False,
        signal_state=state,
        sleep=lambda _seconds: None,
        use_live=True,
        live_console=console,
    )

    text = console.export_text()
    assert rc == 130
    assert "runner" in text
    assert "exit 130" in text


def test_handle_agents_wait_live_quiet_still_prints_one_liner(
    capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot = _snapshot(_record("20260823120000", name="good", outcome="completed"))

    rc = handle_agents_wait(
        argparse.Namespace(
            names=["good"],
            all=False,
            project=None,
            json=False,
            quiet=True,
            wait_blocked=False,
            interval=None,
            timeout=None,
        ),
        snapshot_provider=lambda: snapshot,
        install_signal_handlers=False,
        sleep=_no_sleep,
        use_live=True,
    )

    assert rc == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.strip().startswith("settled:")
