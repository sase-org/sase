"""Codex NDJSON subprocess parsing and thinking capture."""

import json
import os
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import IO

from ._subprocess_artifacts import (
    open_codex_thinking_file,
    open_live_reply_file,
    open_live_reply_timestamps_file,
    write_reply_timestamp,
)
from ._subprocess_stream import append_error_events, stream_json_lines


def stream_and_parse_codex_json_output(
    process: subprocess.Popen[str],
    suppress_output: bool = False,
) -> tuple[str, str, int]:
    """Stream stdout as NDJSON events and extract assistant text from Codex."""
    assistant_texts: list[str] = []
    error_events: list[str] = []
    pending_reasoning: list[dict[str, object]] = []
    live_reply_file = open_live_reply_file()
    timestamps_file = open_live_reply_timestamps_file()
    thinking_file = open_codex_thinking_file()

    try:
        stderr_content, return_code = stream_json_lines(
            process,
            lambda line: _process_codex_json_line(
                line,
                assistant_texts,
                suppress_output,
                error_events,
                live_reply_file,
                thinking_file,
                pending_reasoning,
                timestamps_file,
            ),
            suppress_output,
        )

        # Flush any remaining buffered reasoning (no following action).
        if pending_reasoning and thinking_file is not None:
            _flush_codex_reasoning(pending_reasoning, thinking_file, None)
    finally:
        if live_reply_file:
            live_reply_file.close()
        if timestamps_file:
            timestamps_file.close()
        if thinking_file:
            thinking_file.close()

    combined_text = "\n\n".join(assistant_texts)
    stderr_content = append_error_events(stderr_content, return_code, error_events)

    return combined_text, stderr_content, return_code


def _process_codex_json_line(
    line: str,
    assistant_texts: list[str],
    suppress_output: bool,
    error_events: list[str] | None = None,
    live_reply_file: IO[str] | None = None,
    thinking_file: IO[str] | None = None,
    pending_reasoning: list[dict[str, object]] | None = None,
    timestamps_file: IO[str] | None = None,
) -> None:
    """Parse a single Codex NDJSON line and extract assistant text.

    Also captures reasoning summary items and writes them as JSONL entries to
    *thinking_file*. When *pending_reasoning* is provided, reasoning items are
    buffered so the next action can be attached as ``following_action``.
    """
    line = line.strip()
    if not line:
        return

    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return

    event_type = event.get("type")

    if event_type == "item.completed":
        item = event.get("item", {})
        item_type = item.get("type")
        if item_type == "agent_message":
            _handle_codex_agent_message(
                item,
                assistant_texts,
                suppress_output,
                live_reply_file,
                thinking_file,
                pending_reasoning,
                timestamps_file,
            )
        elif item_type == "reasoning" and thinking_file is not None:
            _handle_codex_reasoning(item, thinking_file, pending_reasoning)
        elif item_type == "function_call":
            if pending_reasoning and thinking_file is not None:
                action = _format_codex_action(item)
                _flush_codex_reasoning(pending_reasoning, thinking_file, action)
    elif event_type == "error" and error_events is not None:
        msg = event.get("message", "")
        if msg:
            error_events.append(f"[error] {msg}")
    elif event_type == "turn.failed" and error_events is not None:
        err = event.get("error", {})
        msg = err.get("message", "") if isinstance(err, dict) else str(err)
        if msg:
            error_events.append(f"[turn.failed] {msg}")


def _handle_codex_agent_message(
    item: Mapping[str, object],
    assistant_texts: list[str],
    suppress_output: bool,
    live_reply_file: IO[str] | None,
    thinking_file: IO[str] | None,
    pending_reasoning: list[dict[str, object]] | None,
    timestamps_file: IO[str] | None,
) -> None:
    text_obj = item.get("text", "")
    if not isinstance(text_obj, str) or not text_obj:
        return
    text = text_obj

    if pending_reasoning and thinking_file is not None:
        action = text.strip()[:80] if text.strip() else None
        _flush_codex_reasoning(pending_reasoning, thinking_file, action)

    if live_reply_file:
        write_reply_timestamp(live_reply_file, timestamps_file)
        if assistant_texts:
            live_reply_file.write("\n\n")
        live_reply_file.write(text)
        live_reply_file.flush()
    assistant_texts.append(text)
    if not suppress_output:
        print(text, flush=True)


def _handle_codex_reasoning(
    item: Mapping[str, object],
    thinking_file: IO[str],
    pending_reasoning: list[dict[str, object]] | None,
) -> None:
    if pending_reasoning is not None:
        # Flush any previously buffered reasoning (no action found), then buffer
        # this item for following_action attachment.
        _flush_codex_reasoning(pending_reasoning, thinking_file, None)
        pending_reasoning.clear()
        pending_reasoning.append(dict(item))
    else:
        _write_codex_thinking(dict(item), thinking_file)


def _write_codex_thinking(
    item: dict[str, object],
    thinking_file: IO[str],
    following_action: str | None = None,
) -> None:
    """Extract reasoning text from a Codex reasoning item and write to JSONL."""
    summary = item.get("summary", [])
    if not isinstance(summary, list):
        return
    texts = [
        s.get("text", "")
        for s in summary
        if isinstance(s, dict) and s.get("type") == "summary_text"
    ]
    text = "\n".join(t for t in texts if t)
    if not text:
        return
    entry: dict[str, object] = {
        "text": text,
        "timestamp": datetime.now(tz=UTC).isoformat(),
    }
    if following_action:
        entry["following_action"] = following_action
    thinking_file.write(json.dumps(entry) + "\n")
    thinking_file.flush()


def _flush_codex_reasoning(
    pending: list[dict[str, object]],
    thinking_file: IO[str],
    following_action: str | None,
) -> None:
    """Write buffered Codex reasoning to the thinking file and clear the buffer."""
    if not pending:
        return
    item = pending[0]
    _write_codex_thinking(item, thinking_file, following_action)
    pending.clear()


def _format_codex_action(item: Mapping[str, object]) -> str | None:
    """Format a Codex ``function_call`` item as a readable action string."""
    name = item.get("name", "")
    if not isinstance(name, str) or not name:
        return None

    arguments = item.get("arguments", "")
    if isinstance(arguments, str):
        try:
            args = json.loads(arguments)
        except (json.JSONDecodeError, TypeError):
            args = {}
    elif isinstance(arguments, dict):
        args = arguments
    else:
        args = {}

    if name in ("shell", "container.exec"):
        cmd = args.get("command", "")
        if isinstance(cmd, list):
            cmd = " ".join(str(c) for c in cmd)
        if isinstance(cmd, str) and cmd.strip():
            first_word = cmd.strip().split()[0]
            return f"Bash `{first_word}`"
        return "Bash"

    if name == "read_file":
        path = args.get("path", args.get("file_path", ""))
        if isinstance(path, str) and path:
            return f"Read {os.path.basename(path)}"
        return "Read"

    if name in ("write_file", "apply_patch", "apply_diff"):
        path = args.get("path", args.get("file_path", ""))
        if isinstance(path, str) and path:
            return f"Edit {os.path.basename(path)}"
        return "Edit"

    return name
