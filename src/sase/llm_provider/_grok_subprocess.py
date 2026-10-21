"""Grok subprocess management and session output recovery."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from urllib.parse import quote

from ._subprocess import (
    ProviderTurnState,
    start_completion_watchdog,
    start_interrupt_monitor,
    stream_and_parse_messages_json_output,
)
from ._subprocess_artifacts import open_live_reply_file
from ._subprocess_reap import teardown_stall_for
from ._tool_calls import append_grok_tool_call_event


def _grok_executable_not_found_error(command: str) -> FileNotFoundError:
    """Build an actionable missing-Grok diagnostic."""
    return FileNotFoundError(
        "Unable to launch Grok Build executable "
        f"{command!r}. Set SASE_GROK_PATH to the Grok Build binary, ensure "
        "'grok' is discoverable on PATH, or run `sase agent-cli install grok`. "
        "If PATH resolves to grok-dev or Homebrew's deprecated regex tool, "
        "point SASE_GROK_PATH at the @xai-official/grok binary."
    )


def _grok_home() -> Path:
    """Return Grok's home directory: ``$GROK_HOME`` if set, else ``~/.grok``."""
    raw = os.environ.get("GROK_HOME", "").strip()
    if raw:
        return Path(raw)
    return Path.home() / ".grok"


def _resolve_grok_session_dir(cwd: str, session_id: str) -> Path | None:
    """Return Grok's session directory for *cwd* and *session_id*, if present.

    The CLI stores sessions at
    ``<grok_home>/sessions/<quote(cwd, safe="")>/<session_id>/``. When that
    exact path is missing, fall back to globbing
    ``<grok_home>/sessions/*/<session_id>`` because session ids are fresh
    UUIDs.
    """
    home = _grok_home()
    exact = home / "sessions" / quote(cwd, safe="") / session_id
    if exact.is_dir():
        return exact
    matches = sorted(
        match for match in home.glob(f"sessions/*/{session_id}") if match.is_dir()
    )
    return matches[0] if matches else None


class _GrokTurnEndProbe:
    """Incremental ``events.jsonl`` reader for Grok's turn lifecycle."""

    def __init__(self, cwd: str, session_id: str) -> None:
        self._cwd = cwd
        self._session_id = session_id
        self._session_dir: Path | None = None
        self._offset = 0
        self._partial = b""
        self._state: ProviderTurnState | None = None

    def __call__(self) -> ProviderTurnState | None:
        try:
            return self._poll()
        except Exception:
            return None

    def _poll(self) -> ProviderTurnState | None:
        if self._session_dir is None:
            self._session_dir = _resolve_grok_session_dir(self._cwd, self._session_id)
        if self._session_dir is None:
            return None
        path = self._session_dir / "events.jsonl"
        try:
            with path.open("rb") as handle:
                handle.seek(self._offset)
                chunk = handle.read()
                self._offset = handle.tell()
        except OSError:
            return None
        if not chunk and not self._partial:
            return self._state
        buf = self._partial + chunk
        lines = buf.split(b"\n")
        self._partial = lines[-1]
        for raw in lines[:-1]:
            self._ingest_line(raw)
        return self._state

    def _ingest_line(self, raw: bytes) -> None:
        stripped = raw.strip()
        if not stripped:
            return
        try:
            event = json.loads(stripped.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(event, dict):
            return
        event_type = event.get("type")
        if event_type == "turn_started":
            self._state = ProviderTurnState("started")
        elif event_type == "turn_ended":
            outcome = event.get("outcome")
            self._state = ProviderTurnState(
                "ended", outcome if isinstance(outcome, str) else None
            )


def _assistant_chat_text(content: object) -> str | None:
    """Return non-empty assistant text from a chat-history ``content`` field."""
    if isinstance(content, str):
        return content if content.strip() else None
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    joined = "".join(parts)
    return joined if joined.strip() else None


def _final_assistant_from_chat_history(session_dir: Path) -> str | None:
    """Return the last assistant entry after the last ``tool_result`` entry."""
    path = session_dir / "chat_history.jsonl"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    last_tool = -1
    last_assistant: str | None = None
    for index, line in enumerate(text.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if event_type == "tool_result":
            last_tool = index
            continue
        if event_type != "assistant" or index <= last_tool:
            continue
        extracted = _assistant_chat_text(event.get("content"))
        if extracted:
            last_assistant = extracted
    return last_assistant


def _append_recovered_live_reply(text: str) -> None:
    """Append recovered final-reply text to ``live_reply.md`` when present."""
    live_reply_file = open_live_reply_file()
    if live_reply_file is None:
        return
    try:
        if live_reply_file.tell() > 0:
            live_reply_file.write("\n\n")
        live_reply_file.write(text)
        live_reply_file.flush()
    except OSError:
        pass
    finally:
        live_reply_file.close()


def _recover_grok_final_reply(
    process: subprocess.Popen[str],
    content: str,
    cwd: str,
    session_id: str,
) -> str:
    """Append grok's final chat-history assistant after a turn-end reap.

    Best-effort: any read or parse failure leaves *content* unchanged.
    """
    try:
        stall = teardown_stall_for(process)
        if stall is None or stall.trigger != "provider_turn_end":
            return content
        session_dir = _resolve_grok_session_dir(cwd, session_id)
        if session_dir is None:
            return content
        recovered = _final_assistant_from_chat_history(session_dir)
        if recovered is None:
            return content
        if content.endswith(recovered) or content.rstrip().endswith(recovered.rstrip()):
            return content
        _append_recovered_live_reply(recovered)
        if not content:
            return recovered
        if content.endswith("\n\n"):
            return content + recovered
        if content.endswith("\n"):
            return content + "\n" + recovered
        return content + "\n\n" + recovered
    except Exception:
        return content


class GrokSubprocessMixin:
    """Subprocess execution methods used by the invocation mixin."""

    def _run_subprocess(
        self,
        args: list[str],
        prompt: str,
        suppress_output: bool,
        *,
        env_overrides: dict[str, str] | None = None,
        session_id: str | None = None,
        cwd: str | None = None,
    ) -> tuple[str, str, int, dict[str, int]]:
        """Run the Grok Build subprocess and parse its Messages JSON stream."""
        try:
            if env_overrides is None:
                process = subprocess.Popen(
                    args,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            else:
                env = os.environ.copy()
                env.update(env_overrides)
                process = subprocess.Popen(
                    args,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env,
                )
        except FileNotFoundError as exc:
            raise _grok_executable_not_found_error(args[0]) from exc

        if process.stdin:
            process.stdin.write(prompt)
            process.stdin.close()

        start_interrupt_monitor(
            process,
            on_interrupt=lambda msg: setattr(self, "_pending_interrupt_message", msg),
        )
        session_cwd = os.getcwd() if cwd is None else cwd
        probe = _GrokTurnEndProbe(session_cwd, session_id) if session_id else None
        start_completion_watchdog(process, runtime="grok", turn_end_probe=probe)

        content, stderr_content, return_code, usage = (
            stream_and_parse_messages_json_output(
                process,
                suppress_output=suppress_output,
                runtime="grok",
                tool_call_writer=append_grok_tool_call_event,
                thinking_sink=True,
            )
        )
        if session_id:
            content = _recover_grok_final_reply(
                process, content, session_cwd, session_id
            )
        return content, stderr_content, return_code, usage
