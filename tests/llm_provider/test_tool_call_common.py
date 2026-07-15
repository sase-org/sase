from __future__ import annotations

import pytest

from sase.llm_provider._tool_call_common import (
    COMMAND_OUTPUT_MIN_TAIL_LINES,
    summarize_tool_input,
    summarize_tool_response,
    tail_command_output,
)


def _numbered_lines(count: int, *, trailing_newline: bool) -> str:
    text = "\n".join(f"line-{index:03d}-payload" for index in range(count))
    return f"{text}\n" if trailing_newline else text


def test_tail_command_output_keeps_short_and_exact_budget_text() -> None:
    assert tail_command_output("", 4) == ""
    assert tail_command_output("abc", 4) == "abc"
    assert tail_command_output("a\r\nb\r", 4) == "a\nb\n"


@pytest.mark.parametrize("line_count", [49, 50])
@pytest.mark.parametrize("trailing_newline", [False, True])
def test_tail_command_output_keeps_all_output_with_at_most_minimum_lines(
    line_count: int,
    trailing_newline: bool,
) -> None:
    text = _numbered_lines(line_count, trailing_newline=trailing_newline)

    result = tail_command_output(text.replace("\n", "\r\n"), 32)

    assert result == text


@pytest.mark.parametrize("trailing_newline", [False, True])
def test_tail_command_output_retains_complete_final_fifty_lines(
    trailing_newline: bool,
) -> None:
    text = _numbered_lines(51, trailing_newline=trailing_newline)
    first_line, retained = text.split("\n", 1)

    result = tail_command_output(text, 32)
    marker, output_tail = result.split("\n", 1)

    assert first_line not in output_tail
    assert output_tail == retained
    assert "from the beginning" in marker
    assert "1 line" in marker
    assert output_tail.endswith("\n") is trailing_newline
    assert len(output_tail.splitlines()) == COMMAND_OUTPUT_MIN_TAIL_LINES


def test_tail_command_output_retains_final_sentinel_beyond_soft_budget() -> None:
    text = _numbered_lines(80, trailing_newline=True) + "FINAL FAILURE\n"

    result = tail_command_output(text, 128)

    assert result.startswith("...[truncated ")
    assert "from the beginning]" in result.splitlines()[0]
    assert "line-000-payload" not in result
    assert "FINAL FAILURE" in result
    assert len(result.splitlines()[1:]) >= COMMAND_OUTPUT_MIN_TAIL_LINES


def test_tail_command_output_is_idempotent() -> None:
    text = _numbered_lines(80, trailing_newline=True)

    result = tail_command_output(text, 128)

    assert tail_command_output(result, 128) == result


def test_only_command_output_fields_use_tail_policy() -> None:
    long_output = _numbered_lines(80, trailing_newline=True)
    long_content = "content-start-" + ("x" * 700) + "-content-end"

    summary = summarize_tool_response(
        None,
        {
            "stdout": long_output,
            "content": long_content,
        },
    )
    tool_input = summarize_tool_input("Bash", {"command": long_content})

    assert "line-000-payload" not in summary["stdout_preview"]
    assert "line-079-payload" in summary["stdout_preview"]
    assert summary["content_preview"].startswith("content-start-")
    assert "content-end" not in summary["content_preview"]
    assert tool_input["command"].startswith("content-start-")
    assert "content-end" not in tool_input["command"]


def test_subagent_full_content_remains_head_oriented() -> None:
    content = "subagent-start-" + ("x" * (70 * 1024)) + "-subagent-end"

    summary = summarize_tool_response(
        "Agent",
        {
            "agentId": "agent-1",
            "content": content,
        },
    )

    assert summary["content_full"].startswith("subagent-start-")
    assert "subagent-end" not in summary["content_full"]
