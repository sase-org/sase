"""Shared subprocess streaming utilities for LLM providers."""

import json
import os
import re
import select
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

# Matches ANSI escape sequences: CSI, OSC, charset selection, and other
# single-character escapes.  Used to clean PTY output that may contain
# colour codes or cursor-movement sequences.
_ANSI_RE = re.compile(
    r"\x1b"
    r"(?:"
    r"\[[0-9;?]*[A-Za-z@]"  # CSI sequences (colors, cursor, erase, …)
    r"|\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC sequences
    r"|[()][0-9A-Za-z]"  # Charset selection
    r"|."  # Any other ESC + single char
    r")"
)


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences and bare carriage returns from *text*."""
    text = _ANSI_RE.sub("", text)
    # Normalize CRLF then strip bare CR (spinner overwrites, etc.)
    return text.replace("\r\n", "\n").replace("\r", "")


def _open_live_reply_file() -> IO[str] | None:
    """Open the live reply file for writing if SASE_ARTIFACTS_DIR is set."""
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return None
    path = os.path.join(artifacts_dir, "live_reply.md")
    return open(path, "w", encoding="utf-8")


def _open_live_reply_timestamps_file() -> IO[str] | None:
    """Open the live reply timestamps JSONL file if SASE_ARTIFACTS_DIR is set."""
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return None
    path = os.path.join(artifacts_dir, "live_reply_timestamps.jsonl")
    return open(path, "w", encoding="utf-8")


def _write_usage_artifact(usage_totals: dict[str, int]) -> None:
    """Write usage.json to the artifacts directory if SASE_ARTIFACTS_DIR is set."""
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return
    path = os.path.join(artifacts_dir, "usage.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(usage_totals, f, indent=2)
        f.write("\n")


def start_interrupt_monitor(
    process: subprocess.Popen[str],
    on_interrupt: Callable[[str | None], None],
) -> None:
    """Spin a daemon thread that watches for interrupt_request.json.

    When the file appears, invoke ``on_interrupt(message)`` with the
    ``"message"`` field from the JSON, unlink the file, and call
    ``process.terminate()``. Reads ``SASE_ARTIFACTS_DIR`` from the
    environment; no-op if unset.
    """
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return

    interrupt_path = Path(artifacts_dir) / "interrupt_request.json"

    def _monitor_interrupt() -> None:
        while process.poll() is None:
            if interrupt_path.exists():
                try:
                    data = json.loads(interrupt_path.read_text(encoding="utf-8"))
                    on_interrupt(data.get("message"))
                    interrupt_path.unlink(missing_ok=True)
                    process.terminate()
                except (OSError, json.JSONDecodeError):
                    pass
                return
            time.sleep(1.0)

    threading.Thread(target=_monitor_interrupt, daemon=True).start()


def stream_process_output(
    process: subprocess.Popen[str],
    suppress_output: bool = False,
    clean_ansi: bool = False,
) -> tuple[str, str, int]:
    """Stream stdout and stderr from a process in real-time.

    Args:
        process: The subprocess.Popen process to stream from.
        suppress_output: If True, don't print output to console.
        clean_ansi: If True, strip ANSI escape sequences from stdout
            lines before accumulating and writing to ``live_reply.md``.
            Useful when stdout is backed by a PTY that may inject
            terminal control codes.

    Returns:
        Tuple of (stdout_content, stderr_content, return_code).
    """
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    live_reply_file = _open_live_reply_file()
    timestamps_file = _open_live_reply_timestamps_file()
    prev_line_blank = True  # So the very first non-blank line triggers a timestamp

    try:
        # Set stdout and stderr to non-blocking mode
        if process.stdout:
            os.set_blocking(process.stdout.fileno(), False)
        if process.stderr:
            os.set_blocking(process.stderr.fileno(), False)

        while True:
            # Use select to wait for data on stdout or stderr
            readable: list[object] = []
            if process.stdout:
                readable.append(process.stdout)
            if process.stderr:
                readable.append(process.stderr)

            if not readable:
                break

            ready, _, _ = select.select(readable, [], [], 0.1)

            # Read from stdout
            if process.stdout and process.stdout in ready:
                try:
                    line = process.stdout.readline()
                except OSError:
                    # PTY master raises EIO when the slave side closes
                    line = ""
                if line:
                    if clean_ansi:
                        line = _strip_ansi(line)
                    stdout_lines.append(line)
                    if live_reply_file:
                        if timestamps_file and prev_line_blank and line.strip():
                            entry = {
                                "byte_offset": live_reply_file.tell(),
                                "timestamp": datetime.now(tz=UTC).isoformat(),
                            }
                            timestamps_file.write(json.dumps(entry) + "\n")
                            timestamps_file.flush()
                        prev_line_blank = not line.strip()
                        live_reply_file.write(line)
                        live_reply_file.flush()
                    if not suppress_output:
                        print(line, end="", flush=True)

            # Read from stderr
            if process.stderr and process.stderr in ready:
                line = process.stderr.readline()
                if line:
                    stderr_lines.append(line)
                    if not suppress_output:
                        print(line, end="", file=sys.stderr, flush=True)

            # Check if process has finished
            if process.poll() is not None:
                # Read any remaining output
                if process.stdout:
                    os.set_blocking(process.stdout.fileno(), True)
                    try:
                        for line in process.stdout:
                            if clean_ansi:
                                line = _strip_ansi(line)
                            stdout_lines.append(line)
                            if live_reply_file:
                                if timestamps_file and prev_line_blank and line.strip():
                                    entry = {
                                        "byte_offset": live_reply_file.tell(),
                                        "timestamp": datetime.now(tz=UTC).isoformat(),
                                    }
                                    timestamps_file.write(json.dumps(entry) + "\n")
                                    timestamps_file.flush()
                                prev_line_blank = not line.strip()
                                live_reply_file.write(line)
                                live_reply_file.flush()
                            if not suppress_output:
                                print(line, end="", flush=True)
                    except OSError:
                        pass
                if process.stderr:
                    os.set_blocking(process.stderr.fileno(), True)
                    for line in process.stderr:
                        stderr_lines.append(line)
                        if not suppress_output:
                            print(line, end="", file=sys.stderr, flush=True)
                break
    finally:
        if live_reply_file:
            live_reply_file.close()
        if timestamps_file:
            timestamps_file.close()

    return_code = process.wait()
    stdout_content = "".join(stdout_lines)
    stderr_content = "".join(stderr_lines)

    return stdout_content, stderr_content, return_code


def stream_and_parse_json_output(
    process: subprocess.Popen[str],
    suppress_output: bool = False,
) -> tuple[str, str, int, dict[str, int]]:
    """Stream stdout as JSON events and extract assistant text.

    Reads ``--output-format stream-json`` output from Claude Code,
    extracting text content from ``assistant`` events so that the full
    conversation is captured even when stop hooks inject extra turns.

    Args:
        process: The subprocess.Popen process to stream from.
        suppress_output: If True, don't print output to console.

    Returns:
        Tuple of (assistant_text, stderr_content, return_code, usage_totals).
    """
    assistant_texts: list[str] = []
    error_events: list[str] = []
    stderr_lines: list[str] = []
    usage_totals: dict[str, int] = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    live_reply_file = _open_live_reply_file()
    timestamps_file = _open_live_reply_timestamps_file()

    try:
        # Set stdout and stderr to non-blocking mode
        if process.stdout:
            os.set_blocking(process.stdout.fileno(), False)
        if process.stderr:
            os.set_blocking(process.stderr.fileno(), False)

        while True:
            readable: list[object] = []
            if process.stdout:
                readable.append(process.stdout)
            if process.stderr:
                readable.append(process.stderr)

            if not readable:
                break

            ready, _, _ = select.select(readable, [], [], 0.1)

            if process.stdout and process.stdout in ready:
                line = process.stdout.readline()
                if line:
                    _process_json_line(
                        line,
                        assistant_texts,
                        suppress_output,
                        error_events,
                        live_reply_file,
                        timestamps_file,
                        usage_totals,
                    )

            if process.stderr and process.stderr in ready:
                line = process.stderr.readline()
                if line:
                    stderr_lines.append(line)
                    if not suppress_output:
                        print(line, end="", file=sys.stderr, flush=True)

            if process.poll() is not None:
                if process.stdout:
                    os.set_blocking(process.stdout.fileno(), True)
                    for line in process.stdout:
                        _process_json_line(
                            line,
                            assistant_texts,
                            suppress_output,
                            error_events,
                            live_reply_file,
                            timestamps_file,
                            usage_totals,
                        )
                if process.stderr:
                    os.set_blocking(process.stderr.fileno(), True)
                    for line in process.stderr:
                        stderr_lines.append(line)
                        if not suppress_output:
                            print(line, end="", file=sys.stderr, flush=True)
                break
    finally:
        if live_reply_file:
            live_reply_file.close()
        if timestamps_file:
            timestamps_file.close()

    return_code = process.wait()
    combined_text = "\n\n".join(assistant_texts)
    stderr_content = "".join(stderr_lines)

    _write_usage_artifact(usage_totals)

    # If process failed, append any captured error/result events to stderr
    # so the caller has full diagnostic context
    if return_code != 0 and error_events:
        error_info = "\n".join(error_events)
        if stderr_content:
            stderr_content += "\n" + error_info
        else:
            stderr_content = error_info

    return combined_text, stderr_content, return_code, usage_totals


def stream_and_parse_qwen_json_output(
    process: subprocess.Popen[str],
    suppress_output: bool = False,
) -> tuple[str, str, int, dict[str, int]]:
    """Stream Qwen Code ``stream-json`` events and extract assistant text.

    Qwen's stream is Claude-like for assistant events, but its final
    ``result`` event may be the only reliable answer in some versions. This
    parser keeps assistant streaming behavior and falls back to the result
    text when no assistant text was emitted.
    """
    assistant_texts: list[str] = []
    error_events: list[str] = []
    stderr_lines: list[str] = []
    usage_totals: dict[str, int] = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    live_reply_file = _open_live_reply_file()
    timestamps_file = _open_live_reply_timestamps_file()

    try:
        if process.stdout:
            os.set_blocking(process.stdout.fileno(), False)
        if process.stderr:
            os.set_blocking(process.stderr.fileno(), False)

        while True:
            readable: list[object] = []
            if process.stdout:
                readable.append(process.stdout)
            if process.stderr:
                readable.append(process.stderr)

            if not readable:
                break

            ready, _, _ = select.select(readable, [], [], 0.1)

            if process.stdout and process.stdout in ready:
                line = process.stdout.readline()
                if line:
                    _process_qwen_json_line(
                        line,
                        assistant_texts,
                        suppress_output,
                        error_events,
                        live_reply_file,
                        timestamps_file,
                        usage_totals,
                    )

            if process.stderr and process.stderr in ready:
                line = process.stderr.readline()
                if line:
                    stderr_lines.append(line)
                    if not suppress_output:
                        print(line, end="", file=sys.stderr, flush=True)

            if process.poll() is not None:
                if process.stdout:
                    os.set_blocking(process.stdout.fileno(), True)
                    for line in process.stdout:
                        _process_qwen_json_line(
                            line,
                            assistant_texts,
                            suppress_output,
                            error_events,
                            live_reply_file,
                            timestamps_file,
                            usage_totals,
                        )
                if process.stderr:
                    os.set_blocking(process.stderr.fileno(), True)
                    for line in process.stderr:
                        stderr_lines.append(line)
                        if not suppress_output:
                            print(line, end="", file=sys.stderr, flush=True)
                break
    finally:
        if live_reply_file:
            live_reply_file.close()
        if timestamps_file:
            timestamps_file.close()

    return_code = process.wait()
    combined_text = "\n\n".join(assistant_texts)
    stderr_content = "".join(stderr_lines)

    _write_usage_artifact(usage_totals)

    if return_code != 0 and error_events:
        error_info = "\n".join(error_events)
        if stderr_content:
            stderr_content += "\n" + error_info
        else:
            stderr_content = error_info

    return combined_text, stderr_content, return_code, usage_totals


def stream_and_parse_opencode_json_output(
    process: subprocess.Popen[str],
    suppress_output: bool = False,
) -> tuple[str, str, int, dict[str, int]]:
    """Stream OpenCode ``run --format json`` events and extract text output."""
    assistant_texts: list[str] = []
    error_events: list[str] = []
    stderr_lines: list[str] = []
    usage_totals: dict[str, int] = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    live_reply_file = _open_live_reply_file()
    timestamps_file = _open_live_reply_timestamps_file()

    try:
        if process.stdout:
            os.set_blocking(process.stdout.fileno(), False)
        if process.stderr:
            os.set_blocking(process.stderr.fileno(), False)

        while True:
            readable: list[object] = []
            if process.stdout:
                readable.append(process.stdout)
            if process.stderr:
                readable.append(process.stderr)

            if not readable:
                break

            ready, _, _ = select.select(readable, [], [], 0.1)

            if process.stdout and process.stdout in ready:
                line = process.stdout.readline()
                if line:
                    _process_opencode_json_line(
                        line,
                        assistant_texts,
                        suppress_output,
                        error_events,
                        live_reply_file,
                        timestamps_file,
                        usage_totals,
                    )

            if process.stderr and process.stderr in ready:
                line = process.stderr.readline()
                if line:
                    stderr_lines.append(line)
                    if not suppress_output:
                        print(line, end="", file=sys.stderr, flush=True)

            if process.poll() is not None:
                if process.stdout:
                    os.set_blocking(process.stdout.fileno(), True)
                    for line in process.stdout:
                        _process_opencode_json_line(
                            line,
                            assistant_texts,
                            suppress_output,
                            error_events,
                            live_reply_file,
                            timestamps_file,
                            usage_totals,
                        )
                if process.stderr:
                    os.set_blocking(process.stderr.fileno(), True)
                    for line in process.stderr:
                        stderr_lines.append(line)
                        if not suppress_output:
                            print(line, end="", file=sys.stderr, flush=True)
                break
    finally:
        if live_reply_file:
            live_reply_file.close()
        if timestamps_file:
            timestamps_file.close()

    return_code = process.wait()
    combined_text = "\n\n".join(assistant_texts)
    stderr_content = "".join(stderr_lines)

    _write_usage_artifact(usage_totals)

    if return_code != 0 and error_events:
        error_info = "\n".join(error_events)
        if stderr_content:
            stderr_content += "\n" + error_info
        else:
            stderr_content = error_info

    return combined_text, stderr_content, return_code, usage_totals


def _open_codex_thinking_file() -> IO[str] | None:
    """Open the codex thinking JSONL file for writing if SASE_ARTIFACTS_DIR is set."""
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return None
    path = os.path.join(artifacts_dir, "codex_thinking.jsonl")
    return open(path, "w", encoding="utf-8")


def stream_and_parse_codex_json_output(
    process: subprocess.Popen[str],
    suppress_output: bool = False,
) -> tuple[str, str, int]:
    """Stream stdout as NDJSON events and extract assistant text from Codex.

    Reads ``codex exec --json`` output, extracting text from
    ``item.completed`` events where ``item.type == "message"`` and content
    blocks have ``type == "output_text"``.

    Also captures reasoning summary items (``item.type == "reasoning"``) and
    writes them to ``codex_thinking.jsonl`` in the artifacts directory for the
    TUI thinking panel.

    Args:
        process: The subprocess.Popen process to stream from.
        suppress_output: If True, don't print output to console.

    Returns:
        Tuple of (assistant_text, stderr_content, return_code).
    """
    assistant_texts: list[str] = []
    error_events: list[str] = []
    stderr_lines: list[str] = []
    pending_reasoning: list[dict[str, object]] = []
    live_reply_file = _open_live_reply_file()
    timestamps_file = _open_live_reply_timestamps_file()
    thinking_file = _open_codex_thinking_file()

    try:
        if process.stdout:
            os.set_blocking(process.stdout.fileno(), False)
        if process.stderr:
            os.set_blocking(process.stderr.fileno(), False)

        while True:
            readable: list[object] = []
            if process.stdout:
                readable.append(process.stdout)
            if process.stderr:
                readable.append(process.stderr)

            if not readable:
                break

            ready, _, _ = select.select(readable, [], [], 0.1)

            if process.stdout and process.stdout in ready:
                line = process.stdout.readline()
                if line:
                    _process_codex_json_line(
                        line,
                        assistant_texts,
                        suppress_output,
                        error_events,
                        live_reply_file,
                        thinking_file,
                        pending_reasoning,
                        timestamps_file,
                    )

            if process.stderr and process.stderr in ready:
                line = process.stderr.readline()
                if line:
                    stderr_lines.append(line)
                    if not suppress_output:
                        print(line, end="", file=sys.stderr, flush=True)

            if process.poll() is not None:
                if process.stdout:
                    os.set_blocking(process.stdout.fileno(), True)
                    for line in process.stdout:
                        _process_codex_json_line(
                            line,
                            assistant_texts,
                            suppress_output,
                            error_events,
                            live_reply_file,
                            thinking_file,
                            pending_reasoning,
                            timestamps_file,
                        )
                if process.stderr:
                    os.set_blocking(process.stderr.fileno(), True)
                    for line in process.stderr:
                        stderr_lines.append(line)
                        if not suppress_output:
                            print(line, end="", file=sys.stderr, flush=True)
                break

        # Flush any remaining buffered reasoning (no following action)
        if pending_reasoning and thinking_file is not None:
            _flush_codex_reasoning(pending_reasoning, thinking_file, None)
    finally:
        if live_reply_file:
            live_reply_file.close()
        if timestamps_file:
            timestamps_file.close()
        if thinking_file:
            thinking_file.close()

    return_code = process.wait()
    combined_text = "\n\n".join(assistant_texts)
    stderr_content = "".join(stderr_lines)

    if return_code != 0 and error_events:
        error_info = "\n".join(error_events)
        if stderr_content:
            stderr_content += "\n" + error_info
        else:
            stderr_content = error_info

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

    Extracts text from ``item.completed`` events where
    ``item.type == "agent_message"`` with a direct ``text`` field.

    Also captures reasoning summary items (``item.type == "reasoning"``)
    and writes them as JSONL entries to *thinking_file* for the TUI
    thinking panel.  When *pending_reasoning* is provided (a mutable list),
    reasoning items are buffered so the ``following_action`` can be attached
    when the next action event arrives.

    Also captures ``error`` and ``turn.failed`` events into *error_events*.
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
            text = item.get("text", "")
            if text:
                # Flush pending reasoning with text as following action
                if pending_reasoning and thinking_file is not None:
                    action = text.strip()[:80] if text.strip() else None
                    _flush_codex_reasoning(pending_reasoning, thinking_file, action)

                if live_reply_file:
                    if timestamps_file:
                        ts_entry = {
                            "byte_offset": live_reply_file.tell(),
                            "timestamp": datetime.now(tz=UTC).isoformat(),
                        }
                        timestamps_file.write(json.dumps(ts_entry) + "\n")
                        timestamps_file.flush()
                    if assistant_texts:
                        live_reply_file.write("\n\n")
                    live_reply_file.write(text)
                    live_reply_file.flush()
                assistant_texts.append(text)
                if not suppress_output:
                    print(text, flush=True)
        elif item_type == "reasoning" and thinking_file is not None:
            if pending_reasoning is not None:
                # Flush any previously buffered reasoning (no action found)
                _flush_codex_reasoning(pending_reasoning, thinking_file, None)
                # Buffer this reasoning for following_action attachment
                pending_reasoning.clear()
                pending_reasoning.append(item)
            else:
                # No buffering — write immediately (backward compat)
                _write_codex_thinking(item, thinking_file)
        elif item_type == "function_call":
            # Flush pending reasoning with this function call as action
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


def _write_codex_thinking(
    item: dict[str, object],
    thinking_file: IO[str],
    following_action: str | None = None,
) -> None:
    """Extract reasoning text from a Codex reasoning item and write to JSONL.

    Codex reasoning items have a ``summary`` list of summary parts::

        {"type": "reasoning", "summary": [{"type": "summary_text", "text": "..."}]}
    """
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

    Also captures ``error`` and ``result`` events into *error_events* (when
    provided) so callers have diagnostic context when the process fails.

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
                text = block["text"]
                if live_reply_file:
                    if timestamps_file:
                        ts_entry = {
                            "byte_offset": live_reply_file.tell(),
                            "timestamp": datetime.now(tz=UTC).isoformat(),
                        }
                        timestamps_file.write(json.dumps(ts_entry) + "\n")
                        timestamps_file.flush()
                    if assistant_texts:
                        live_reply_file.write("\n\n")
                    live_reply_file.write(text)
                    live_reply_file.flush()
                assistant_texts.append(text)
                if not suppress_output:
                    print(text, flush=True)
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


def _process_qwen_json_line(
    line: str,
    assistant_texts: list[str],
    suppress_output: bool,
    error_events: list[str] | None = None,
    live_reply_file: IO[str] | None = None,
    timestamps_file: IO[str] | None = None,
    usage_totals: dict[str, int] | None = None,
) -> None:
    """Parse one Qwen Code stream-json line.

    Assistant events are streamed immediately. Result text is captured only
    when no assistant text has been seen, avoiding duplicate final answers for
    Qwen versions that emit both event types.
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
        for text in _qwen_assistant_texts(event):
            _append_stream_text(
                text,
                assistant_texts,
                suppress_output,
                live_reply_file,
                timestamps_file,
            )
    elif event_type == "result":
        _capture_qwen_diagnostic(event, "result", error_events)
        if usage_totals is not None:
            _accumulate_qwen_usage(event.get("usage"), usage_totals)
        result_text = _qwen_result_text(event)
        if result_text and not assistant_texts:
            _append_stream_text(
                result_text,
                assistant_texts,
                suppress_output,
                live_reply_file,
                timestamps_file,
            )
    elif event_type == "error":
        _capture_qwen_diagnostic(event, "error", error_events)


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
            _append_stream_text(
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


def _qwen_assistant_texts(event: Mapping[str, object]) -> list[str]:
    """Extract text blocks from known Qwen assistant event shapes."""
    texts: list[str] = []
    message = event.get("message")
    if isinstance(message, dict):
        texts.extend(_extract_text_from_content(message.get("content")))
    texts.extend(_extract_text_from_content(event.get("content")))
    return [text for text in texts if text]


def _opencode_texts(event: Mapping[str, object]) -> list[str]:
    """Extract assistant text from known OpenCode JSON event shapes."""
    texts: list[str] = []
    part = event.get("part")
    if isinstance(part, dict):
        text = part.get("text")
        if isinstance(text, str) and text:
            texts.append(text)
        texts.extend(_extract_text_from_content(part.get("content")))

    text = event.get("text")
    if isinstance(text, str) and text:
        texts.append(text)
    texts.extend(_extract_text_from_content(event.get("content")))
    return texts


def _qwen_result_text(event: Mapping[str, object]) -> str:
    """Extract final text from known Qwen result event fields."""
    for key in ("result", "response", "text", "content"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    message = event.get("message")
    if isinstance(message, dict):
        texts = _extract_text_from_content(message.get("content"))
        if texts:
            return "\n".join(texts)
    return ""


def _extract_text_from_content(content: object) -> list[str]:
    """Extract text from a string or list of content blocks."""
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []

    texts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str) and text:
                texts.append(text)
    return texts


def _append_stream_text(
    text: str,
    assistant_texts: list[str],
    suppress_output: bool,
    live_reply_file: IO[str] | None,
    timestamps_file: IO[str] | None,
) -> None:
    """Append extracted assistant text to memory, artifacts, and console."""
    if live_reply_file:
        if timestamps_file:
            ts_entry = {
                "byte_offset": live_reply_file.tell(),
                "timestamp": datetime.now(tz=UTC).isoformat(),
            }
            timestamps_file.write(json.dumps(ts_entry) + "\n")
            timestamps_file.flush()
        if assistant_texts:
            live_reply_file.write("\n\n")
        live_reply_file.write(text)
        live_reply_file.flush()
    assistant_texts.append(text)
    if not suppress_output:
        print(text, flush=True)


def _capture_qwen_diagnostic(
    event: Mapping[str, object],
    event_type: str,
    error_events: list[str] | None,
) -> None:
    """Capture Qwen error/result detail for non-zero exit diagnostics."""
    if error_events is None:
        return
    detail = event.get("error") or event.get("message") or event.get("result", "")
    if isinstance(detail, dict):
        detail = detail.get("message", json.dumps(detail))
    if isinstance(detail, str) and detail:
        error_events.append(f"[{event_type}] {detail}")


def _accumulate_qwen_usage(
    usage: object,
    usage_totals: dict[str, int],
) -> None:
    """Accumulate Qwen token usage into SASE's common usage keys."""
    if not isinstance(usage, dict):
        return

    usage_totals["input_tokens"] += _int_usage(
        usage.get("input_tokens", usage.get("prompt_tokens", 0))
    )
    usage_totals["output_tokens"] += _int_usage(
        usage.get("output_tokens", usage.get("completion_tokens", 0))
    )
    usage_totals["cache_creation_input_tokens"] += _int_usage(
        usage.get("cache_creation_input_tokens", 0)
    )
    usage_totals["cache_read_input_tokens"] += _int_usage(
        usage.get("cache_read_input_tokens", 0)
    )


def _int_usage(value: object) -> int:
    """Return *value* as an int usage count when possible."""
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


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

    usage_totals["input_tokens"] += _int_usage(tokens.get("input", 0))
    usage_totals["output_tokens"] += _int_usage(tokens.get("output", 0))

    cache = tokens.get("cache")
    if isinstance(cache, dict):
        usage_totals["cache_read_input_tokens"] += _int_usage(cache.get("read", 0))
        usage_totals["cache_creation_input_tokens"] += _int_usage(cache.get("write", 0))
