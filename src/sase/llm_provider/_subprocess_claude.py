"""Claude Code stream-json subprocess parsing."""

import json
import subprocess
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, IO

from ._subprocess_artifacts import (
    append_stream_text,
    initial_usage_totals,
    open_codex_thinking_file,
    open_live_reply_file,
    open_live_reply_timestamps_file,
    write_usage_artifact,
)
from ._subprocess_diagnostics import record_stdout_json_decode_diagnostic
from ._subprocess_stream import append_error_events, stream_json_lines
from ._tool_calls import append_claude_tool_call_event

ToolCallWriter = Callable[[Mapping[str, Any]], None]
ThinkingSink = Callable[[Mapping[str, Any], Mapping[str, Any], IO[str]], None]
ThinkingSinkOption = ThinkingSink | bool | None


def stream_and_parse_json_output(
    process: subprocess.Popen[str],
    suppress_output: bool = False,
) -> tuple[str, str, int, dict[str, int]]:
    """Stream stdout as JSON events and extract assistant text.

    Reads ``--output-format stream-json`` output from Claude Code, extracting
    text content from ``assistant`` events so that the full conversation is
    captured even when stop hooks inject extra turns.
    """
    return _stream_and_parse_messages_json_output(
        process,
        suppress_output=suppress_output,
    )


def stream_and_parse_messages_json_output(
    process: subprocess.Popen[str],
    suppress_output: bool = False,
    *,
    runtime: str = "claude",
    tool_call_writer: ToolCallWriter = append_claude_tool_call_event,
    thinking_sink: ThinkingSinkOption = None,
) -> tuple[str, str, int, dict[str, int]]:
    """Stream Anthropic Messages JSON events for Claude-compatible CLIs."""
    return _stream_and_parse_messages_json_output(
        process,
        suppress_output=suppress_output,
        runtime=runtime,
        tool_call_writer=tool_call_writer,
        thinking_sink=thinking_sink,
    )


def _stream_and_parse_messages_json_output(
    process: subprocess.Popen[str],
    suppress_output: bool = False,
    *,
    runtime: str = "claude",
    tool_call_writer: ToolCallWriter = append_claude_tool_call_event,
    thinking_sink: ThinkingSinkOption = None,
) -> tuple[str, str, int, dict[str, int]]:
    """Stream Anthropic Messages JSON events and extract assistant text."""
    assistant_texts: list[str] = []
    error_events: list[str] = []
    usage_totals = initial_usage_totals()
    live_reply_file = open_live_reply_file()
    timestamps_file = open_live_reply_timestamps_file()
    resolved_thinking_sink = _resolve_thinking_sink(thinking_sink)
    thinking_file = (
        open_codex_thinking_file() if resolved_thinking_sink is not None else None
    )

    try:
        stderr_content, return_code = stream_json_lines(
            process,
            lambda line: _process_json_line(
                line,
                assistant_texts,
                suppress_output,
                error_events,
                live_reply_file,
                timestamps_file,
                usage_totals,
                runtime=runtime,
                tool_call_writer=tool_call_writer,
                thinking_sink=resolved_thinking_sink,
                thinking_file=thinking_file,
            ),
            suppress_output,
        )
    finally:
        if live_reply_file:
            live_reply_file.close()
        if timestamps_file:
            timestamps_file.close()
        if thinking_file:
            thinking_file.close()

    combined_text = "\n\n".join(assistant_texts)
    write_usage_artifact(usage_totals)
    stderr_content = append_error_events(stderr_content, return_code, error_events)

    return combined_text, stderr_content, return_code, usage_totals


def _process_json_line(
    line: str,
    assistant_texts: list[str],
    suppress_output: bool,
    error_events: list[str] | None = None,
    live_reply_file: IO[str] | None = None,
    timestamps_file: IO[str] | None = None,
    usage_totals: dict[str, int] | None = None,
    *,
    runtime: str = "claude",
    tool_call_writer: ToolCallWriter = append_claude_tool_call_event,
    thinking_sink: ThinkingSinkOption = None,
    thinking_file: IO[str] | None = None,
) -> None:
    """Parse a single JSON line and extract assistant text if present.

    Also captures ``error`` and ``result`` events into *error_events* when
    provided so callers have diagnostic context when the process fails.

    When *usage_totals* is provided, accumulates token usage from ``result``
    events into the dict.
    """
    line = line.strip()
    if not line:
        return

    try:
        event = json.loads(line)
    except json.JSONDecodeError as exc:
        record_stdout_json_decode_diagnostic(runtime, line, exc)
        return
    if not isinstance(event, Mapping):
        return

    event_type = event.get("type")
    tool_call_writer(event)
    resolved_thinking_sink = _resolve_thinking_sink(thinking_sink)

    if event_type == "assistant":
        message = event.get("message", {})
        content_blocks = message.get("content", [])
        for block in content_blocks:
            if not isinstance(block, Mapping):
                continue
            if block.get("type") == "text":
                append_stream_text(
                    block["text"],
                    assistant_texts,
                    suppress_output,
                    live_reply_file,
                    timestamps_file,
                )
            elif (
                block.get("type") == "thinking"
                and resolved_thinking_sink is not None
                and thinking_file is not None
                and isinstance(message, Mapping)
            ):
                resolved_thinking_sink(block, message, thinking_file)
    elif event_type in ("error", "result"):
        if error_events is not None:
            detail = _messages_error_detail(event)
            if detail:
                error_events.append(f"[{event_type}] {detail}")
        if event_type == "result" and usage_totals is not None:
            usage = event.get("usage")
            if isinstance(usage, dict):
                for key in usage_totals:
                    usage_totals[key] += usage.get(key, 0)


def _messages_error_detail(event: Mapping[str, Any]) -> str:
    detail = event.get("error") or event.get("message") or event.get("result", "")
    if not detail:
        errors = event.get("errors")
        if isinstance(errors, list):
            return "\n".join(str(item) for item in errors if item)
    if isinstance(detail, Mapping):
        message = detail.get("message")
        if message:
            return str(message)
        return json.dumps(detail)
    if isinstance(detail, str):
        return detail
    return str(detail)


def _resolve_thinking_sink(thinking_sink: ThinkingSinkOption) -> ThinkingSink | None:
    if thinking_sink is True:
        return _write_messages_thinking
    if thinking_sink is False:
        return None
    return thinking_sink


def _write_messages_thinking(
    block: Mapping[str, Any],
    message: Mapping[str, Any],
    thinking_file: IO[str],
) -> None:
    text = block.get("thinking", "")
    if not isinstance(text, str):
        text = str(text)
    if not text.strip():
        if not block.get("signature"):
            return
        usage = message.get("usage", {})
        output_tokens = (
            usage.get("output_tokens") if isinstance(usage, Mapping) else None
        )
        if isinstance(output_tokens, int) and output_tokens > 0:
            text = f"[encrypted thought · ~{output_tokens} output tokens]"
        else:
            text = "[encrypted thought]"
    entry = {
        "text": text,
        "timestamp": datetime.now(tz=UTC).isoformat(),
    }
    thinking_file.write(json.dumps(entry) + "\n")
    thinking_file.flush()
