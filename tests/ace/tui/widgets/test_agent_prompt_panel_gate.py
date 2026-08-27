"""Tests for the GATE detail section and ANSI output rendering."""

from __future__ import annotations

from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from rich.console import Console, Group
from rich.text import Text

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.ace.tui.widgets.prompt_panel._agent_gate_section import build_gate_phase


def _console_lines(rendered: object, *, width: int = 120) -> list[str]:
    output = StringIO()
    Console(file=output, width=width, color_system=None).print(rendered, end="")
    return output.getvalue().splitlines()


def _gate_agent(
    tmp_path: Path,
    *,
    status: str = "APPROVE",
    gate_state: str = "pending",
    output: str | None = None,
    output_truncated: bool = False,
) -> Agent:
    started = datetime(2026, 8, 12, 9, 0, 0)
    output_path: str | None = None
    if output is not None:
        path = tmp_path / "gate.log"
        path.write_text(output, encoding="utf-8")
        output_path = str(path)
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="gate-row",
        project_file="/tmp/gate.sase",
        status=status,
        status_bucket="Running" if gate_state == "settling" else "Stopped",
        start_time=started,
        run_start_time=started,
        raw_suffix="20260812090000",
        parent_timestamp="20260812085900",
        agent_name="alpha--gate",
        agent_family="alpha",
        agent_family_role="gate",
        role_suffix="--gate",
        gate_id="g123abc456def",
        gate_kind="approval",
        gate_state=gate_state,
        gate_start_status="APPROVE",
        gate_stop_status="APPROVED",
        gate_accent="#0BCDEC",
        gate_label="Approve deploy",
        gate_reason="Release needs confirmation",
        gate_timeout_seconds=2700.0,
        gate_output_path=output_path,
        gate_output_truncated=output_truncated,
        gate_next_action="Continue the deployment.",
        gate_followup_outcome="not-launchable" if gate_state == "failed" else None,
        gate_followup_error="No branch selected" if gate_state == "failed" else None,
    )


def _render(agent: Agent) -> object:
    panel = AgentPromptPanel.__new__(AgentPromptPanel)
    with patch.object(panel, "update") as mock_update:
        panel.update_display(agent)
    return mock_update.call_args.args[0]


def _annotate(value: str | Text) -> Text:
    return value if isinstance(value, Text) else Text(value)


def _gate_phase_text(agent: Agent) -> Text:
    result = Text(end="")
    for part in build_gate_phase(agent, annotate=_annotate):
        assert isinstance(part, Text)
        result.append_text(part)
    return result


def test_gate_row_renders_gate_section_fields(tmp_path: Path) -> None:
    rendered = _render(_gate_agent(tmp_path))

    assert isinstance(rendered, Group)
    text = "\n".join(_console_lines(rendered))

    assert "GATE" in text
    assert "Approve deploy" in text
    assert "approval" in text
    assert "APPROVE" in text
    assert "APPROVED" in text
    assert "pending" in text
    assert "Release needs confirmation" in text
    assert "Continue the deployment." in text
    assert "g123abc456def" in text
    assert "sase gate show" in text
    assert "AGENT PROMPT" not in text
    assert "AGENT REPLY" not in text


def test_gate_row_no_output_shows_placeholder(tmp_path: Path) -> None:
    rendered = _render(_gate_agent(tmp_path))
    text = "\n".join(_console_lines(rendered))

    assert "OUTPUT" in text
    assert "No output yet." in text


def test_gate_row_renders_output_as_ansi_not_markdown(tmp_path: Path) -> None:
    rendered = _render(
        _gate_agent(
            tmp_path,
            output="line one\n**not markdown** `still not markdown`\n",
            output_truncated=True,
        )
    )
    text = "\n".join(_console_lines(rendered))

    assert "OUTPUT" in text
    assert "truncated" in text.lower()
    assert "**not markdown**" in text
    assert "`still not markdown`" in text


def test_gate_phase_text_flattens_family_phase(tmp_path: Path) -> None:
    agent = _gate_agent(
        tmp_path,
        status="APPROVED",
        gate_state="answered",
        output="selected approve\n",
    )

    text = _gate_phase_text(agent).plain

    assert "GATE" in text
    assert "APPROVE" in text
    assert "APPROVED" in text
    assert "answered" in text
    assert "Output:" in text
    assert "selected approve" in text
