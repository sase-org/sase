"""Builders for Muse 1.4.13 session-log commentary tests.

Phase ``mounted-fixture`` reuses ``build_fake_muse_exec_script`` so the
mounted TUI fixture can emit commentary through a session log instead of
mid-run stdout deltas.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from sase.llm_provider._subprocess_muse import stream_and_parse_muse_json_output

_SESSION_DATE_PARTS = ("2026", "10", "26")


def commentary_record(
    *,
    session_id: str,
    text: str,
    message_id: str | None = "msg-1",
    sequence: int = 1,
    phase: str | None = "commentary",
    event_kind: str = "assistant_message_committed",
    payload_kind: str = "run",
    payload_type: str = "runtime.session",
    run_id: str = "run-1",
    record_id: str | None = None,
) -> str:
    """Return one compact 1.4.13 ``assistant_message_committed`` JSONL line."""
    event: dict[str, object] = {"kind": event_kind, "text": text}
    if message_id is not None:
        event["message_id"] = message_id
    if phase is not None:
        event["phase"] = phase
    record = {
        "schema_version": 1,
        "id": record_id or f"rec-{sequence}",
        "stream": {"kind": "session", "id": session_id},
        "sequence": sequence,
        "recorded_at": 1792463279757454,
        "record_type": "event",
        "durability": "durable",
        "payload_type": payload_type,
        "payload_schema_version": 1,
        "payload": {
            "kind": payload_kind,
            "run_id": run_id,
            "event": event,
        },
    }
    return json.dumps(record, separators=(",", ":")) + "\n"


def retained_frame_line(child_record: str) -> str:
    """Wrap *child_record* as a ``retained_frame`` with escaped ``record_json``."""
    frame = {
        "schema_version": 1,
        "record_type": "retained_frame",
        "payload_type": "retained_frame",
        "children": [{"record_json": child_record.strip()}],
    }
    return json.dumps(frame, separators=(",", ":")) + "\n"


def marker_record(*, session_id: str, sequence: int = 99) -> str:
    """Return a non-commentary ``runtime.session`` marker line."""
    return commentary_record(
        session_id=session_id,
        text="marker",
        message_id=None,
        sequence=sequence,
        phase=None,
        event_kind="marker",
    )


def reasoning_record(*, session_id: str, sequence: int = 98) -> str:
    """Return a thinking record that must never become live-reply text."""
    return commentary_record(
        session_id=session_id,
        text="thinking about the plan",
        message_id="reason-1",
        sequence=sequence,
        phase="commentary",
        event_kind="reasoning_summary_delta",
    )


def install_muse_session_log(
    tmp_path: Path,
    session_id: str,
    body: str,
    *,
    date_parts: tuple[str, str, str] = _SESSION_DATE_PARTS,
) -> Path:
    """Materialize a Muse session log under a fake ``XDG_DATA_HOME`` root."""
    session_dir = tmp_path.joinpath("muse", "sessions", *date_parts, session_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    log_path = session_dir / "session.jsonl"
    log_path.write_text(body, encoding="utf-8")
    return log_path


def install_sessions_root_log(
    sessions_root: Path,
    session_id: str,
    body: str,
    *,
    date_parts: tuple[str, str, str] = _SESSION_DATE_PARTS,
) -> Path:
    """Materialize a log directly under a ``sessions_root`` glob tree."""
    session_dir = sessions_root.joinpath(*date_parts, session_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    log_path = session_dir / "session.jsonl"
    log_path.write_text(body, encoding="utf-8")
    return log_path


def muse_stdout_envelope(payload_type: str, payload: dict[str, object]) -> str:
    """Return one ``muse exec --json`` stdout envelope."""
    return (
        json.dumps(
            {
                "schema_version": 1,
                "record_type": "event",
                "durability": "durable",
                "payload_type": payload_type,
                "payload_schema_version": 1,
                "payload": payload,
            }
        )
        + "\n"
    )


def muse_delta(text: str, command_id: str = "cmd-1") -> str:
    return muse_stdout_envelope(
        "run.output.delta",
        {
            "kind": "run_output_delta",
            "text": text,
            "command_id": command_id,
            "run_stream": {"id": command_id, "kind": "run"},
        },
    )


def muse_terminal(text: str, command_id: str = "cmd-1") -> str:
    return muse_stdout_envelope(
        "run.terminal.completed",
        {"terminal": "completed", "text": text, "command_id": command_id},
    )


def muse_task_lifecycle(kind: str = "started") -> str:
    return muse_stdout_envelope(
        f"task.lifecycle.{kind}",
        {"event": {"kind": kind}},
    )


def run_muse_stream(
    payload: str,
    *,
    session_id: str | None = None,
    exit_code: int = 0,
    suppress_output: bool = True,
) -> tuple[str, str, int, dict[str, int]]:
    """Replay *payload* on a real subprocess's stdout and parse the stream."""
    script = "import sys\nsys.stdout.write(sys.argv[1])\nsys.exit(int(sys.argv[2]))\n"
    process = subprocess.Popen(
        [sys.executable, "-c", script, payload, str(exit_code)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return stream_and_parse_muse_json_output(
        process, suppress_output=suppress_output, session_id=session_id
    )


def build_fake_muse_exec_script(
    *,
    session_id: str,
    commentaries: Sequence[str],
    final_answer: str,
    date_parts: tuple[str, str, str] = _SESSION_DATE_PARTS,
) -> str:
    """Return a fake ``muse exec`` that logs commentary, then waits on a gate.

    Argv: ``ready_path``, ``release_path``. After start it writes the session
    log, emits only ``task.lifecycle.*`` on stdout, and creates *ready_path*.
    After *release_path* appears it writes the final-answer deltas and the
    terminal event. Phase ``mounted-fixture`` can extend this choreography.
    """
    records = [
        commentary_record(
            session_id=session_id,
            text=text,
            message_id=f"msg-{index}",
            sequence=index,
        )
        for index, text in enumerate(commentaries, start=1)
    ]
    return f"""
import json
import os
import sys
import time
from pathlib import Path

session_id = {session_id!r}
date_parts = {date_parts!r}
records = {records!r}
final_answer = {final_answer!r}

xdg = os.environ["XDG_DATA_HOME"]
log_dir = Path(xdg).joinpath("muse", "sessions", *date_parts, session_id)
log_dir.mkdir(parents=True, exist_ok=True)
log_path = log_dir / "session.jsonl"
with log_path.open("w", encoding="utf-8") as handle:
    for record in records:
        handle.write(record)
        handle.flush()
        os.fsync(handle.fileno())

def envelope(payload_type, payload):
    return json.dumps({{
        "schema_version": 1,
        "record_type": "event",
        "durability": "durable",
        "payload_type": payload_type,
        "payload_schema_version": 1,
        "payload": payload,
    }}) + "\\n"

os.write(1, envelope("task.lifecycle.started", {{"event": {{"kind": "started"}}}}).encode())
Path(sys.argv[1]).write_text("ready", encoding="utf-8")

deadline = time.monotonic() + 8
release = Path(sys.argv[2])
while not release.exists() and time.monotonic() < deadline:
    time.sleep(0.01)
if not release.exists():
    raise SystemExit(42)

command = {{"command_id": "cmd-1", "run_stream": {{"id": "cmd-1", "kind": "run"}}}}
os.write(1, envelope("run.output.delta", {{"kind": "run_output_delta", "text": final_answer, **command}}).encode())
os.write(1, envelope("run.terminal.completed", {{"terminal": "completed", "text": final_answer, "command_id": "cmd-1"}}).encode())
"""
