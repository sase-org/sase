"""Claude Code stream-json subprocess parsing."""

import json
import subprocess
from typing import IO

from ._subprocess_artifacts import (
    append_stream_text,
    initial_usage_totals,
    open_live_reply_file,
    open_live_reply_timestamps_file,
    write_usage_artifact,
)
from ._subprocess_stream import append_error_events, stream_json_lines


def stream_and_parse_json_output(
    process: subprocess.Popen[str],
    suppress_output: bool = False,
) -> tuple[str, str, int, dict[str, int]]:
    """Stream stdout as JSON events and extract assistant text.

    Reads ``--output-format stream-json`` output from Claude Code, extracting
    text content from ``assistant`` events so that the full conversation is
    captured even when stop hooks inject extra turns.
    """
    assistant_texts: list[str] = []
    error_events: list[str] = []
    usage_totals = initial_usage_totals()
    live_reply_file = open_live_reply_file()
    timestamps_file = open_live_reply_timestamps_file()

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
            ),
            suppress_output,
        )
    finally:
        if live_reply_file:
            live_reply_file.close()
        if timestamps_file:
            timestamps_file.close()

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
    except json.JSONDecodeError:
        return

    event_type = event.get("type")

    if event_type == "assistant":
        message = event.get("message", {})
        content_blocks = message.get("content", [])
        for block in content_blocks:
            if block.get("type") == "text":
                append_stream_text(
                    block["text"],
                    assistant_texts,
                    suppress_output,
                    live_reply_file,
                    timestamps_file,
                )
    elif event_type in ("error", "result"):
        if error_events is not None:
            detail = (
                event.get("error") or event.get("message") or event.get("result", "")
            )
            if isinstance(detail, dict):
                detail = detail.get("message", json.dumps(detail))
            if detail:
                error_events.append(f"[{event_type}] {detail}")
        if event_type == "result" and usage_totals is not None:
            usage = event.get("usage")
            if isinstance(usage, dict):
                for key in usage_totals:
                    usage_totals[key] += usage.get(key, 0)
