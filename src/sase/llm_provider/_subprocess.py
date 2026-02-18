"""Shared subprocess streaming utilities for LLM providers."""

import json
import os
import select
import subprocess
import sys


def stream_process_output(
    process: subprocess.Popen[str],
    suppress_output: bool = False,
) -> tuple[str, str, int]:
    """Stream stdout and stderr from a process in real-time.

    Args:
        process: The subprocess.Popen process to stream from.
        suppress_output: If True, don't print output to console.

    Returns:
        Tuple of (stdout_content, stderr_content, return_code).
    """
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

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
            line = process.stdout.readline()
            if line:
                stdout_lines.append(line)
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
                for line in process.stdout:
                    stdout_lines.append(line)
                    if not suppress_output:
                        print(line, end="", flush=True)
            if process.stderr:
                for line in process.stderr:
                    stderr_lines.append(line)
                    if not suppress_output:
                        print(line, end="", file=sys.stderr, flush=True)
            break

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
    stderr_lines: list[str] = []

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
                _process_json_line(line, assistant_texts, suppress_output)

        if process.stderr and process.stderr in ready:
            line = process.stderr.readline()
            if line:
                stderr_lines.append(line)
                if not suppress_output:
                    print(line, end="", file=sys.stderr, flush=True)

        if process.poll() is not None:
            if process.stdout:
                for line in process.stdout:
                    _process_json_line(line, assistant_texts, suppress_output)
            if process.stderr:
                for line in process.stderr:
                    stderr_lines.append(line)
                    if not suppress_output:
                        print(line, end="", file=sys.stderr, flush=True)
            break

    return_code = process.wait()
    combined_text = "\n\n".join(assistant_texts)
    stderr_content = "".join(stderr_lines)

    return combined_text, stderr_content, return_code


def _process_json_line(
    line: str,
    assistant_texts: list[str],
    suppress_output: bool,
) -> None:
    """Parse a single JSON line and extract assistant text if present."""
    line = line.strip()
    if not line:
        return

    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return

    if event.get("type") != "assistant":
        return

    message = event.get("message", {})
    content_blocks = message.get("content", [])
    for block in content_blocks:
        if block.get("type") == "text":
            text = block["text"]
            assistant_texts.append(text)
            if not suppress_output:
                print(text, flush=True)
