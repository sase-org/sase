"""OpenCode JSON subprocess parsing."""

import json
import subprocess
from collections.abc import Mapping
from typing import IO

from . import _subprocess_qwen as _qwen
from ._subprocess_artifacts import (
    append_stream_text,
    initial_usage_totals,
    int_usage,
    open_live_reply_file,
    open_live_reply_timestamps_file,
    write_usage_artifact,
)
from ._subprocess_stream import append_error_events, stream_json_lines


def stream_and_parse_opencode_json_output(
    process: subprocess.Popen[str],
    suppress_output: bool = False,
) -> tuple[str, str, int, dict[str, int]]:
    """Stream OpenCode ``run --format json`` events and extract text output."""
    assistant_texts: list[str] = []
    error_events: list[str] = []
    usage_totals = initial_usage_totals()
    live_reply_file = open_live_reply_file()
    timestamps_file = open_live_reply_timestamps_file()

    try:
        stderr_content, return_code = stream_json_lines(
            process,
            lambda line: _process_opencode_json_line(
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


def _process_opencode_json_line(
    line: str,
    assistant_texts: list[str],
    suppress_output: bool,
    error_events: list[str] | None = None,
    live_reply_file: IO[str] | None = None,
    timestamps_file: IO[str] | None = None,
    usage_totals: dict[str, int] | None = None,
) -> None:
    """Parse one OpenCode ``run --format json`` JSONL event."""
    line = line.strip()
    if not line:
        return

    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return

    if not isinstance(event, dict):
        return

    event_type = event.get("type")

    if event_type == "text":
        for text in _opencode_texts(event):
            append_stream_text(
                text,
                assistant_texts,
                suppress_output,
                live_reply_file,
                timestamps_file,
            )
    elif event_type == "step_finish":
        if usage_totals is not None:
            _accumulate_opencode_usage(event, usage_totals)
    elif event_type == "error":
        _capture_opencode_diagnostic(event, error_events)


def _opencode_texts(event: Mapping[str, object]) -> list[str]:
    """Extract assistant text from known OpenCode JSON event shapes."""
    texts: list[str] = []
    part = event.get("part")
    if isinstance(part, dict):
        text = part.get("text")
        if isinstance(text, str) and text:
            texts.append(text)
        texts.extend(_qwen._extract_text_from_content(part.get("content")))

    text = event.get("text")
    if isinstance(text, str) and text:
        texts.append(text)
    texts.extend(_qwen._extract_text_from_content(event.get("content")))
    return texts


def _capture_opencode_diagnostic(
    event: Mapping[str, object],
    error_events: list[str] | None,
) -> None:
    """Capture OpenCode error detail for non-zero exit diagnostics."""
    if error_events is None:
        return
    detail = event.get("error") or event.get("message")
    if isinstance(detail, dict):
        nested_data = detail.get("data")
        if isinstance(nested_data, dict) and isinstance(
            nested_data.get("message"), str
        ):
            detail = nested_data["message"]
        else:
            detail = detail.get("message", json.dumps(detail))
    if isinstance(detail, str) and detail:
        error_events.append(f"[error] {detail}")


def _accumulate_opencode_usage(
    event: Mapping[str, object],
    usage_totals: dict[str, int],
) -> None:
    """Accumulate OpenCode token counters from ``step_finish`` events."""
    part = event.get("part")
    if not isinstance(part, dict):
        return
    tokens = part.get("tokens")
    if not isinstance(tokens, dict):
        return

    usage_totals["input_tokens"] += int_usage(tokens.get("input", 0))
    usage_totals["output_tokens"] += int_usage(tokens.get("output", 0))

    cache = tokens.get("cache")
    if isinstance(cache, dict):
        usage_totals["cache_read_input_tokens"] += int_usage(cache.get("read", 0))
        usage_totals["cache_creation_input_tokens"] += int_usage(cache.get("write", 0))
