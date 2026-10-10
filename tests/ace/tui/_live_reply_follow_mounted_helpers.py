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


def gated_muse_script() -> str:
    """Emit two deltas, then wait at gates before the second delta and terminal."""
    return (
        """
import json
import os
import sys
import time
from pathlib import Path

def envelope(kind, payload):
    return (json.dumps({
        "schema_version": 1,
        "record_type": "event",
        "durability": "durable",
        "payload_type": kind,
        "payload_schema_version": 1,
        "payload": payload,
    }) + "\\n").encode()

def wait_for(path):
    deadline = time.monotonic() + 8
    while not Path(path).exists() and time.monotonic() < deadline:
        time.sleep(0.005)
    if not Path(path).exists():
        raise SystemExit(42)

command = {"command_id": "mounted-stream",
           "run_stream": {"id": "mounted-stream", "kind": "run"}}
os.write(1, (_delta1 + _delta2).encode())
Path(sys.argv[1]).write_text("first batch sent", encoding="utf-8")
wait_for(sys.argv[2])
os.write(1, _delta3.encode())
Path(sys.argv[3]).write_text("second batch sent", encoding="utf-8")
wait_for(sys.argv[4])
os.write(1, envelope("run.terminal.completed", {
    **command,
    "terminal": "completed",
    "reason": None,
    "text": _answer,
}))
Path(sys.argv[5]).write_text("terminal sent", encoding="utf-8")
""".replace(
            "_delta1",
            repr(_delta("A reply can stream in pieces: ")),
        )
        .replace(
            "_delta2",
            repr(_delta("the words stay together")),
        )
        .replace(
            "_delta3",
            repr(_delta(" and keep growing.")),
        )
        .replace(
            "_answer",
            repr(
                "A reply can stream in pieces: the words stay together and keep growing."
            ),
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
        )
    )
    try:
        await wait_for_page(page, first_sent.exists, "first Muse delta batch")
        await wait_for_page(
            page,
            lambda: reply_path.read_text(encoding="utf-8").startswith(
                "A reply can stream in pieces: the words stay together"
            ),
            "parser to append the first delta batch",
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
            lambda: "A reply can stream in pieces:" in reply_card_text(page),
            "first partial reply in the mounted Reply card",
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
        await wait_for_page(page, second_sent.exists, "second Muse delta")
        await wait_for_page(
            page,
            lambda: reply_path.read_text(encoding="utf-8").endswith(
                " and keep growing."
            ),
            "parser to append the final delta",
        )
        assert process.poll() is None
        assert not terminal_sent.exists()

        panel._live_reply_last_probe = time.monotonic() - 2
        panel.maybe_probe_live_reply_drift()
        await wait_for_page(
            page,
            lambda: "and keep growing." in reply_card_text(page),
            "polling backstop to paint the latest bytes",
        )
        assert reply_card_text(page).count("A reply can stream in pieces:") == 1
        assert refresh_calls == []
        if old_text is not None:
            assert reply_card_text(page).count(old_text) == 1

        release_terminal.touch()
        result = await asyncio.wait_for(parser_task, timeout=5)
        assert process.wait(timeout=1) == 0
        assert result[0] == (
            "A reply can stream in pieces: the words stay together and keep growing."
        )
        assert terminal_sent.exists()
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
