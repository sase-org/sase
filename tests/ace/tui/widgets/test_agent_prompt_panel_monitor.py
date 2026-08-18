"""Tests for the MONITOR detail section and ANSI output rendering."""

from __future__ import annotations

from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from rich.console import Console, Group
from rich.text import Text

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from tests.ace.tui.widgets._agent_display_helpers import FakePromptPanel, plain_of


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
        monitor_idle_timeout_seconds=600.0,
        monitor_exit_code=exit_code,
        monitor_output_truncated=output_truncated,
    )


def _render(agent: Agent) -> object:
    panel = AgentPromptPanel.__new__(AgentPromptPanel)
    with patch.object(panel, "update") as mock_update:
        panel.update_display(agent)
    return mock_update.call_args.args[0]


def _iter_texts(renderable: object) -> list[Text]:
    if isinstance(renderable, Text):
        return [renderable]
    if isinstance(renderable, Group):
        texts: list[Text] = []
        for child in renderable.renderables:
            texts.extend(_iter_texts(child))
        return texts
    inner = getattr(renderable, "renderable", None)
    if inner is not None and inner is not renderable:
        return _iter_texts(inner)
    return []


def _family_with_monitor(
    tmp_path: Path,
    *,
    output: str | None = None,
    output_truncated: bool = False,
    workspace_dir: str | None = None,
) -> Agent:
    artifacts_dir: str | None = None
    if output is not None:
        mon_dir = tmp_path / "monitor-artifacts"
        mon_dir.mkdir()
        (mon_dir / "live_reply.md").write_text(output, encoding="utf-8")
        artifacts_dir = str(mon_dir)
    monitor = _monitor_agent(
        status="MONITORED",
        monitor_state="completed",
        exit_code=0,
        artifacts_dir=artifacts_dir,
        output_truncated=output_truncated,
    )
    if workspace_dir is not None:
        monitor.workspace_dir = workspace_dir
    started = datetime(2026, 8, 12, 8, 59, 0)
    root = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="code-family",
        project_file="/tmp/monitor.sase",
        status="DONE",
        status_bucket="Done",
        start_time=started,
        run_start_time=started,
        raw_suffix="20260812085900",
        agent_name="alpha--code",
        agent_family="alpha",
        agent_family_role="code",
        role_suffix="--code",
        plan_chain_root=True,
        followup_agents=[monitor],
    )
    monitor.family_container = root
    return root


def _starter_with_monitor(
    tmp_path: Path,
    *,
    output: str | None = None,
    output_truncated: bool = False,
) -> Agent:
    starter_dir = tmp_path / "starter-artifacts"
    starter_dir.mkdir()
    (starter_dir / "01_prompt.md").write_text(
        "Implement the feature.\n", encoding="utf-8"
    )
    artifacts_dir: str | None = None
    if output is not None:
        mon_dir = tmp_path / "monitor-artifacts"
        mon_dir.mkdir()
        (mon_dir / "live_reply.md").write_text(output, encoding="utf-8")
        artifacts_dir = str(mon_dir)
    monitor = _monitor_agent(
        status="MONITORED",
        monitor_state="completed",
        exit_code=0,
        artifacts_dir=artifacts_dir,
        output_truncated=output_truncated,
    )
    started = datetime(2026, 8, 12, 8, 59, 0)
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="code-starter",
        project_file="/tmp/monitor.sase",
        status="DONE",
        status_bucket="Done",
        start_time=started,
        run_start_time=started,
        raw_suffix="20260812085900",
        artifacts_dir=str(starter_dir),
        agent_name="alpha--code",
        agent_family="alpha",
        agent_family_role="code",
        role_suffix="--code",
        followup_agents=[monitor],
    )


def _assert_monitor_phase(
    text: str,
    *,
    expect_output: str | None = None,
    expect_truncated: bool = False,
    expect_no_output: bool = False,
) -> None:
    assert "MONITOR" in text
    assert "AGENT (monitor)" not in text
    assert "just check-full" in text
    assert "/home/bryan/sase" in text
    assert "Verify the refactor before replying" in text
    assert "completed" in text
    assert "exit 0" in text
    assert "sase monitor show m123ab --follow" in text
    if expect_output is not None:
        assert expect_output in text
    if expect_truncated:
        assert "truncated" in text.lower()
    if expect_no_output:
        assert "No output yet." in text


def _assert_failed_is_ansi_styled(rendered: object) -> None:
    combined = "\n".join(text.plain for text in _iter_texts(rendered))
    assert "FAILED" in combined
    assert "\x1b" not in combined
    styled = False
    for text in _iter_texts(rendered):
        if "FAILED" not in text.plain:
            continue
        for span in text.spans:
            if "FAILED" not in text.plain[span.start : span.end]:
                continue
            if span.style is not None and str(span.style) not in {"", "none"}:
                styled = True
    assert styled


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
    assert "10m0s without output" in text
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


def test_family_container_renders_monitor_phase_fields_and_log(tmp_path) -> None:
    log = "✓ lint (ruff)\nFAILED tests/ace/tui/test_x.py::test_y\n"
    rendered = _render(_family_with_monitor(tmp_path, output=log))
    text = "\n".join(_console_lines(rendered))

    _assert_monitor_phase(text, expect_output=log.strip())
    assert "⚙ MONITOR" in text or "MONITOR" in text


def test_starter_followup_renders_monitor_phase_fields_and_log(tmp_path) -> None:
    log = "✓ lint (ruff)\nFAILED tests/ace/tui/test_x.py::test_y\n"
    rendered = _render(_starter_with_monitor(tmp_path, output=log))
    text = "\n".join(_console_lines(rendered))

    _assert_monitor_phase(text, expect_output=log.strip())


def test_family_monitor_phase_decodes_ansi_and_drops_escapes(tmp_path) -> None:
    rendered = _render(
        _family_with_monitor(
            tmp_path,
            output="\x1b[31mFAILED\x1b[0m tests/x.py\n",
        )
    )
    text = "\n".join(_console_lines(rendered))

    assert "FAILED" in text
    assert "\x1b" not in text
    _assert_failed_is_ansi_styled(rendered)


def test_starter_monitor_phase_decodes_ansi_and_drops_escapes(tmp_path) -> None:
    rendered = _render(
        _starter_with_monitor(
            tmp_path,
            output="\x1b[31mFAILED\x1b[0m tests/x.py\n",
        )
    )
    text = "\n".join(_console_lines(rendered))

    assert "FAILED" in text
    assert "\x1b" not in text
    _assert_failed_is_ansi_styled(rendered)


def test_family_truncated_monitor_keeps_elision_notice(tmp_path) -> None:
    rendered = _render(
        _family_with_monitor(
            tmp_path,
            output="some output\n",
            output_truncated=True,
        )
    )
    text = "\n".join(_console_lines(rendered))

    _assert_monitor_phase(text, expect_output="some output", expect_truncated=True)


def test_starter_truncated_monitor_keeps_elision_notice(tmp_path) -> None:
    rendered = _render(
        _starter_with_monitor(
            tmp_path,
            output="some output\n",
            output_truncated=True,
        )
    )
    text = "\n".join(_console_lines(rendered))

    _assert_monitor_phase(text, expect_output="some output", expect_truncated=True)


def test_family_outputless_monitor_shows_placeholder(tmp_path) -> None:
    rendered = _render(_family_with_monitor(tmp_path))
    text = "\n".join(_console_lines(rendered))

    _assert_monitor_phase(text, expect_no_output=True)


def test_starter_outputless_monitor_shows_placeholder(tmp_path) -> None:
    rendered = _render(_starter_with_monitor(tmp_path))
    text = "\n".join(_console_lines(rendered))

    _assert_monitor_phase(text, expect_no_output=True)


def test_family_hint_mode_annotates_command_and_log_paths(tmp_path) -> None:
    workspace = tmp_path / "mon-workspace"
    log_path = workspace / "tests" / "ace" / "tui" / "test_x.py"
    log_path.parent.mkdir(parents=True)
    log_path.write_text("def test_y() -> None:\n    assert False\n", encoding="utf-8")
    root = _family_with_monitor(
        tmp_path,
        output="FAILED tests/ace/tui/test_x.py::test_y\n",
        workspace_dir=str(workspace),
    )
    panel = FakePromptPanel()

    result = panel.update_display_with_hints(root)
    plain = plain_of(panel.captured[-1])

    assert "just check-full" in plain
    assert "FAILED" in plain
    assert "AGENT (monitor)" not in plain
    assert any(
        str(log_path) == resolved or resolved.endswith("tests/ace/tui/test_x.py")
        for resolved in result.file_hints.values()
    )
    assert any(f"[{number}]" in plain for number in result.file_hints)


def test_standalone_monitor_hint_mode_renders_document_not_empty_prompt() -> None:
    panel = FakePromptPanel()

    panel.update_display_with_hints(_monitor_agent())
    plain = plain_of(panel.captured[-1])

    assert "MONITOR" in plain
    assert "just check-full" in plain
    assert "OUTPUT" in plain
    assert "No prompt file found." not in plain
