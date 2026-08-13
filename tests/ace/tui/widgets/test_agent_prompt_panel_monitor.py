"""Tests for the MONITOR detail section and ANSI output rendering."""

from __future__ import annotations

from datetime import datetime
from io import StringIO
from unittest.mock import patch

from rich.console import Console, Group

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel


def _console_lines(rendered: object, *, width: int = 120) -> list[str]:
    output = StringIO()
    Console(file=output, width=width, color_system=None).print(rendered, end="")
    return output.getvalue().splitlines()


def _monitor_agent(
    *,
    status: str = "MONITORING",
    monitor_state: str = "running",
    exit_code: int | None = None,
    artifacts_dir: str | None = None,
    output_truncated: bool = False,
) -> Agent:
    started = datetime(2026, 8, 12, 9, 0, 0)
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="monitor-row",
        project_file="/tmp/monitor.sase",
        status=status,
        status_bucket="Running" if monitor_state == "running" else "Done",
        start_time=started,
        run_start_time=started,
        raw_suffix="20260812090000",
        parent_timestamp="20260812085900",
        agent_name="alpha--mon",
        agent_family="alpha",
        agent_family_role="monitor",
        role_suffix="--mon",
        artifacts_dir=artifacts_dir,
        monitor_id="m123abc456def",
        monitor_state=monitor_state,
        monitor_label="just check",
        monitor_command="just check-full",
        monitor_cwd="/home/bryan/sase",
        monitor_reason="Verify the refactor before replying",
        monitor_next_action="Reply to the user.",
        monitor_timeout_seconds=2700.0,
        monitor_exit_code=exit_code,
        monitor_output_truncated=output_truncated,
    )


def _render(agent: Agent) -> object:
    panel = AgentPromptPanel.__new__(AgentPromptPanel)
    with patch.object(panel, "update") as mock_update:
        panel.update_display(agent)
    return mock_update.call_args.args[0]


def test_monitor_row_renders_monitor_section_fields() -> None:
    rendered = _render(_monitor_agent())

    assert isinstance(rendered, Group)
    lines = _console_lines(rendered)
    text = "\n".join(lines)

    assert "MONITOR" in text
    assert "just check-full" in text
    assert "/home/bryan/sase" in text
    assert "Verify the refactor before replying" in text
    assert "Reply to the user." in text
    assert "running" in text
    assert "m123abc456def" in text
    assert "sase monitor show m123ab --follow" in text
    assert "AGENT PROMPT" not in text
    assert "AGENT REPLY" not in text


def test_monitor_row_shows_exit_code_and_timeout_budget() -> None:
    rendered = _render(
        _monitor_agent(status="MONITORED", monitor_state="failed", exit_code=1)
    )
    text = "\n".join(_console_lines(rendered))

    assert "exit 1" in text
    assert "of 45m0s budget" in text


def test_monitor_row_no_output_shows_placeholder() -> None:
    rendered = _render(_monitor_agent())
    text = "\n".join(_console_lines(rendered))

    assert "OUTPUT" in text
    assert "No output yet." in text


def test_monitor_row_renders_output_as_ansi_not_markdown(tmp_path) -> None:
    live_reply = tmp_path / "live_reply.md"
    live_reply.write_text("line one\n**not markdown** `still not markdown`\n")

    rendered = _render(_monitor_agent(artifacts_dir=str(tmp_path)))
    text = "\n".join(_console_lines(rendered))

    assert "OUTPUT" in text
    assert "**not markdown**" in text
    assert "`still not markdown`" in text


def test_monitor_row_truncated_output_shows_elision_notice(tmp_path) -> None:
    live_reply = tmp_path / "live_reply.md"
    live_reply.write_text("some output\n")

    rendered = _render(
        _monitor_agent(artifacts_dir=str(tmp_path), output_truncated=True)
    )
    text = "\n".join(_console_lines(rendered))

    assert "truncated" in text.lower()
