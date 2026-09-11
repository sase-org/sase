"""Tests for realtime and JSON rendering of ``sase axe restart``."""

from __future__ import annotations

import json
from io import StringIO

from rich.console import Console

from sase.axe import restart_render
from sase.axe.process import (
    AxeStartAttempt,
    AxeStartResult,
    AxeStopResult,
    RestartFinished,
    RestartPlanned,
    RetryScheduled,
    StartAttemptBegan,
    StartAttemptSettled,
    StartAttemptSpawned,
    StopBegan,
    StopFinished,
    VerifyProgress,
)
from sase.axe.restart_render import (
    RestartPlainRenderer,
    render_restart_json,
    render_restart_settle_panel,
    should_render_restart_live,
)


def _console(*, width: int = 100) -> tuple[Console, StringIO]:
    output = StringIO()
    console = Console(file=output, width=width, force_terminal=False, color_system=None)
    return console, output


def _plain_lines(events: list[object]) -> list[str]:
    console, output = _console()
    renderer = RestartPlainRenderer(console)
    for event in events:
        renderer.handle_event(event)  # type: ignore[arg-type]
    return [line for line in output.getvalue().splitlines() if line]


def test_should_render_restart_live_gating() -> None:
    assert should_render_restart_live(as_json=True, stdout_isatty=True) is False
    assert should_render_restart_live(as_json=False, stdout_isatty=True) is True
    assert should_render_restart_live(as_json=False, stdout_isatty=False) is False


def test_plain_renderer_prints_stop_started_verify_and_finish_lines() -> None:
    events = [
        RestartPlanned(lumberjacks=("agents", "hooks"), max_attempts=3),
        StopBegan(),
        StopFinished(
            result=AxeStopResult(
                orchestrator_pid=41213,
                orchestrator_signaled=True,
                orchestrator_stopped=True,
                lumberjacks_stopped=2,
            ),
            elapsed_seconds=1.2,
        ),
        StartAttemptBegan(number=1, max_attempts=3),
        StartAttemptSpawned(number=1, status="started", pid=41890, message="started"),
        VerifyProgress(
            number=1,
            fresh=("agents",),
            pending=("hooks",),
            elapsed_seconds=0.1,
            timeout_seconds=15.0,
        ),
        VerifyProgress(
            number=1,
            fresh=("agents", "hooks"),
            pending=(),
            elapsed_seconds=0.2,
            timeout_seconds=15.0,
        ),
        StartAttemptSettled(
            attempt=AxeStartAttempt(
                number=1, status="started", pid=41890, verified=True
            )
        ),
        RestartFinished(
            result=AxeStartResult(
                status="started", pid=41890, message="ok", verified=True
            ),
            elapsed_seconds=6.3,
        ),
    ]

    lines = _plain_lines(events)

    assert lines[0] == "Stopping AXE…"
    assert lines[1] == "Stopped orchestrator (pid 41213) + 2 lumberjack(s) in 1.2s"
    assert lines[2] == "Starting AXE (attempt 1/3)…"
    assert lines[3] == "Started orchestrator (pid 41890)"
    assert lines[4] == "Verifying 2 lumberjack heartbeats (timeout 15s)…"
    assert lines[5] == "  agents fresh"
    assert lines[6] == "  hooks fresh"
    assert lines[-1] == "AXE restarted and verified (pid 41890) in 6.3s"


def test_plain_renderer_prints_skipped_stop_when_axe_was_not_running() -> None:
    events = [
        RestartPlanned(lumberjacks=(), max_attempts=3),
        StopBegan(),
        StopFinished(result=AxeStopResult(), elapsed_seconds=0.0),
        StartAttemptBegan(number=1, max_attempts=3),
        StartAttemptSpawned(number=1, status="started", pid=99, message="started"),
        RestartFinished(
            result=AxeStartResult(
                status="started", pid=99, message="ok", verified=True
            ),
            elapsed_seconds=1.0,
        ),
    ]

    lines = _plain_lines(events)

    assert lines[0] == "Stopping AXE…"
    assert lines[1] == "AXE was not running — nothing to stop"
    assert lines[2] == "Starting AXE (attempt 1/3)…"
    assert lines[3] == "Started orchestrator (pid 99)"
    assert lines[-1] == "AXE restarted and verified (pid 99) in 1.0s"


def test_plain_renderer_prints_retry_and_failure_lines() -> None:
    events = [
        RestartPlanned(lumberjacks=("hooks",), max_attempts=2),
        StopBegan(),
        StopFinished(result=AxeStopResult(), elapsed_seconds=0.0),
        StartAttemptBegan(number=1, max_attempts=2),
        StartAttemptSpawned(
            number=1, status="failed", pid=None, message="spawn failed"
        ),
        StartAttemptSettled(
            attempt=AxeStartAttempt(number=1, status="failed", message="spawn failed")
        ),
        RetryScheduled(next_number=2, delay_seconds=0.25),
        StartAttemptBegan(number=2, max_attempts=2),
        StartAttemptSpawned(
            number=2, status="failed", pid=None, message="spawn failed again"
        ),
        StartAttemptSettled(
            attempt=AxeStartAttempt(
                number=2, status="failed", message="spawn failed again"
            )
        ),
        RestartFinished(
            result=AxeStartResult(
                status="failed", message="Axe restart failed after 2 attempt(s)."
            ),
            elapsed_seconds=2.0,
        ),
    ]

    lines = _plain_lines(events)

    assert "Attempt 1 failed to start: spawn failed" in lines
    assert "Attempt 1 failed; retrying in 0.25s…" in lines
    assert "Attempt 2 failed to start: spawn failed again" in lines
    assert lines[-2] == "Axe restart failed after 2 attempt(s)."
    assert lines[-1] == "AXE may be down. Run `sase axe status` or `sase axe ensure`."


def test_settle_panel_success_variant_is_green_and_lists_lumberjacks() -> None:
    state = restart_render._RestartLiveState(lumberjacks=("agents", "hooks"))
    result = AxeStartResult(status="started", pid=41890, message="ok", verified=True)

    panel = render_restart_settle_panel(result, state, elapsed_seconds=6.3)

    assert panel.border_style == "green"
    assert panel.title == "AXE restarted"
    text = panel.renderable.plain  # type: ignore[union-attr]
    assert "41890" in text
    assert "agents, hooks" in text
    assert "6.3s" in text


def test_settle_panel_failure_variant_is_red_and_lists_attempts_and_hints() -> None:
    state = restart_render._RestartLiveState(lumberjacks=("hooks",))
    result = AxeStartResult(
        status="failed",
        message="Axe restart failed after 3 attempt(s): timed out",
        attempts=(
            AxeStartAttempt(number=1, status="blocked", message="lock held"),
            AxeStartAttempt(number=2, status="failed", message="spawn failed"),
            AxeStartAttempt(
                number=3, status="started", pid=1, verification_error="timed out"
            ),
        ),
    )

    panel = render_restart_settle_panel(result, state, elapsed_seconds=9.9)

    assert panel.border_style == "red"
    assert panel.title == "AXE restart failed"
    text = panel.renderable.plain  # type: ignore[union-attr]
    assert "Attempt 1: lock held" in text
    assert "Attempt 2: spawn failed" in text
    assert "Attempt 3: timed out" in text
    assert "sase axe status" in text
    assert "sase axe ensure" in text


def test_live_panel_renders_stop_start_and_verify_rows() -> None:
    state = restart_render._RestartLiveState(
        lumberjacks=("agents", "hooks"),
        max_attempts=3,
        attempt_number=1,
        stop_result=AxeStopResult(
            orchestrator_pid=41213,
            orchestrator_signaled=True,
            orchestrator_stopped=True,
            lumberjacks_stopped=1,
        ),
        stop_elapsed=1.2,
        start_status="started",
        start_pid=41890,
        verify_fresh=("agents",),
        verify_pending=("hooks",),
        verify_elapsed=2.1,
        verify_timeout=15.0,
    )

    panel = restart_render._render_restart_live_panel(state, elapsed_seconds=4.0)

    console, output = _console()
    console.print(panel)
    text = output.getvalue()
    assert "attempt 1/3" in text
    assert "0:04" in text
    assert "Stopped orchestrator (pid 41213) + 1 lumberjack(s)" in text
    assert "Started orchestrator (pid 41890)" in text
    assert "1/2 fresh" in text
    assert "agents" in text and "fresh" in text
    assert "hooks" in text and "waiting…" in text


def test_live_panel_renders_skipped_stop_when_axe_was_not_running() -> None:
    state = restart_render._RestartLiveState(
        lumberjacks=(), max_attempts=3, stop_result=AxeStopResult()
    )

    panel = restart_render._render_restart_live_panel(state, elapsed_seconds=0.0)

    console, output = _console()
    console.print(panel)
    assert "AXE was not running — nothing to stop" in output.getvalue()


def test_render_restart_json_is_deterministic_and_schema_shaped() -> None:
    result = AxeStartResult(
        status="started",
        pid=41890,
        message="Axe restarted and verified (pid 41890).",
        verified=True,
        attempts=(
            AxeStartAttempt(number=1, status="started", pid=41890, verified=True),
        ),
    )
    first = StringIO()
    second = StringIO()

    render_restart_json(result, 6.3, stream=first)
    render_restart_json(result, 6.3, stream=second)

    assert first.getvalue() == second.getvalue()
    payload = json.loads(first.getvalue())
    assert payload == {
        "schema_version": 1,
        "status": "started",
        "pid": 41890,
        "message": "Axe restarted and verified (pid 41890).",
        "verified": True,
        "elapsed_seconds": 6.3,
        "attempts": [
            {
                "number": 1,
                "status": "started",
                "pid": 41890,
                "message": "",
                "verified": True,
                "verification_error": None,
            }
        ],
    }
    assert first.getvalue().endswith("\n")
