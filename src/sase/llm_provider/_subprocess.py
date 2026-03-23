"""Shared subprocess streaming utilities for LLM providers."""

import json
import os
import re
import select
import subprocess
import sys
from datetime import UTC, datetime
from collections.abc import Mapping
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
                    try:
                        for line in process.stdout:
                            if clean_ansi:
                                line = _strip_ansi(line)
                            stdout_lines.append(line)
                            if live_reply_file:
                                live_reply_file.write(line)
                                live_reply_file.flush()
                            if not suppress_output:
                                print(line, end="", flush=True)
                    except OSError:
                        pass
                if process.stderr:
                    for line in process.stderr:
                        stderr_lines.append(line)
                        if not suppress_output:
                            print(line, end="", file=sys.stderr, flush=True)
                break
    finally:
        if live_reply_file:
            live_reply_file.close()

    return_code = process.wait()
    stdout_content = "".join(stdout_lines)
    stderr_content = "".join(stderr_lines)

    return stdout_content, stderr_content, return_code


def stream_and_parse_json_output(
    process: subprocess.Popen[str],
    suppress_output: bool = False,
) -> tuple[str, str, int]:
    """Stream stdout as JSON events and extract assistant text.

    Reads ``--output-format stream-json`` output from Claude Code,
    extracting text content from ``assistant`` events so that the full
    conversation is captured even when stop hooks inject extra turns.

    Args:
        process: The subprocess.Popen process to stream from.
        suppress_output: If True, don't print output to console.

    Returns:
        Tuple of (assistant_text, stderr_content, return_code).
    """
    assistant_texts: list[str] = []
    error_events: list[str] = []
    stderr_lines: list[str] = []
    live_reply_file = _open_live_reply_file()

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
                    )

            if process.stderr and process.stderr in ready:
                line = process.stderr.readline()
                if line:
                    stderr_lines.append(line)
                    if not suppress_output:
                        print(line, end="", file=sys.stderr, flush=True)

            if process.poll() is not None:
                if process.stdout:
                    for line in process.stdout:
                        _process_json_line(
                            line,
                            assistant_texts,
                            suppress_output,
                            error_events,
                            live_reply_file,
                        )
                if process.stderr:
                    for line in process.stderr:
                        stderr_lines.append(line)
                        if not suppress_output:
                            print(line, end="", file=sys.stderr, flush=True)
                break
    finally:
        if live_reply_file:
            live_reply_file.close()

    return_code = process.wait()
    combined_text = "\n\n".join(assistant_texts)
    stderr_content = "".join(stderr_lines)

    # If process failed, append any captured error/result events to stderr
    # so the caller has full diagnostic context
    if return_code != 0 and error_events:
        error_info = "\n".join(error_events)
        if stderr_content:
            stderr_content += "\n" + error_info
        else:
            stderr_content = error_info

    return combined_text, stderr_content, return_code


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
                    )

            if process.stderr and process.stderr in ready:
                line = process.stderr.readline()
                if line:
                    stderr_lines.append(line)
                    if not suppress_output:
                        print(line, end="", file=sys.stderr, flush=True)

            if process.poll() is not None:
                if process.stdout:
                    for line in process.stdout:
                        _process_codex_json_line(
                            line,
                            assistant_texts,
                            suppress_output,
                            error_events,
                            live_reply_file,
                            thinking_file,
                            pending_reasoning,
                        )
                if process.stderr:
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
) -> None:
    """Parse a single JSON line and extract assistant text if present.

    Also captures ``error`` and ``result`` events into *error_events* (when
    provided) so callers have diagnostic context when the process fails.
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
                    if assistant_texts:
                        live_reply_file.write("\n\n")
                    live_reply_file.write(text)
                    live_reply_file.flush()
                assistant_texts.append(text)
                if not suppress_output:
                    print(text, flush=True)
    elif event_type in ("error", "result") and error_events is not None:
        # Extract the most useful diagnostic string from the event
        detail = event.get("error") or event.get("message") or event.get("result", "")
        if isinstance(detail, dict):
            detail = detail.get("message", json.dumps(detail))
        if detail:
            error_events.append(f"[{event_type}] {detail}")
