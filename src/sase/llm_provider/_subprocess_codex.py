"""Codex NDJSON subprocess parsing and thinking capture."""

import json
import os
import shlex
import subprocess
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import IO, Any

from ._subprocess_artifacts import (
    open_codex_thinking_file,
    open_live_reply_file,
    open_live_reply_timestamps_file,
    write_reply_timestamp,
)
from ._subprocess_diagnostics import record_stdout_json_decode_diagnostic
from ._subprocess_stream import append_error_events, stream_json_lines
from ._tool_calls import append_codex_tool_call_event

CODEX_TURN_INTEGRITY_ERROR_PREFIX = "Codex turn integrity failure"


@dataclass(frozen=True)
class CodexStrandedCommand:
    """One command still running when Codex reported task completion."""

    command_id: str
    command: str | None
    reason: str
    is_handoff: bool


@dataclass(frozen=True)
class CodexStreamResult:
    """Parsed Codex output plus facts the provider must resolve before success.

    Iteration preserves the historical three-value unpacking contract for parser
    callers while exposing stranded-command facts to :class:`CodexProvider`.
    """

    content: str
    stderr_content: str
    return_code: int
    stranded_commands: tuple[CodexStrandedCommand, ...] = ()
    integrity_error: str | None = None

    def __iter__(self) -> Iterator[str | int]:
        yield self.content
        yield self.stderr_content
        yield self.return_code


@dataclass
class _CodexTurnIntegrityState:
    saw_task_complete: bool = False
    has_nonempty_final_answer: bool = False
    pending_commands: dict[str, str | None] = field(default_factory=dict)
    killed_commands: dict[str, str | None] = field(default_factory=dict)

    def observe(self, event: Mapping[str, Any]) -> None:
        payload = _codex_event_payload(event)
        event_type = _string(payload.get("type"))

        if event_type in {"turn.completed", "turn_completed", "task_complete"}:
            self.saw_task_complete = True
            if _has_nonempty_message(payload.get("last_agent_message")):
                self.has_nonempty_final_answer = True

        if event_type not in {
            "item.started",
            "item_started",
            "item.completed",
            "item_completed",
        }:
            return

        item = payload.get("item")
        if not isinstance(item, Mapping):
            return

        item_type = _normalized_item_type(item.get("type"))
        if item_type == "agentmessage":
            if _is_final_answer_message(payload, item) and _has_nonempty_message(
                item.get("text")
            ):
                self.has_nonempty_final_answer = True
            return
        if item_type != "commandexecution":
            return

        command_id = _command_item_id(item)
        command = _command_item_text(item)
        if event_type in {"item.started", "item_started"}:
            self.pending_commands[command_id] = command
            return

        self.pending_commands.pop(command_id, None)
        if _is_killed_teardown_command(item):
            self.killed_commands[command_id] = command

    def stranded_commands(self) -> tuple[CodexStrandedCommand, ...]:
        """Return commands that need a provider-level recovery decision."""
        if not self.saw_task_complete:
            return ()
        return tuple(
            [
                CodexStrandedCommand(
                    command_id=command_id,
                    command=command,
                    reason="killed_at_teardown",
                    is_handoff=is_sase_handoff_command(command),
                )
                for command_id, command in self.killed_commands.items()
            ]
            + [
                CodexStrandedCommand(
                    command_id=command_id,
                    command=command,
                    reason="started_without_result",
                    is_handoff=is_sase_handoff_command(command),
                )
                for command_id, command in self.pending_commands.items()
            ]
        )

    def integrity_error(
        self, stranded_commands: Sequence[CodexStrandedCommand]
    ) -> str | None:
        if not self.saw_task_complete or self.has_nonempty_final_answer:
            return None
        non_handoff_commands = tuple(
            command for command in stranded_commands if not command.is_handoff
        )
        killed_commands = tuple(
            command
            for command in non_handoff_commands
            if command.reason == "killed_at_teardown"
        )
        if killed_commands:
            details = _format_stranded_command_refs(killed_commands)
            return (
                f"{CODEX_TURN_INTEGRITY_ERROR_PREFIX}: task completed with no "
                "final agent message and command execution was killed at teardown "
                f"(exit_code -1): {details}"
            )
        pending_commands = tuple(
            command
            for command in non_handoff_commands
            if command.reason == "started_without_result"
        )
        if pending_commands:
            details = _format_stranded_command_refs(pending_commands)
            return (
                f"{CODEX_TURN_INTEGRITY_ERROR_PREFIX}: task completed with no "
                "final agent message and command execution started without a "
                f"result: {details}"
            )
        return None


def _codex_event_payload(event: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the inner Codex rollout payload when stdout uses wrapper events."""
    if event.get("type") == "event_msg" and isinstance(event.get("payload"), Mapping):
        return event["payload"]
    return event


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _normalized_item_type(value: object) -> str:
    raw = value if isinstance(value, str) else ""
    return raw.replace("_", "").lower()


def _is_final_answer_message(
    payload: Mapping[str, Any], item: Mapping[str, Any]
) -> bool:
    """Return whether an agent message belongs to Codex's final-answer phase."""
    for source in (item, payload):
        phase = source.get("phase")
        if isinstance(phase, str) and phase.replace("-", "_").lower() == "final_answer":
            return True
    return False


def _has_nonempty_message(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return any(_has_nonempty_message(child) for child in value.values())
    if isinstance(value, list):
        return any(_has_nonempty_message(child) for child in value)
    return value is not None and value is not False


def _command_item_id(item: Mapping[str, Any]) -> str:
    for key in ("id", "call_id", "process_id"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return "<unknown-command>"


def _command_item_text(item: Mapping[str, Any]) -> str | None:
    command = item.get("command")
    if isinstance(command, list):
        return shlex.join(str(part) for part in command)
    if isinstance(command, str):
        return command
    return None


def _is_killed_teardown_command(item: Mapping[str, Any]) -> bool:
    if item.get("exit_code") != -1:
        return False
    status = item.get("status")
    if not isinstance(status, str):
        return True
    return status.lower() in {
        "failed",
        "failure",
        "error",
        "cancelled",
        "canceled",
        "interrupted",
    }


def _format_stranded_command_refs(commands: Sequence[CodexStrandedCommand]) -> str:
    refs: list[str] = []
    for stranded in commands[:3]:
        command_id = stranded.command_id
        command = stranded.command
        if command:
            one_line = " ".join(command.split())
            if len(one_line) > 80:
                one_line = one_line[:77] + "..."
            refs.append(f"{command_id} ({one_line})")
        else:
            refs.append(command_id)
    if len(commands) > 3:
        refs.append(f"+{len(commands) - 3} more")
    return ", ".join(refs)


# These prefixes are the direct CLI handoff entry points. Their corresponding
# paths call ``write_pending_handoff_marker`` (or the shared gate helper) before
# ``kill_agent_runner_group``: monitor/start, plan/propose, pipe, questions,
# gate/create, sudo/request, launch/request, and run.
_SASE_HANDOFF_COMMAND_PREFIXES = (
    ("monitor", "start"),
    ("plan", "propose"),
    ("pipe",),
    ("questions",),
    ("gate", "create"),
    ("sudo", "request"),
    ("launch", "request"),
    ("run",),
)


def is_sase_handoff_command(command: str | None) -> bool:
    """Return whether *command* is a SASE CLI command that hands off a turn."""
    if not command:
        return False
    argv = _handoff_command_argv(command)
    if not argv:
        return False
    return any(
        tuple(argv[: len(prefix)]) == prefix
        for prefix in _SASE_HANDOFF_COMMAND_PREFIXES
    )


def _handoff_command_argv(command: str) -> list[str]:
    """Extract a SASE command argv, including the usual ``zsh -lc`` wrapper."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return []
    if not tokens:
        return []

    shell_command = _shell_command_text(tokens)
    if shell_command is not None:
        return _handoff_command_argv(shell_command)

    index = 0
    while index < len(tokens) and ("=" in tokens[index] or tokens[index] == "env"):
        index += 1
    if index < len(tokens) and tokens[index] == "exec":
        index += 1
    if index >= len(tokens) or os.path.basename(tokens[index]) != "sase":
        return []
    return tokens[index + 1 :]


def _shell_command_text(tokens: Sequence[str]) -> str | None:
    """Return the script supplied to a shell ``-c`` invocation, if present."""
    shell_names = {"sh", "bash", "zsh", "fish"}
    if os.path.basename(tokens[0]) not in shell_names:
        return None
    for index, token in enumerate(tokens[:-1]):
        if token == "-c" or (token.startswith("-") and "c" in token[1:]):
            return tokens[index + 1]
    return None


def stream_and_parse_codex_json_output(
    process: subprocess.Popen[str],
    suppress_output: bool = False,
) -> CodexStreamResult:
    """Stream stdout as NDJSON events and extract assistant text from Codex."""
    assistant_texts: list[str] = []
    error_events: list[str] = []
    pending_reasoning: list[dict[str, object]] = []
    turn_integrity = _CodexTurnIntegrityState()
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
                turn_integrity,
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
    stranded_commands = turn_integrity.stranded_commands()
    integrity_error = (
        turn_integrity.integrity_error(stranded_commands) if return_code == 0 else None
    )
    return CodexStreamResult(
        content=combined_text,
        stderr_content=stderr_content,
        return_code=return_code,
        stranded_commands=stranded_commands,
        integrity_error=integrity_error,
    )


def _process_codex_json_line(
    line: str,
    assistant_texts: list[str],
    suppress_output: bool,
    error_events: list[str] | None = None,
    live_reply_file: IO[str] | None = None,
    thinking_file: IO[str] | None = None,
    pending_reasoning: list[dict[str, object]] | None = None,
    timestamps_file: IO[str] | None = None,
    turn_integrity: _CodexTurnIntegrityState | None = None,
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
    except json.JSONDecodeError as exc:
        record_stdout_json_decode_diagnostic("codex", line, exc)
        return
    if not isinstance(event, Mapping):
        return

    if turn_integrity is not None:
        turn_integrity.observe(event)

    event_type = event.get("type")
    append_codex_tool_call_event(event)

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
        if assistant_texts or live_reply_file.tell() > 0:
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
