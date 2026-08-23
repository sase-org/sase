"""Proc-shell prompt-panel section rendering."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._agent_proc_shell_section import (
    build_proc_shell_preview,
    build_proc_shell_section,
)


def _agent(
    *,
    status: str = "RUNNING",
    proc_status: str = "running",
    proc_phase: str = "running",
) -> Agent:
    return Agent(
        agent_type=AgentType.PROC_SHELL,
        cl_name="sase",
        project_file="",
        status=status,
        start_time=datetime(2026, 8, 20, 12, 0, 0),
        raw_suffix="abc123def456",
        agent_name="abc123",
        monitor_command="/bin/bash --noprofile --norc /tmp/script.sh",
        monitor_timeout_seconds=600,
        monitor_idle_timeout_seconds=120,
        monitor_exit_code=0,
        proc_id="abc123def456",
        proc_status=proc_status,
        proc_phase=proc_phase,
        proc_label="Build docs",
        proc_origin="xprompt-proc",
        proc_language="bash",
        proc_code_digest="sha256:code",
        proc_safe_preview="just check",
        proc_log_path="/tmp/abc123def456.log",
        proc_waits=["bead: sase-s6.7"],
        proc_condition_result="passed: cache warm",
        proc_supervisor_id="supervisor-1",
        proc_settlement_state="settled by supervisor",
        proc_request_fingerprint="sha256:request",
    )


def _annotate(value: str | Text) -> Text:
    return value if isinstance(value, Text) else Text(value)


def _plain(parts: list[object]) -> str:
    rendered: list[str] = []
    for part in parts:
        if isinstance(part, Text):
            rendered.append(part.plain)
        else:
            rendered.append(str(part))
    return "".join(rendered)


def test_proc_shell_details_hide_diagnostics_at_default_fold() -> None:
    plain = _plain(
        build_proc_shell_section(
            _agent(),
            panel_level=FoldLevel.COLLAPSED,
            annotate=_annotate,
        )
    )

    assert "PROC DETAILS · +6 diagnostics" in plain
    assert "Status:" in plain
    assert "Language:" in plain
    assert "Phase:" in plain
    assert "Timeout:" in plain
    assert "Idle timeout:" in plain
    assert "Waits:" in plain
    assert "Condition:" in plain
    assert "Proc id:" in plain
    assert "Log path:" in plain
    assert "Label:" not in plain
    assert "Origin:" not in plain
    assert "Digest:" not in plain
    assert "Fingerprint:" not in plain
    assert "Supervisor:" not in plain
    assert "Settlement:" not in plain
    assert "Runtime argv:" not in plain
    assert "Command:" not in plain


def test_proc_shell_details_omit_stale_terminal_phase() -> None:
    plain = _plain(
        build_proc_shell_section(
            _agent(status="DONE", proc_status="success", proc_phase="running"),
            panel_level=FoldLevel.COLLAPSED,
            annotate=_annotate,
        )
    )

    assert "Status:" in plain
    assert "Phase:" not in plain


def test_proc_shell_details_show_diagnostics_when_fully_expanded() -> None:
    plain = _plain(
        build_proc_shell_section(
            _agent(),
            panel_level=FoldLevel.FULLY_EXPANDED,
            annotate=_annotate,
        )
    )

    assert "+6 diagnostics" not in plain
    assert "Origin:" in plain
    assert "Digest:" in plain
    assert "Fingerprint:" in plain
    assert "Supervisor:" in plain
    assert "Settlement:" in plain
    assert "Runtime argv:" in plain
    assert "/bin/bash --noprofile --norc /tmp/script.sh" in plain


def test_proc_shell_command_preview_heading() -> None:
    preview = _plain(build_proc_shell_preview(_agent(), annotate=_annotate))
    detail = _plain(
        build_proc_shell_section(
            _agent(),
            panel_level=FoldLevel.COLLAPSED,
            annotate=_annotate,
        )
    )

    combined = preview + detail
    assert "COMMAND" in preview
    assert "SAFE PREVIEW" not in preview
    assert combined.index("COMMAND") < combined.index("PROC DETAILS")
