"""Shared streaming fixtures for mounted live-reply follow tests."""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import time
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.ace.tui.widgets.prompt_panel._live_reply_follow import (
    _contains_live_reply_region,
)
from sase.llm_provider._subprocess import stream_and_parse_muse_json_output
from tests.ace.tui.visual._ace_png_snapshot_helpers import wait_for_visual_idle
from tests.llm_provider._muse_commentary_helpers import commentary_record

MOUNTED_MUSE_SESSION_ID = "mounted-stream-session"
_MOUNTED_SESSION_DATE_PARTS = ("2026", "10", "03")

MOUNTED_COMMENTARY_1 = "First tool phase running: gathering context for the reply."
MOUNTED_COMMENTARY_2 = "Second tool phase running: assembling the final answer."
MOUNTED_DELTA_1 = "A reply can stream in pieces: the words stay together"
MOUNTED_DELTA_2 = " and keep growing."
MOUNTED_ANSWER = (
    "A reply can stream in pieces: the words stay together and keep growing."
)


def _envelope(payload_type: str, payload: dict[str, object]) -> str:
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


def _delta(text: str) -> str:
    return _envelope(
        "run.output.delta",
        {
            "command_id": "mounted-stream",
            "run_stream": {"id": "mounted-stream", "kind": "run"},
            "text": text,
        },
    )


def gated_muse_script(*, session_id: str = MOUNTED_MUSE_SESSION_ID) -> str:
    """Emit lifecycle events on stdout while commentary flows via session log.

    Matches real Muse 1.4.13: during tool phases stdout carries only
    ``task.lifecycle.*`` (plus ``run.model.configured``) and never mid-run
    ``run.output.delta``. The script creates the session log itself after it
    starts and appends one commentary record per stage, flushing each. The
    last stage commits the unphased final message to the log, then emits the
    final-answer deltas plus ``run.terminal.completed`` on stdout.
    """
    records = {
        "commentary_1": commentary_record(
            session_id=session_id,
            text=MOUNTED_COMMENTARY_1,
            message_id="msg-1",
            sequence=1,
        ),
        "commentary_2": commentary_record(
            session_id=session_id,
            text=MOUNTED_COMMENTARY_2,
            message_id="msg-2",
            sequence=2,
        ),
        "final_message": commentary_record(
            session_id=session_id,
            text=MOUNTED_ANSWER,
            message_id="msg-final",
            sequence=3,
            phase=None,
        ),
    }
    return (
        """
import json
import os
import sys
import time
from pathlib import Path

session_id = _session_id
date_parts = _date_parts
commentary_1 = _commentary_1
commentary_2 = _commentary_2
final_message = _final_message

def envelope(kind, payload):
    return (json.dumps({
        "schema_version": 1,
        "record_type": "event",
        "durability": "durable",
        "payload_type": kind,
        "payload_schema_version": 1,
        "payload": payload,
    }) + "\\n").encode()

def append_log(record):
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(record)
        handle.flush()
        os.fsync(handle.fileno())

def wait_for(path):
    deadline = time.monotonic() + 8
    while not Path(path).exists() and time.monotonic() < deadline:
        time.sleep(0.005)
    if not Path(path).exists():
        raise SystemExit(42)

xdg = os.environ["XDG_DATA_HOME"]
log_dir = Path(xdg).joinpath("muse", "sessions", *date_parts, session_id)
log_dir.mkdir(parents=True, exist_ok=True)
log_path = log_dir / "session.jsonl"
log_path.write_text("", encoding="utf-8")

command = {"command_id": "mounted-stream",
           "run_stream": {"id": "mounted-stream", "kind": "run"}}
append_log(commentary_1)
os.write(1, envelope("task.lifecycle.started",
                     {"event": {"kind": "started"}}))
os.write(1, envelope("run.model.configured",
                     {"model_id": "muse-spark-1.2",
                      "provider_id": "muse"}))
Path(sys.argv[1]).write_text("first batch sent", encoding="utf-8")
wait_for(sys.argv[2])
append_log(commentary_2)
Path(sys.argv[3]).write_text("second batch sent", encoding="utf-8")
wait_for(sys.argv[4])
append_log(final_message)
os.write(1, (_delta1 + _delta2).encode())
os.write(1, envelope("run.terminal.completed", {
    **command,
    "terminal": "completed",
    "reason": None,
    "text": _answer,
}))
Path(sys.argv[5]).write_text("terminal sent", encoding="utf-8")
""".replace(
            "_session_id",
            repr(session_id),
        )
        .replace(
            "_date_parts",
            repr(_MOUNTED_SESSION_DATE_PARTS),
        )
        .replace(
            "_commentary_1",
            repr(records["commentary_1"]),
        )
        .replace(
            "_commentary_2",
            repr(records["commentary_2"]),
        )
        .replace(
            "_final_message",
            repr(records["final_message"]),
        )
        .replace(
            "_delta1",
            repr(_delta(MOUNTED_DELTA_1)),
        )
        .replace(
            "_delta2",
            repr(_delta(MOUNTED_DELTA_2)),
        )
        .replace(
            "_answer",
            repr(MOUNTED_ANSWER),
        )
    )


def reply_card_text(page: AcePage) -> str:
    detail = page.app.query_one("#agent-detail-panel")
    card = detail._main_deck_document.card("reply")
    assert card is not None
    console = Console(file=StringIO(), record=True, width=120)
    console.print(card)
    return console.export_text()


async def wait_for_page(page: AcePage, predicate: Any, description: str) -> None:
    deadline = asyncio.get_running_loop().time() + 5.0
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"timed out waiting for {description}\n{page.screen}")
        await page.pause(0.025)


async def exercise_gated_stream(
    page: AcePage,
    panel: AgentPromptPanel,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stream_dir: Path,
    *,
    expected_identity: Any,
    expected_dir: Path,
    expected_dividers: int | None = 1,
    old_text: str | None = None,
) -> None:
    reply_path = stream_dir / "live_reply.md"
    timestamps_path = stream_dir / "live_reply_timestamps.jsonl"
    assert panel._live_reply_source is not None
    assert panel._live_reply_source.reply_identity == expected_identity
    assert panel._live_reply_source.reply_path.startswith(str(expected_dir))
    assert _contains_live_reply_region(
        panel._last_prompt_panel_content, expected_identity
    )
    if old_text is not None:
        assert old_text in reply_card_text(page)

    route_calls: list[tuple[Path, ...]] = []
    on_live_reply_artifact_change = panel.on_live_reply_artifact_change

    def track_live_reply_route(paths: tuple[Path, ...]) -> None:
        route_calls.append(paths)
        on_live_reply_artifact_change(paths)

    monkeypatch.setattr(panel, "on_live_reply_artifact_change", track_live_reply_route)
    await page.press("ctrl+j")
    await wait_for_visual_idle(page)

    refresh_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    schedule_refresh = page.app._schedule_agents_async_refresh

    def track_refresh(*args: Any, **kwargs: Any) -> Any:
        refresh_calls.append((args, kwargs))
        return schedule_refresh(*args, **kwargs)

    monkeypatch.setattr(page.app, "_schedule_agents_async_refresh", track_refresh)

    # The session-log tail resolves its log through XDG_DATA_HOME in this
    # same process, so point it at a per-test fake home the fixture populates.
    xdg_home = tmp_path / "xdg-home"
    xdg_home.mkdir(exist_ok=True)
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg_home))

    first_sent = tmp_path / "first-sent"
    release_second = tmp_path / "release-second"
    second_sent = tmp_path / "second-sent"
    release_terminal = tmp_path / "release-terminal"
    terminal_sent = tmp_path / "terminal-sent"
    process = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-c",
            gated_muse_script(),
            str(first_sent),
            str(release_second),
            str(second_sent),
            str(release_terminal),
            str(terminal_sent),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    parser_task = asyncio.create_task(
        asyncio.to_thread(
            stream_and_parse_muse_json_output,
            process,
            suppress_output=True,
            session_id=MOUNTED_MUSE_SESSION_ID,
        )
    )
    try:
        await wait_for_page(page, first_sent.exists, "first commentary record")
        await wait_for_page(
            page,
            lambda: reply_path.read_text(encoding="utf-8").startswith(
                MOUNTED_COMMENTARY_1
            ),
            "tail to append the first commentary chunk",
        )
        assert process.poll() is None
        assert not terminal_sent.exists()
        assert not (stream_dir / "done.json").exists()

        await wait_for_page(
            page,
            lambda: not page.app._nav_gate.is_navigating(),
            "navigation settles before the watcher route",
        )
        page.app._on_artifact_change((reply_path, timestamps_path))
        assert len(route_calls) == 1
        await wait_for_page(
            page,
            lambda: MOUNTED_COMMENTARY_1 in reply_card_text(page),
            "first commentary in the mounted Reply card",
        )
        assert process.poll() is None
        assert timestamps_path.read_text(encoding="utf-8").count("\n") == 1
        if expected_dividers is not None:
            assert (
                len(re.findall(r"─── \d{2}:\d{2}:\d{2}", reply_card_text(page)))
                == expected_dividers
            )
        if old_text is not None:
            assert reply_card_text(page).count(old_text) == 1

        release_second.touch()
        await wait_for_page(page, second_sent.exists, "second commentary record")
        await wait_for_page(
            page,
            lambda: reply_path.read_text(encoding="utf-8").endswith(
                MOUNTED_COMMENTARY_2
            ),
            "tail to append the second commentary chunk",
        )
        assert process.poll() is None
        assert not terminal_sent.exists()

        panel._live_reply_last_probe = time.monotonic() - 2
        panel.maybe_probe_live_reply_drift()
        await wait_for_page(
            page,
            lambda: MOUNTED_COMMENTARY_2 in reply_card_text(page),
            "polling backstop to paint the latest bytes",
        )
        assert reply_card_text(page).count(MOUNTED_COMMENTARY_1) == 1
        assert reply_card_text(page).count(MOUNTED_COMMENTARY_2) == 1
        assert timestamps_path.read_text(encoding="utf-8").count("\n") == 2
        if expected_dividers is not None:
            assert (
                len(re.findall(r"─── \d{2}:\d{2}:\d{2}", reply_card_text(page)))
                == expected_dividers + 1
            )
        assert refresh_calls == []
        if old_text is not None:
            assert reply_card_text(page).count(old_text) == 1

        release_terminal.touch()
        result = await asyncio.wait_for(parser_task, timeout=5)
        assert process.wait(timeout=1) == 0
        assert result[0] == MOUNTED_ANSWER
        assert terminal_sent.exists()
        # The unphased final message committed to the session log must not
        # duplicate the terminal answer in the Reply card.
        panel._live_reply_last_probe = time.monotonic() - 2
        panel.maybe_probe_live_reply_drift()
        await wait_for_page(
            page,
            lambda: MOUNTED_ANSWER in reply_card_text(page),
            "final answer below the commentary",
        )
        assert reply_card_text(page).count(MOUNTED_ANSWER) == 1
        assert reply_path.read_text(encoding="utf-8").count(MOUNTED_ANSWER) == 1
        assert reply_path.read_text(encoding="utf-8").index(
            MOUNTED_COMMENTARY_2
        ) < reply_path.read_text(encoding="utf-8").index(MOUNTED_ANSWER)
    finally:
        for gate in (release_second, release_terminal):
            gate.touch(exist_ok=True)
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        if not parser_task.done():
            try:
                await asyncio.wait_for(parser_task, timeout=3)
            except Exception:
                pass
